"""
Framework auto-detection and patching for @track decorator.

This module provides automatic instrumentation of agent frameworks, allowing
@track to capture full tool visibility without manual tracer setup.
"""

from __future__ import annotations

import functools
import logging
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from driftbase.sdk.track import RunContext

logger = logging.getLogger(__name__)

# Track which frameworks have been patched to avoid double-patching
_patches_applied: set[str] = set()

# Thread-local storage for current context and version
_thread_local = threading.local()

# Registry of all supported frameworks
FRAMEWORK_PATCHES = [
    {
        "name": "langgraph",
        "detect": "langgraph.pregel",
        "patcher": "_patch_langgraph",
    },
    {
        "name": "langchain",
        "detect": "langchain_core.runnables",
        "patcher": "_patch_langchain",
    },
    {
        "name": "llamaindex",
        "detect": "llama_index.core",
        "patcher": "_patch_llamaindex",
    },
    {
        "name": "haystack",
        "detect": "haystack",
        "patcher": "_patch_haystack",
    },
    {
        "name": "dspy",
        "detect": "dspy",
        "patcher": "_patch_dspy",
    },
    {
        "name": "smolagents",
        "detect": "smolagents",
        "patcher": "_patch_smolagents",
    },
]


def apply_framework_patches(ctx: RunContext, version: str) -> None:
    """
    Detect installed frameworks and apply patches to inject Driftbase tracers.

    Stores ctx and version in thread-local storage, then patches are applied
    once per framework (idempotent). Patched methods retrieve ctx/version from
    thread-local at runtime.

    Args:
        ctx: RunContext to share with injected tracers (prevents double-saving)
        version: Deployment version to pass to tracers
    """
    # Store ctx and version in thread-local storage for this call
    _thread_local.ctx = ctx
    _thread_local.version = version

    for fw in FRAMEWORK_PATCHES:
        if fw["name"] in _patches_applied:
            continue  # Already patched

        try:
            # Try to import the framework's detection module
            __import__(fw["detect"])

            # Framework is installed - apply patch
            patcher_func = globals().get(fw["patcher"])
            if patcher_func is not None:
                patcher_func()
                _patches_applied.add(fw["name"])
                logger.debug(f"Applied auto-detection patch for {fw['name']}")
        except ImportError:
            # Framework not installed - skip silently
            pass
        except Exception as e:
            # Patch failed - log but don't crash
            logger.debug(f"Failed to patch {fw['name']}: {e}")


def clear_framework_context() -> None:
    """
    Clear thread-local storage after @track call completes.

    This prevents stale context from leaking into subsequent calls.
    """
    _thread_local.ctx = None
    _thread_local.version = None


def _patch_async(
    cls: type, method_name: str, tracer_cls: type, ctx: RunContext, version: str
) -> None:
    """
    Helper to patch async methods with tracer injection.

    Args:
        cls: Class to patch (e.g., Pregel, Runnable)
        method_name: Method name to patch (e.g., "ainvoke")
        tracer_cls: Tracer class to instantiate (e.g., LangGraphTracer)
        ctx: RunContext to pass to tracer
        version: Version string for tracer
    """
    original_method = getattr(cls, method_name, None)
    if original_method is None:
        return

    @functools.wraps(original_method)
    async def patched_async(self, input, config=None, **kwargs):
        tracer = tracer_cls(version=version, _external_ctx=ctx)
        config = config or {}
        callbacks = config.get("callbacks", [])

        # Don't duplicate if user already added a Driftbase tracer
        if not any(isinstance(cb, tracer_cls) for cb in callbacks):
            callbacks.append(tracer)
            config["callbacks"] = callbacks

        return await original_method(self, input, config=config, **kwargs)

    setattr(cls, method_name, patched_async)


# ============================================================================
# LangGraph Patching (Priority 1 - Full Implementation)
# ============================================================================


def _patch_langgraph() -> None:
    """
    Patch LangGraph's Pregel.invoke() to auto-inject LangGraphTracer.

    This enables @track to capture full tool call visibility from LangGraph
    agents without requiring manual tracer setup.

    Retrieves ctx and version from thread-local storage at runtime.
    """
    try:
        from langgraph.pregel import Pregel

        from driftbase.integrations.langgraph import LangGraphTracer
    except ImportError:
        logger.debug("LangGraph or LangGraphTracer not available for patching")
        return

    # Patch synchronous invoke
    original_invoke = Pregel.invoke

    @functools.wraps(original_invoke)
    def patched_invoke(self, input, config=None, **kwargs):
        # Retrieve ctx and version from thread-local storage
        ctx = getattr(_thread_local, "ctx", None)
        version = getattr(_thread_local, "version", "unknown")

        # Only modify callbacks if @track is active (ctx is not None)
        if ctx is None:
            # No active @track context - call original without modification
            return original_invoke(self, input, config=config, **kwargs)

        config = config or {}
        callbacks = config.get("callbacks", [])

        # Check if user already added a LangGraphTracer
        existing_tracer_idx = None
        for i, cb in enumerate(callbacks):
            if isinstance(cb, LangGraphTracer):
                existing_tracer_idx = i
                break

        if existing_tracer_idx is not None:
            # User provided a manual tracer - replace it with context-aware version
            # to prevent double-saving (manual tracer + @track)
            manual_tracer = callbacks[existing_tracer_idx]
            # Create new tracer with _external_ctx, preserving user's version if set
            tracer_version = getattr(manual_tracer, "deployment_version", version)
            tracer = LangGraphTracer(version=tracer_version, _external_ctx=ctx)
            callbacks[existing_tracer_idx] = tracer
            config["callbacks"] = callbacks
        else:
            # No manual tracer - inject ours
            tracer = LangGraphTracer(version=version, _external_ctx=ctx)
            callbacks.append(tracer)
            config["callbacks"] = callbacks

        return original_invoke(self, input, config=config, **kwargs)

    Pregel.invoke = patched_invoke

    # Patch asynchronous ainvoke
    original_ainvoke = getattr(Pregel, "ainvoke", None)
    if original_ainvoke is not None:

        @functools.wraps(original_ainvoke)
        async def patched_ainvoke(self, input, config=None, **kwargs):
            ctx = getattr(_thread_local, "ctx", None)
            version = getattr(_thread_local, "version", "unknown")

            if ctx is None:
                return await original_ainvoke(self, input, config=config, **kwargs)

            config = config or {}
            callbacks = config.get("callbacks", [])

            # Check if user already added a LangGraphTracer
            existing_tracer_idx = None
            for i, cb in enumerate(callbacks):
                if isinstance(cb, LangGraphTracer):
                    existing_tracer_idx = i
                    break

            if existing_tracer_idx is not None:
                # User provided a manual tracer - replace it with context-aware version
                manual_tracer = callbacks[existing_tracer_idx]
                tracer_version = getattr(manual_tracer, "deployment_version", version)
                tracer = LangGraphTracer(version=tracer_version, _external_ctx=ctx)
                callbacks[existing_tracer_idx] = tracer
                config["callbacks"] = callbacks
            else:
                # No manual tracer - inject ours
                tracer = LangGraphTracer(version=version, _external_ctx=ctx)
                callbacks.append(tracer)
                config["callbacks"] = callbacks

            return await original_ainvoke(self, input, config=config, **kwargs)

        Pregel.ainvoke = patched_ainvoke


# ============================================================================
# LangChain Patching (Priority 2 - Full Implementation)
# ============================================================================


def _patch_langchain() -> None:
    """
    Patch LangChain's Runnable.invoke() to auto-inject DriftbaseCallbackHandler.

    This enables @track to capture full tool call visibility from LangChain
    chains and agents without requiring manual handler setup.

    Retrieves ctx and version from thread-local storage at runtime.
    """
    try:
        from langchain_core.runnables import Runnable

        from driftbase.sdk.watcher import DriftbaseCallbackHandler
    except ImportError:
        logger.debug("LangChain or DriftbaseCallbackHandler not available for patching")
        return

    # Patch synchronous invoke
    original_invoke = Runnable.invoke

    @functools.wraps(original_invoke)
    def patched_invoke(self, input, config=None, **kwargs):
        ctx = getattr(_thread_local, "ctx", None)
        version = getattr(_thread_local, "version", "unknown")

        if ctx is None:
            return original_invoke(self, input, config=config, **kwargs)

        # DriftbaseCallbackHandler uses run_ctx parameter (not _external_ctx)
        handler = DriftbaseCallbackHandler(version=version, agent_id=None, run_ctx=ctx)
        config = config or {}
        callbacks = config.get("callbacks", [])

        # Don't duplicate if user already added a Driftbase handler
        if not any(isinstance(cb, DriftbaseCallbackHandler) for cb in callbacks):
            callbacks.append(handler)
            config["callbacks"] = callbacks

        return original_invoke(self, input, config=config, **kwargs)

    Runnable.invoke = patched_invoke

    # Patch asynchronous ainvoke
    original_ainvoke = getattr(Runnable, "ainvoke", None)
    if original_ainvoke is not None:

        @functools.wraps(original_ainvoke)
        async def patched_ainvoke(self, input, config=None, **kwargs):
            ctx = getattr(_thread_local, "ctx", None)
            version = getattr(_thread_local, "version", "unknown")

            if ctx is None:
                return await original_ainvoke(self, input, config=config, **kwargs)

            handler = DriftbaseCallbackHandler(
                version=version, agent_id=None, run_ctx=ctx
            )
            config = config or {}
            callbacks = config.get("callbacks", [])

            if not any(isinstance(cb, DriftbaseCallbackHandler) for cb in callbacks):
                callbacks.append(handler)
                config["callbacks"] = callbacks

            return await original_ainvoke(self, input, config=config, **kwargs)

        Runnable.ainvoke = patched_ainvoke


# ============================================================================
# Other Frameworks (Stub Implementations)
# ============================================================================


def _patch_llamaindex() -> None:
    """
    Stub: LlamaIndex auto-detection not yet implemented.

    Users should continue using LlamaIndexTracer directly until this is implemented.
    """
    logger.debug(
        "LlamaIndex auto-detection not yet supported - use LlamaIndexTracer directly"
    )


def _patch_haystack() -> None:
    """
    Stub: Haystack auto-detection not yet implemented.

    Users should continue using HaystackTracer directly until this is implemented.
    """
    logger.debug(
        "Haystack auto-detection not yet supported - use HaystackTracer directly"
    )


def _patch_dspy() -> None:
    """
    Stub: DSPy auto-detection not yet implemented.

    Users should continue using DSPyTracer directly until this is implemented.
    """
    logger.debug("DSPy auto-detection not yet supported - use DSPyTracer directly")


def _patch_smolagents() -> None:
    """
    Stub: smolagents auto-detection not yet implemented.

    Users should continue using SmolagentsTracer directly until this is implemented.
    """
    logger.debug(
        "smolagents auto-detection not yet supported - use SmolagentsTracer directly"
    )
