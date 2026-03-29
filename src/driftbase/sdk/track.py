"""
Zero-friction @track() decorator for agent runs.

Auto-detects framework (LangGraph → LangChain → LlamaIndex → raw OpenAI → generic), captures
tool calls, latency, and outcome, and writes to local SQLite and Azure Cloud without blocking.
Never raises to the caller; all errors logged to ~/.driftbase/errors.log.
"""

from __future__ import annotations

import functools
import hashlib
import inspect
import json
import logging
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

import requests

from driftbase.config import get_settings
from driftbase.local.local_store import _log_track_error, enqueue_run

# Track persisted budget configs to avoid repeated writes
_budget_configs_persisted: set[tuple[str, str]] = set()

# Track persisted change events to avoid repeated writes
_change_events_persisted: set[tuple[str, str, str]] = (
    set()
)  # (agent_id, version, change_type)

# Ensure logger doesn't pollute the user's stdout by default
logger = logging.getLogger("driftbase")
logger.setLevel(logging.ERROR)

# Decision outcome for semantic_cluster / reporting
OUTCOME_RESOLVED = "resolved"
OUTCOME_ESCALATED = "escalated"
OUTCOME_FALLBACK = "fallback"
OUTCOME_ERROR = "error"

# Pre-compiled regexes for zero-latency PII scrubbing (GDPR/EU AI Act)
PII_PATTERNS = [
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b"), "[EMAIL]"),
    (re.compile(r"\b(?:\d[ -]*?){13,16}\b"), "[CREDIT_CARD]"),
    (re.compile(r"\b(?:[A-Z]{2}[0-9]{2})(?:[ ]?[0-9a-zA-Z]{4}){3,5}\b"), "[IBAN]"),
    (re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), "[IP_ADDRESS]"),
    (
        re.compile(
            r"\+?\d{1,4}?[-.\s]?\(?\d{1,3}?\)?[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}"
        ),
        "[PHONE]",
    ),
]


def _scrub_pii(data: Any) -> Any:
    """Recursively scrub PII if enabled in settings."""
    if not get_settings().DRIFTBASE_SCRUB_PII:
        return data

    if isinstance(data, str):
        for pattern, replacement in PII_PATTERNS:
            data = pattern.sub(replacement, data)
        return data
    elif isinstance(data, dict):
        return {k: _scrub_pii(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_scrub_pii(item) for item in data]
    elif isinstance(data, tuple):
        return tuple(_scrub_pii(item) for item in data)
    return data


@dataclass
class RunContext:
    """Mutable context for a single tracked run."""

    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    tool_calls: list[dict[str, Any]] = field(
        default_factory=list
    )  # name, order, input_hash, output_hash, latency_ms
    decision_outcome: str = OUTCOME_RESOLVED
    latency_ms: int = 0
    token_usage: dict[str, int] | None = None
    error_type: str | None = None
    retry_count: int = 0
    framework: str = "generic"
    task_input_hash: str = ""
    output_length: int = 0
    output_structure_hash: str = ""
    error_count: int = 0

    # New behavioral metrics
    loop_count: int = 0  # number of tool call iterations before final answer
    tool_call_sequence: list[str] = field(
        default_factory=list
    )  # ordered list of tool names
    time_to_first_tool_ms: int = 0  # milliseconds from start to first tool call

    # Added for Azure Cloud Dashboard UI
    raw_input: str = ""
    raw_output: str = ""
    model_name: str = "unknown"


def _hash_content(content: Any) -> str:
    try:
        serialized = json.dumps(content, sort_keys=True, default=str)
    except Exception:
        serialized = repr(content)
    return hashlib.sha256(serialized.encode()).hexdigest()


def _classify_decision_outcome(result: Any, exception: BaseException | None) -> str:
    if exception is not None:
        return OUTCOME_ERROR
    if result is None:
        return OUTCOME_RESOLVED
    try:
        if isinstance(result, dict):
            out = (
                result.get("outcome")
                or result.get("decision_outcome")
                or result.get("status")
                or ""
            ).lower()
            if out in (
                OUTCOME_ESCALATED,
                OUTCOME_FALLBACK,
                OUTCOME_ERROR,
                OUTCOME_RESOLVED,
            ):
                return out
            if result.get("escalated") is True:
                return OUTCOME_ESCALATED
            if result.get("fallback") is True:
                return OUTCOME_FALLBACK
            if result.get("error") is True:
                return OUTCOME_ERROR
        if hasattr(result, "outcome"):
            v = getattr(result, "outcome", None)
            if isinstance(v, str) and v.lower() in (
                OUTCOME_ESCALATED,
                OUTCOME_FALLBACK,
                OUTCOME_ERROR,
                OUTCOME_RESOLVED,
            ):
                return v.lower()
        if hasattr(result, "escalated") and result.escalated is True:
            return OUTCOME_ESCALATED
        if hasattr(result, "fallback") and result.fallback is True:
            return OUTCOME_FALLBACK
    except Exception:
        pass
    return OUTCOME_RESOLVED


def _compute_structure_hash(content: Any) -> str:
    if isinstance(content, dict):
        structure = {k: type(v).__name__ for k, v in content.items()}
    elif isinstance(content, list):
        structure = {"type": "list", "length": len(content)}
    elif isinstance(content, str):
        structure = {"type": "str", "length": len(content)}
    else:
        structure = {"type": type(content).__name__}
    return _hash_content(structure)


def _detect_framework(func: Callable[..., Any]) -> str:
    try:
        mod = inspect.getmodule(func)
        if mod is not None:
            if "langgraph" in mod.__name__:
                return "langgraph"
            if "langchain" in mod.__name__:
                return "langchain"
            if "llama" in mod.__name__.lower() or "llamaindex" in mod.__name__.lower():
                return "llamaindex"
            if "openai" in mod.__name__:
                return "openai"

        sig = inspect.signature(func)

        # Check parameter annotations
        for param in sig.parameters.values():
            hint = param.annotation
            if hint is inspect.Parameter.empty:
                continue
            hint_str = str(hint)
            if "StateGraph" in hint_str or "langgraph" in str(hint).lower():
                return "langgraph"
            if "Runnable" in hint_str or "langchain" in str(hint):
                return "langchain"
            if "openai" in str(hint).lower() or "ChatCompletion" in hint_str:
                return "openai"

        # Check return annotation
        hint = sig.return_annotation
        if hint != inspect.Parameter.empty and hint is not None:
            hint_str = getattr(hint, "__name__", str(hint))
            if "StateGraph" in hint_str or "langgraph" in str(hint).lower():
                return "langgraph"
            if "Runnable" in hint_str or "langchain" in str(hint):
                return "langchain"
            if "openai" in str(hint).lower() or "ChatCompletion" in hint_str:
                return "openai"
    except Exception:
        pass
    return "generic"


def _build_payload(
    ctx: RunContext,
    session_id: str,
    deployment_version: str,
    environment: str,
    sensitivity: str | None = None,
) -> dict[str, Any]:
    completed = ctx.completed_at or datetime.utcnow()
    tool_sequence_json = json.dumps([t.get("name", "") for t in ctx.tool_calls])

    # Compute verbosity_ratio
    prompt_tokens = (ctx.token_usage or {}).get("prompt", 0) or 0
    completion_tokens = (ctx.token_usage or {}).get("completion", 0) or 0
    verbosity_ratio = completion_tokens / prompt_tokens if prompt_tokens > 0 else 0.0

    # Serialize tool_call_sequence to JSON
    tool_call_sequence_json = json.dumps(ctx.tool_call_sequence)

    payload = {
        "session_id": session_id,
        "deployment_version": deployment_version,
        "environment": environment,
        "started_at": ctx.started_at,
        "completed_at": completed,
        "task_input_hash": ctx.task_input_hash or "none",
        "tool_sequence": tool_sequence_json,
        "tool_call_count": len(ctx.tool_calls),
        "output_length": ctx.output_length,
        "output_structure_hash": ctx.output_structure_hash or "none",
        "latency_ms": ctx.latency_ms,
        "error_count": ctx.error_count,
        "retry_count": ctx.retry_count,
        "semantic_cluster": ctx.decision_outcome,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        # New behavioral metrics
        "loop_count": ctx.loop_count,
        "tool_call_sequence": tool_call_sequence_json,
        "time_to_first_tool_ms": ctx.time_to_first_tool_ms,
        "verbosity_ratio": verbosity_ratio,
    }

    if sensitivity is not None:
        payload["sensitivity"] = sensitivity

    return payload


def _capture_generic(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    ctx: RunContext,
) -> Any:
    start = time.perf_counter()
    result = None
    try:
        result = func(*args, **kwargs)
        return result
    finally:
        ctx.latency_ms = int((time.perf_counter() - start) * 1000)
        ctx.completed_at = datetime.utcnow()
        if result is not None:
            try:
                if hasattr(result, "tool_calls"):
                    for tc in getattr(result, "tool_calls", []) or []:
                        name = (
                            getattr(tc, "function", tc)
                            if hasattr(tc, "function")
                            else tc
                        )
                        if isinstance(name, dict):
                            tool_name = name.get("name", "unknown")
                            ctx.tool_calls.append({"name": tool_name})
                            ctx.tool_call_sequence.append(tool_name)
                        else:
                            tool_name = getattr(name, "name", str(name))
                            ctx.tool_calls.append({"name": tool_name})
                            ctx.tool_call_sequence.append(tool_name)
                        # Track time to first tool
                        if len(ctx.tool_call_sequence) == 1:
                            ctx.time_to_first_tool_ms = int(
                                (time.perf_counter() - start) * 1000
                            )
                elif isinstance(result, dict) and "tool_calls" in result:
                    for tc in result["tool_calls"] or []:
                        tool_name = tc.get("function", {}).get("name", "unknown")
                        ctx.tool_calls.append({"name": tool_name})
                        ctx.tool_call_sequence.append(tool_name)
                        # Track time to first tool
                        if len(ctx.tool_call_sequence) == 1:
                            ctx.time_to_first_tool_ms = int(
                                (time.perf_counter() - start) * 1000
                            )
                # Update loop_count (iterations of tool calls)
                ctx.loop_count = len(ctx.tool_call_sequence)
            except Exception:
                pass


def _capture_openai(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    ctx: RunContext,
) -> Any:
    try:
        openai_mod = __import__("openai", fromlist=["resources"])
        resources = getattr(openai_mod, "resources", None)
        if resources is None:
            return _capture_generic(func, args, kwargs, ctx)
        chat = getattr(resources, "chat", None)
        if chat is None:
            return _capture_generic(func, args, kwargs, ctx)
        completions = getattr(chat, "completions", None)
        if completions is None:
            return _capture_generic(func, args, kwargs, ctx)
        Completions = getattr(completions, "Completions", None)
        if Completions is None:
            return _capture_generic(func, args, kwargs, ctx)
        original_create = Completions.create
    except Exception:
        return _capture_generic(func, args, kwargs, ctx)

    def patched_create(self: Any, *create_args: Any, **create_kwargs: Any) -> Any:
        t0 = time.perf_counter()
        resp = original_create(self, *create_args, **create_kwargs)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        ctx.latency_ms += elapsed_ms
        try:
            ctx.model_name = getattr(resp, "model", "openai")
            if getattr(resp, "choices", None):
                c = resp.choices[0]
                msg = getattr(c, "message", None)
                if msg and getattr(msg, "tool_calls", None):
                    for tc in msg.tool_calls or []:
                        name = "unknown"
                        if hasattr(tc, "function") and tc.function:
                            name = getattr(tc.function, "name", name)
                        ctx.tool_calls.append({"name": name})
                        ctx.tool_call_sequence.append(name)
                        # Track time to first tool
                        if len(ctx.tool_call_sequence) == 1:
                            ctx.time_to_first_tool_ms = elapsed_ms
                    # Update loop_count
                    ctx.loop_count = len(ctx.tool_call_sequence)
            usage = getattr(resp, "usage", None)
            if usage:
                p = getattr(usage, "prompt_tokens", 0) or 0
                c = getattr(usage, "completion_tokens", 0) or 0
                if ctx.token_usage is None:
                    ctx.token_usage = {"prompt": 0, "completion": 0}
                ctx.token_usage["prompt"] = ctx.token_usage.get("prompt", 0) + p
                ctx.token_usage["completion"] = ctx.token_usage.get("completion", 0) + c
        except Exception:
            pass
        return resp

    Completions.create = patched_create
    ctx.framework = "openai"
    try:
        return _capture_generic(func, args, kwargs, ctx)
    finally:
        Completions.create = original_create


def _capture_langchain(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    ctx: RunContext,
) -> Any:
    try:
        from driftbase.sdk.watcher import DriftbaseCallbackHandler
    except ImportError:
        return _capture_generic(func, args, kwargs, ctx)

    handler = DriftbaseCallbackHandler(run_ctx=ctx)
    ctx.framework = "langchain"

    sig = inspect.signature(func)
    params = sig.parameters
    accepts_config = "config" in params or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
    )
    if accepts_config:
        config = kwargs.get("config") or {}
        if not isinstance(config, dict):
            config = {}
        callbacks = list(config.get("callbacks", []))
        callbacks.append(handler)
        kwargs = {**kwargs, "config": {**config, "callbacks": callbacks}}

    return _capture_generic(func, args, kwargs, ctx)


def _capture_langgraph(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    ctx: RunContext,
) -> Any:
    if "langgraph" not in sys.modules:
        return _capture_generic(func, args, kwargs, ctx)

    try:
        from driftbase.sdk.watcher import DriftbaseCallbackHandler
    except ImportError:
        return _capture_generic(func, args, kwargs, ctx)

    handler = DriftbaseCallbackHandler(run_ctx=ctx)
    ctx.framework = "langgraph"

    sig = inspect.signature(func)
    params = sig.parameters
    accepts_config = "config" in params or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
    )
    if accepts_config:
        config = kwargs.get("config") or {}
        if not isinstance(config, dict):
            config = {}
        callbacks = list(config.get("callbacks", []))
        callbacks.append(handler)
        kwargs = {**kwargs, "config": {**config, "callbacks": callbacks}}

    return _capture_generic(func, args, kwargs, ctx)


def _dispatch_to_cloud(ctx: RunContext, explicit_api_key: str | None = None) -> None:
    """Silently dispatch payload to Azure if API key exists. Data is already scrubbed."""
    api_key = explicit_api_key or os.getenv("DRIFTBASE_API_KEY")
    if not api_key:
        return

    def _fire_cloud():
        try:
            p_tokens = (ctx.token_usage or {}).get("prompt", 0)
            c_tokens = (ctx.token_usage or {}).get("completion", 0)

            # Since ctx.raw_input and ctx.raw_output were scrubbed in the wrapper,
            # this payload is completely clean and safe for EU enterprise compliance.
            raw_payload = {
                "status": "error" if ctx.error_count > 0 else "success",
                "latency": ctx.latency_ms,
                "payload": {
                    "model": ctx.model_name
                    if ctx.model_name != "unknown"
                    else ctx.framework,
                    "messages": [{"role": "user", "content": ctx.raw_input}],
                    "response": ctx.raw_output,
                    "prompt_tokens": p_tokens,
                    "completion_tokens": c_tokens,
                    "total_tokens": p_tokens + c_tokens,
                },
            }

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            # Hard 2.0s timeout. Never hang the host application.
            requests.post(
                "https://app-driftbase-eu-92745.azurewebsites.net/api/capture/",
                json=raw_payload,
                headers=headers,
                timeout=2.0,
            )
        except Exception as e:
            # Silently catch network drops or rate limits.
            logger.debug(f"Cloud dispatch failed: {str(e)}")

    threading.Thread(target=_fire_cloud, daemon=True).start()


def track(
    version: str = "unknown",
    environment: str | None = None,
    api_key: str | None = None,
    sensitivity: str | None = None,
    budget: dict[str, Any] | None = None,
    changes: dict[str, Any] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    # Parse budget at decoration time (fail fast on invalid keys)
    budget_config = None
    if budget:
        from driftbase.local.budget import parse_budget

        budget_config = parse_budget(budget)

    # Validate changes at decoration time (fail fast on invalid keys)
    if changes:
        valid_change_types = {
            "model_version",
            "prompt_hash",
            "rag_snapshot",
            "tool_version",
        }
        for key in changes:
            if key not in valid_change_types and not key.startswith("custom_"):
                raise ValueError(
                    f"Unknown change type: '{key}'. "
                    f"Supported types: {', '.join(sorted(valid_change_types))} or any key prefixed with 'custom_'"
                )

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        framework = _detect_framework(func)
        session_id = os.getenv("DRIFTBASE_SESSION_ID", "")

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            env = environment or os.getenv("DRIFTBASE_ENVIRONMENT", "production")

            run_id = _hash_content(str(time.time()) + str(id(func)))[:12]

            # Persist budget config on first run (before function execution, idempotent)
            if budget_config and budget_config.limits:
                session_id = os.getenv("DRIFTBASE_SESSION_ID", "")
                agent_id = session_id or run_id
                config_key = (agent_id, version)
                if config_key not in _budget_configs_persisted:
                    try:
                        from driftbase.backends.factory import get_backend

                        backend = get_backend()
                        backend.write_budget_config(
                            agent_id=agent_id,
                            version=version,
                            config=budget_config.limits,
                            source="decorator",
                        )
                        _budget_configs_persisted.add(config_key)
                    except Exception:
                        pass  # Never crash decorated function

            # Persist change events on first run (before function execution, idempotent)
            if changes:
                session_id = os.getenv("DRIFTBASE_SESSION_ID", "")
                agent_id = session_id or run_id
                for change_type, current_value in changes.items():
                    event_key = (agent_id, version, change_type)
                    if event_key not in _change_events_persisted:
                        try:
                            from driftbase.backends.factory import get_backend

                            backend = get_backend()
                            backend.write_change_event(
                                {
                                    "agent_id": agent_id,
                                    "version": version,
                                    "change_type": change_type,
                                    "previous": None,  # Don't know previous value
                                    "current": str(current_value),
                                    "source": "decorator",
                                }
                            )
                            _change_events_persisted.add(event_key)
                        except Exception:
                            pass  # Never crash decorated function

            ctx = RunContext()
            ctx.framework = framework

            # 1. SCRUB THE INPUT DATA BEFORE HASHING
            safe_args = _scrub_pii(args)
            safe_kwargs = _scrub_pii(kwargs)
            ctx.task_input_hash = _hash_content((safe_args, safe_kwargs))[:32]

            # Capture UI input securely
            msg_data = safe_kwargs.get("messages") or safe_args
            try:
                ctx.raw_input = json.dumps(msg_data, default=str)
            except Exception:
                ctx.raw_input = str(msg_data)

            try:
                if framework == "langgraph":
                    result = _capture_langgraph(func, args, kwargs, ctx)
                elif framework == "langchain":
                    result = _capture_langchain(func, args, kwargs, ctx)
                elif framework == "openai":
                    result = _capture_openai(func, args, kwargs, ctx)
                else:
                    # Generic capture for all other frameworks
                    # Note: For LlamaIndex, use the explicit LlamaIndexTracer from driftbase.integrations
                    result = _capture_generic(func, args, kwargs, ctx)
                ctx.decision_outcome = _classify_decision_outcome(result, None)
            except Exception as e:
                ctx.decision_outcome = OUTCOME_ERROR
                ctx.error_count = 1
                ctx.error_type = type(e).__name__
                ctx.completed_at = datetime.utcnow()
                ctx.raw_output = _scrub_pii(str(e))
                if ctx.latency_ms == 0:
                    ctx.latency_ms = 1
                try:
                    payload = _build_payload(
                        ctx, session_id or run_id, version, env, sensitivity
                    )
                    enqueue_run(payload)
                except Exception as enq_err:
                    _log_track_error(
                        "track_decorator", f"run_id={run_id} enqueue error={enq_err!r}"
                    )

                _dispatch_to_cloud(ctx, api_key)
                raise

            try:
                if result is not None:
                    # Parse objects for clean text and tokens
                    if (
                        hasattr(result, "choices")
                        and isinstance(result.choices, list)
                        and len(result.choices) > 0
                    ):
                        ctx.raw_output = getattr(
                            result.choices[0].message, "content", ""
                        )
                        ctx.framework = "openai"  # Auto-correct framework

                        if hasattr(result, "usage") and result.usage:
                            ctx.token_usage = {
                                "prompt": getattr(result.usage, "prompt_tokens", 0),
                                "completion": getattr(
                                    result.usage, "completion_tokens", 0
                                ),
                            }
                    # Fallbacks for standard strings and dicts
                    elif isinstance(result, str):
                        ctx.raw_output = result
                    elif hasattr(result, "content"):
                        ctx.raw_output = str(getattr(result, "content", ""))
                    else:
                        try:
                            ctx.raw_output = json.dumps(result, default=str)
                        except Exception:
                            ctx.raw_output = str(result)

                    # 2. SCRUB THE OUTPUT DATA BEFORE HASHING
                    ctx.raw_output = _scrub_pii(ctx.raw_output)
                    ctx.output_length = len(ctx.raw_output)
                    ctx.output_structure_hash = _compute_structure_hash(result)

                payload = _build_payload(ctx, session_id or run_id, version, env)
                enqueue_run(payload)
            except Exception as e:
                _log_track_error("track_decorator", f"run_id={run_id} error={e!r}")

            return result

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            env = environment or os.getenv("DRIFTBASE_ENVIRONMENT", "production")

            run_id = _hash_content(str(time.time()) + str(id(func)))[:12]

            # Persist budget config on first run (before function execution, idempotent)
            if budget_config and budget_config.limits:
                session_id = os.getenv("DRIFTBASE_SESSION_ID", "")
                agent_id = session_id or run_id
                config_key = (agent_id, version)
                if config_key not in _budget_configs_persisted:
                    try:
                        from driftbase.backends.factory import get_backend

                        backend = get_backend()
                        backend.write_budget_config(
                            agent_id=agent_id,
                            version=version,
                            config=budget_config.limits,
                            source="decorator",
                        )
                        _budget_configs_persisted.add(config_key)
                    except Exception:
                        pass  # Never crash decorated function

            # Persist change events on first run (before function execution, idempotent)
            if changes:
                session_id = os.getenv("DRIFTBASE_SESSION_ID", "")
                agent_id = session_id or run_id
                for change_type, current_value in changes.items():
                    event_key = (agent_id, version, change_type)
                    if event_key not in _change_events_persisted:
                        try:
                            from driftbase.backends.factory import get_backend

                            backend = get_backend()
                            backend.write_change_event(
                                {
                                    "agent_id": agent_id,
                                    "version": version,
                                    "change_type": change_type,
                                    "previous": None,  # Don't know previous value
                                    "current": str(current_value),
                                    "source": "decorator",
                                }
                            )
                            _change_events_persisted.add(event_key)
                        except Exception:
                            pass  # Never crash decorated function

            ctx = RunContext()
            ctx.framework = framework
            start = time.perf_counter()

            # 1. SCRUB THE INPUT DATA BEFORE HASHING
            safe_args = _scrub_pii(args)
            safe_kwargs = _scrub_pii(kwargs)
            ctx.task_input_hash = _hash_content((safe_args, safe_kwargs))[:32]

            msg_data = safe_kwargs.get("messages") or safe_args
            try:
                ctx.raw_input = json.dumps(msg_data, default=str)
            except Exception:
                ctx.raw_input = str(msg_data)

            try:
                if framework == "langgraph":
                    result = await _capture_langgraph_async(func, args, kwargs, ctx)
                elif framework == "langchain":
                    result = await _capture_langchain_async(func, args, kwargs, ctx)
                elif framework == "openai":
                    result = await _capture_openai_async(func, args, kwargs, ctx)
                else:
                    # Generic capture for all other frameworks
                    # Note: For LlamaIndex, use the explicit LlamaIndexTracer from driftbase.integrations
                    result = await _capture_generic_async(func, args, kwargs, ctx)
                ctx.latency_ms = int((time.perf_counter() - start) * 1000)
                ctx.completed_at = datetime.utcnow()
                ctx.decision_outcome = _classify_decision_outcome(result, None)
            except Exception as e:
                ctx.latency_ms = int((time.perf_counter() - start) * 1000)
                ctx.completed_at = datetime.utcnow()
                ctx.decision_outcome = OUTCOME_ERROR
                ctx.error_count = 1
                ctx.error_type = type(e).__name__
                ctx.raw_output = _scrub_pii(str(e))
                try:
                    payload = _build_payload(
                        ctx, session_id or run_id, version, env, sensitivity
                    )
                    enqueue_run(payload)
                except Exception as enq_err:
                    _log_track_error(
                        "track_decorator_async",
                        f"run_id={run_id} enqueue error={enq_err!r}",
                    )

                _dispatch_to_cloud(ctx, api_key)
                raise

            try:
                if result is not None:
                    if (
                        hasattr(result, "choices")
                        and isinstance(result.choices, list)
                        and len(result.choices) > 0
                    ):
                        ctx.raw_output = getattr(
                            result.choices[0].message, "content", ""
                        )
                        ctx.framework = "openai"

                        if hasattr(result, "usage") and result.usage:
                            ctx.token_usage = {
                                "prompt": getattr(result.usage, "prompt_tokens", 0),
                                "completion": getattr(
                                    result.usage, "completion_tokens", 0
                                ),
                            }
                    elif isinstance(result, str):
                        ctx.raw_output = result
                    elif hasattr(result, "content"):
                        ctx.raw_output = str(getattr(result, "content", ""))
                    else:
                        try:
                            ctx.raw_output = json.dumps(result, default=str)
                        except Exception:
                            ctx.raw_output = str(result)

                    # 2. SCRUB THE OUTPUT DATA BEFORE HASHING
                    ctx.raw_output = _scrub_pii(ctx.raw_output)
                    ctx.output_length = len(ctx.raw_output)
                    ctx.output_structure_hash = _compute_structure_hash(result)

                payload = _build_payload(ctx, session_id or run_id, version, env)
                enqueue_run(payload)
            except Exception as e:
                _log_track_error(
                    "track_decorator_async", f"run_id={run_id} error={e!r}"
                )

            _dispatch_to_cloud(ctx, api_key)

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


async def _capture_generic_async(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    ctx: RunContext,
) -> Any:
    result = await func(*args, **kwargs)
    return result


async def _capture_langchain_async(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    ctx: RunContext,
) -> Any:
    try:
        from driftbase.sdk.watcher import DriftbaseCallbackHandler
    except ImportError:
        return await _capture_generic_async(func, args, kwargs, ctx)

    handler = DriftbaseCallbackHandler(run_ctx=ctx)
    config = kwargs.get("config") or {}
    if not isinstance(config, dict):
        config = {}
    kwargs = {
        **kwargs,
        "config": {
            **config,
            "callbacks": list(config.get("callbacks", [])) + [handler],
        },
    }
    return await func(*args, **kwargs)


async def _capture_langgraph_async(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    ctx: RunContext,
) -> Any:
    if "langgraph" not in sys.modules:
        return await _capture_generic_async(func, args, kwargs, ctx)

    try:
        from driftbase.sdk.watcher import DriftbaseCallbackHandler
    except ImportError:
        return await _capture_generic_async(func, args, kwargs, ctx)

    handler = DriftbaseCallbackHandler(run_ctx=ctx)
    ctx.framework = "langgraph"

    sig = inspect.signature(func)
    params = sig.parameters
    accepts_config = "config" in params or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
    )
    if accepts_config:
        config = kwargs.get("config") or {}
        if not isinstance(config, dict):
            config = {}
        callbacks = list(config.get("callbacks", []))
        callbacks.append(handler)
        kwargs = {**kwargs, "config": {**config, "callbacks": callbacks}}

    return await _capture_generic_async(func, args, kwargs, ctx)


async def _capture_openai_async(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    ctx: RunContext,
) -> Any:
    try:
        openai_mod = __import__("openai", fromlist=["resources"])
        resources = getattr(openai_mod, "resources", None)
        if resources is None:
            return await _capture_generic_async(func, args, kwargs, ctx)
        chat = getattr(resources, "chat", None)
        if chat is None:
            return await _capture_generic_async(func, args, kwargs, ctx)
        completions = getattr(chat, "completions", None)
        if completions is None:
            return await _capture_generic_async(func, args, kwargs, ctx)
        Completions = getattr(completions, "Completions", None)
        if Completions is None:
            return await _capture_generic_async(func, args, kwargs, ctx)
        original_create = Completions.create
    except Exception:
        return await _capture_generic_async(func, args, kwargs, ctx)

    async def patched_create(self: Any, *create_args: Any, **create_kwargs: Any) -> Any:
        t0 = time.perf_counter()
        r = original_create(self, *create_args, **create_kwargs)
        if inspect.iscoroutine(r):
            resp = await r
        else:
            resp = r
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        ctx.latency_ms += elapsed_ms
        try:
            ctx.model_name = getattr(resp, "model", "openai")
            if getattr(resp, "choices", None):
                c = resp.choices[0]
                msg = getattr(c, "message", None)
                if msg and getattr(msg, "tool_calls", None):
                    for tc in msg.tool_calls or []:
                        name = "unknown"
                        if hasattr(tc, "function") and tc.function:
                            name = getattr(tc.function, "name", name)
                        ctx.tool_calls.append({"name": name})
                        ctx.tool_call_sequence.append(name)
                        # Track time to first tool
                        if len(ctx.tool_call_sequence) == 1:
                            ctx.time_to_first_tool_ms = elapsed_ms
                    # Update loop_count
                    ctx.loop_count = len(ctx.tool_call_sequence)
            usage = getattr(resp, "usage", None)
            if usage:
                p = getattr(usage, "prompt_tokens", 0) or 0
                c = getattr(usage, "completion_tokens", 0) or 0
                if ctx.token_usage is None:
                    ctx.token_usage = {"prompt": 0, "completion": 0}
                ctx.token_usage["prompt"] = ctx.token_usage.get("prompt", 0) + p
                ctx.token_usage["completion"] = ctx.token_usage.get("completion", 0) + c
        except Exception:
            pass
        return resp

    Completions.create = patched_create
    ctx.framework = "openai"
    try:
        return await _capture_generic_async(func, args, kwargs, ctx)
    finally:
        Completions.create = original_create
