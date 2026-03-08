"""
Zero-friction @track() decorator for agent runs.

Auto-detects framework (LangGraph → LangChain → LlamaIndex → raw OpenAI → generic), captures
tool calls, latency, and outcome, and writes to local SQLite without blocking.
Never raises to the caller; all errors logged to ~/.driftbase/errors.log.
"""

from __future__ import annotations

import functools
import hashlib
import inspect
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

from driftbase.local.local_store import _log_track_error, enqueue_run

logger = logging.getLogger(__name__)

# Decision outcome for semantic_cluster / reporting
OUTCOME_RESOLVED = "resolved"
OUTCOME_ESCALATED = "escalated"
OUTCOME_FALLBACK = "fallback"
OUTCOME_ERROR = "error"


@dataclass
class RunContext:
    """Mutable context for a single tracked run."""

    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)  # name, order, input_hash, output_hash, latency_ms
    decision_outcome: str = OUTCOME_RESOLVED
    latency_ms: int = 0
    token_usage: Optional[dict[str, int]] = None
    error_type: Optional[str] = None
    retry_count: int = 0
    framework: str = "generic"
    task_input_hash: str = ""
    output_length: int = 0
    output_structure_hash: str = ""
    error_count: int = 0


def _hash_content(content: Any) -> str:
    try:
        serialized = json.dumps(content, sort_keys=True, default=str)
    except Exception:
        serialized = repr(content)
    return hashlib.sha256(serialized.encode()).hexdigest()


def _classify_decision_outcome(result: Any, exception: Optional[BaseException]) -> str:
    """Classify run as resolved, escalated, fallback, or error from return value or exception."""
    if exception is not None:
        return OUTCOME_ERROR
    if result is None:
        return OUTCOME_RESOLVED
    try:
        if isinstance(result, dict):
            out = (result.get("outcome") or result.get("decision_outcome") or result.get("status") or "").lower()
            if out in (OUTCOME_ESCALATED, OUTCOME_FALLBACK, OUTCOME_ERROR, OUTCOME_RESOLVED):
                return out
            if result.get("escalated") is True:
                return OUTCOME_ESCALATED
            if result.get("fallback") is True:
                return OUTCOME_FALLBACK
            if result.get("error") is True:
                return OUTCOME_ERROR
        if hasattr(result, "outcome"):
            v = getattr(result, "outcome", None)
            if isinstance(v, str) and v.lower() in (OUTCOME_ESCALATED, OUTCOME_FALLBACK, OUTCOME_ERROR, OUTCOME_RESOLVED):
                return v.lower()
        if hasattr(result, "escalated") and getattr(result, "escalated") is True:
            return OUTCOME_ESCALATED
        if hasattr(result, "fallback") and getattr(result, "fallback") is True:
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
    """Detect framework by inspecting function module and signature. Priority: LangGraph → LangChain → LlamaIndex → OpenAI → generic."""
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
        hint = sig.return_annotation
        if hint != inspect.Parameter.empty and hint is not None:
            hint_str = getattr(hint, "__name__", str(hint))
            if "StateGraph" in hint_str or "CompiledStateGraph" in hint_str or "langgraph" in str(hint).lower():
                return "langgraph"
            if "Runnable" in hint_str or "BaseMessage" in hint_str or "langchain" in str(hint):
                return "langchain"
            if "openai" in str(hint).lower() or "ChatCompletion" in hint_str:
                return "openai"
        # Check sys.modules so already-imported frameworks are detected
        if "langgraph" in sys.modules:
            return "langgraph"
        if "langchain" in sys.modules or "langchain_core" in sys.modules:
            return "langchain"
        if "llama_index" in sys.modules or "llamaindex" in sys.modules:
            return "llamaindex"
        if "openai" in sys.modules:
            return "openai"
    except Exception:
        pass
    return "generic"


def _build_payload(
    ctx: RunContext,
    session_id: str,
    deployment_version: str,
    environment: str,
) -> dict[str, Any]:
    """Build AgentRunLocal-compatible payload for local_store.enqueue_run."""
    completed = ctx.completed_at or datetime.utcnow()
    tool_sequence_json = json.dumps([t.get("name", "") for t in ctx.tool_calls])
    return {
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
        "prompt_tokens": (ctx.token_usage or {}).get("prompt"),
        "completion_tokens": (ctx.token_usage or {}).get("completion"),
    }


def _capture_generic(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    ctx: RunContext,
) -> Any:
    """Generic path: time the call and optionally parse tool_sequence from return value."""
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
                        name = getattr(tc, "function", tc) if hasattr(tc, "function") else tc
                        if isinstance(name, dict):
                            ctx.tool_calls.append({"name": name.get("name", "unknown")})
                        else:
                            ctx.tool_calls.append({"name": getattr(name, "name", str(name))})
                elif isinstance(result, dict) and "tool_calls" in result:
                    for tc in result["tool_calls"] or []:
                        ctx.tool_calls.append({"name": tc.get("function", {}).get("name", "unknown")})
            except Exception:
                pass


def _capture_openai(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    ctx: RunContext,
) -> Any:
    """Wrap OpenAI chat.completions.create to capture tool_calls, finish_reason, usage, latency from raw response."""
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
        ctx.latency_ms += int((time.perf_counter() - t0) * 1000)
        try:
            if getattr(resp, "choices", None):
                c = resp.choices[0]
                msg = getattr(c, "message", None)
                if msg and getattr(msg, "tool_calls", None):
                    for tc in msg.tool_calls or []:
                        name = "unknown"
                        if hasattr(tc, "function") and tc.function:
                            name = getattr(tc.function, "name", name)
                        ctx.tool_calls.append({"name": name})
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
    """Run with LangChain callback handler to capture tool/agent/llm events."""
    try:
        from langchain_core.callbacks import BaseCallbackHandler
        from langchain_core.runnables import Runnable
    except ImportError:
        return _capture_generic(func, args, kwargs, ctx)

    class TrackHandler(BaseCallbackHandler):
        def __init__(self, run_ctx: RunContext):
            self.ctx = run_ctx
            self._tool_start: dict[str, float] = {}

        def on_tool_start(self, serialized: dict, input_str: str, **kwargs: Any) -> None:
            name = serialized.get("name", "unknown")
            self._tool_start[id(serialized)] = time.perf_counter()
            self.ctx.tool_calls.append({"name": name, "input_hash": _hash_content(input_str)[:16]})

        def on_tool_end(self, output: str, **kwargs: Any) -> None:
            pass  # we already have order; could add output_hash per tool here

        def on_agent_action(self, action: Any, **kwargs: Any) -> None:
            pass

        def on_agent_finish(self, finish: Any, **kwargs: Any) -> None:
            pass

        def on_llm_start(self, serialized: dict, prompts: list[str], **kwargs: Any) -> None:
            pass

        def on_llm_end(self, response: Any, **kwargs: Any) -> None:
            pass

    handler = TrackHandler(ctx)
    ctx.framework = "langchain"

    # Only inject callbacks if the function accepts config (e.g. LangChain invoke)
    sig = inspect.signature(func)
    params = sig.parameters
    accepts_config = "config" in params or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    if accepts_config:
        config = kwargs.get("config") or {}
        if not isinstance(config, dict):
            config = {}
        callbacks = list(config.get("callbacks", []))
        callbacks.append(handler)
        kwargs = {**kwargs, "config": {**config, "callbacks": callbacks}}

    return _capture_generic(func, args, kwargs, ctx)


def _capture_llamaindex(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    ctx: RunContext,
) -> Any:
    """Run with LlamaIndex BaseCallbackHandler to capture query, retrieval, and tool-call events."""
    try:
        from llama_index.core.callbacks import BaseCallbackHandler, CBEventType
        from llama_index.core.settings import Settings
    except ImportError:
        ctx.framework = "llamaindex"
        return _capture_generic(func, args, kwargs, ctx)

    class TrackHandler(BaseCallbackHandler):
        def __init__(self, run_ctx: RunContext) -> None:
            super().__init__(event_starts_to_ignore=[], event_ends_to_ignore=[])
            self.ctx = run_ctx

        def on_event_start(
            self,
            event_type: Any,
            payload: Optional[dict] = None,
            event_id: str = "",
            parent_id: str = "",
            **kwargs: Any,
        ) -> str:
            payload = payload or {}
            try:
                if event_type == CBEventType.FUNCTION_CALL:
                    name = (payload.get("function_call") or payload.get("name") or "unknown")
                    if isinstance(name, dict):
                        name = name.get("name", "unknown")
                    self.ctx.tool_calls.append({"name": str(name)})
            except Exception:
                pass
            return event_id or ""

        def on_event_end(
            self,
            event_type: Any,
            payload: Optional[dict] = None,
            event_id: str = "",
            **kwargs: Any,
        ) -> None:
            pass

        def start_trace(self, trace_id: Optional[str] = None) -> None:
            pass

        def end_trace(
            self,
            trace_id: Optional[str] = None,
            trace_map: Optional[dict] = None,
        ) -> None:
            pass

    handler = TrackHandler(ctx)
    ctx.framework = "llamaindex"
    try:
        cm = getattr(Settings, "callback_manager", None) or getattr(Settings, "_callback_manager", None)
        if cm is not None and hasattr(cm, "add_handler"):
            cm.add_handler(handler)
            try:
                return _capture_generic(func, args, kwargs, ctx)
            finally:
                if hasattr(cm, "remove_handler"):
                    cm.remove_handler(handler)
        return _capture_generic(func, args, kwargs, ctx)
    except Exception:
        return _capture_generic(func, args, kwargs, ctx)


def track(
    version: str = "unknown",
    environment: Optional[str] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that records agent runs to local SQLite with zero friction.

    Use as:
        @track(version="v1.0")
        def my_agent(user_input: str) -> str:
            ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        framework = _detect_framework(func)
        session_id = os.getenv("DRIFTBASE_SESSION_ID", "")

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            run_id = _hash_content(str(time.time()) + str(id(func)))[:12]
            ctx = RunContext()
            ctx.task_input_hash = _hash_content((args, kwargs))[:32]
            ctx.framework = framework
            try:
                if framework == "langgraph":
                    result = _capture_langchain(func, args, kwargs, ctx)
                    ctx.framework = "langgraph"
                elif framework == "langchain":
                    result = _capture_langchain(func, args, kwargs, ctx)
                elif framework == "llamaindex":
                    result = _capture_llamaindex(func, args, kwargs, ctx)
                elif framework == "openai":
                    result = _capture_openai(func, args, kwargs, ctx)
                else:
                    result = _capture_generic(func, args, kwargs, ctx)
                ctx.decision_outcome = _classify_decision_outcome(result, None)
            except Exception as e:
                ctx.decision_outcome = OUTCOME_ERROR
                ctx.error_count = 1
                ctx.error_type = type(e).__name__
                ctx.completed_at = datetime.utcnow()
                if ctx.latency_ms == 0:
                    ctx.latency_ms = 1
                try:
                    env = environment or os.getenv("DRIFTBASE_ENVIRONMENT", "production")
                    payload = _build_payload(ctx, session_id or run_id, version, env)
                    enqueue_run(payload)
                except Exception as enq_err:
                    _log_track_error("track_decorator", f"run_id={run_id} enqueue error={enq_err!r}")
                raise

            try:
                if result is not None:
                    if isinstance(result, str):
                        ctx.output_length = len(result)
                    elif hasattr(result, "content"):
                        ctx.output_length = len(getattr(result, "content", "") or "")
                    elif isinstance(result, (dict, list)):
                        ctx.output_length = len(json.dumps(result, default=str))
                    ctx.output_structure_hash = _compute_structure_hash(result)
                env = environment or os.getenv("DRIFTBASE_ENVIRONMENT", "production")
                payload = _build_payload(ctx, session_id or run_id, version, env)
                enqueue_run(payload)
            except Exception as e:
                _log_track_error("track_decorator", f"run_id={run_id} error={e!r}")
            return result

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            run_id = _hash_content(str(time.time()) + str(id(func)))[:12]
            ctx = RunContext()
            ctx.task_input_hash = _hash_content((args, kwargs))[:32]
            ctx.framework = framework
            start = time.perf_counter()
            try:
                if framework == "langgraph":
                    result = await _capture_langchain_async(func, args, kwargs, ctx)
                    ctx.framework = "langgraph"
                elif framework == "langchain":
                    result = await _capture_langchain_async(func, args, kwargs, ctx)
                elif framework == "llamaindex":
                    result = await _capture_llamaindex_async(func, args, kwargs, ctx)
                elif framework == "openai":
                    result = await _capture_openai_async(func, args, kwargs, ctx)
                else:
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
                try:
                    env = environment or os.getenv("DRIFTBASE_ENVIRONMENT", "production")
                    payload = _build_payload(ctx, session_id or run_id, version, env)
                    enqueue_run(payload)
                except Exception as enq_err:
                    _log_track_error("track_decorator_async", f"run_id={run_id} enqueue error={enq_err!r}")
                raise

            try:
                if result is not None:
                    if isinstance(result, str):
                        ctx.output_length = len(result)
                    elif hasattr(result, "content"):
                        ctx.output_length = len(getattr(result, "content", "") or "")
                    elif isinstance(result, (dict, list)):
                        ctx.output_length = len(json.dumps(result, default=str))
                    ctx.output_structure_hash = _compute_structure_hash(result)
                env = environment or os.getenv("DRIFTBASE_ENVIRONMENT", "production")
                payload = _build_payload(ctx, session_id or run_id, version, env)
                enqueue_run(payload)
            except Exception as e:
                _log_track_error("track_decorator_async", f"run_id={run_id} error={e!r}")
            return result

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
        from langchain_core.callbacks import BaseCallbackHandler
    except ImportError:
        return await _capture_generic_async(func, args, kwargs, ctx)

    class TrackHandler(BaseCallbackHandler):
        def __init__(self, run_ctx: RunContext):
            self.ctx = run_ctx

        def on_tool_start(self, serialized: dict, input_str: str, **kwargs: Any) -> None:
            self.ctx.tool_calls.append({"name": serialized.get("name", "unknown")})

    handler = TrackHandler(ctx)
    config = kwargs.get("config") or {}
    if not isinstance(config, dict):
        config = {}
    kwargs = {**kwargs, "config": {**config, "callbacks": list(config.get("callbacks", [])) + [handler]}}
    return await func(*args, **kwargs)


async def _capture_llamaindex_async(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    ctx: RunContext,
) -> Any:
    """LlamaIndex async: inject callback handler then run generic async capture."""
    try:
        from llama_index.core.callbacks import BaseCallbackHandler, CBEventType
        from llama_index.core.settings import Settings
    except ImportError:
        ctx.framework = "llamaindex"
        return await _capture_generic_async(func, args, kwargs, ctx)

    class TrackHandlerAsync(BaseCallbackHandler):
        def __init__(self, run_ctx: RunContext) -> None:
            super().__init__(event_starts_to_ignore=[], event_ends_to_ignore=[])
            self.ctx = run_ctx

        def on_event_start(
            self,
            event_type: Any,
            payload: Optional[dict] = None,
            event_id: str = "",
            parent_id: str = "",
            **kwargs: Any,
        ) -> str:
            payload = payload or {}
            try:
                if event_type == CBEventType.FUNCTION_CALL:
                    name = (payload.get("function_call") or payload.get("name") or "unknown")
                    if isinstance(name, dict):
                        name = name.get("name", "unknown")
                    self.ctx.tool_calls.append({"name": str(name)})
            except Exception:
                pass
            return event_id or ""

        def on_event_end(
            self,
            event_type: Any,
            payload: Optional[dict] = None,
            event_id: str = "",
            **kwargs: Any,
        ) -> None:
            pass

        def start_trace(self, trace_id: Optional[str] = None) -> None:
            pass

        def end_trace(
            self,
            trace_id: Optional[str] = None,
            trace_map: Optional[dict] = None,
        ) -> None:
            pass

    handler = TrackHandlerAsync(ctx)
    ctx.framework = "llamaindex"
    try:
        cm = getattr(Settings, "callback_manager", None) or getattr(Settings, "_callback_manager", None)
        if cm is not None and hasattr(cm, "add_handler"):
            cm.add_handler(handler)
            try:
                return await _capture_generic_async(func, args, kwargs, ctx)
            finally:
                if hasattr(cm, "remove_handler"):
                    cm.remove_handler(handler)
        return await _capture_generic_async(func, args, kwargs, ctx)
    except Exception:
        return await _capture_generic_async(func, args, kwargs, ctx)


async def _capture_openai_async(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    ctx: RunContext,
) -> Any:
    """Wrap OpenAI chat.completions.create (async) to capture from raw response."""
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
        ctx.latency_ms += int((time.perf_counter() - t0) * 1000)
        try:
            if getattr(resp, "choices", None):
                c = resp.choices[0]
                msg = getattr(c, "message", None)
                if msg and getattr(msg, "tool_calls", None):
                    for tc in msg.tool_calls or []:
                        name = "unknown"
                        if hasattr(tc, "function") and tc.function:
                            name = getattr(tc.function, "name", name)
                        ctx.tool_calls.append({"name": name})
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
