"""
Explicit framework adapters for driftbase-python.

Each adapter provides a framework-specific way to track agent runs with no magic detection.
Developers import the adapter directly and use it with their framework.

All adapters call enqueue_run() from driftbase.local.local_store so data goes to the same
SQLite database and works with the same CLI commands.

Usage:
    from driftbase.integrations import LangChainTracer
    tracer = LangChainTracer(version='v1.0')
    chain.invoke(input, config={'callbacks': [tracer]})

Note: Imports are lazy - you can import any tracer without having the framework installed.
      The error only appears when you instantiate the tracer.
"""

__all__ = [
    "LangChainTracer",
    "LangGraphTracer",
    "OpenAITracer",
    "AutoGenTracer",
    "CrewAITracer",
]


def __getattr__(name: str):
    """Lazy import mechanism - only load modules when accessed."""
    if name == "LangChainTracer":
        from driftbase.integrations.langchain import LangChainTracer
        return LangChainTracer
    elif name == "LangGraphTracer":
        from driftbase.integrations.langgraph import LangGraphTracer
        return LangGraphTracer
    elif name == "OpenAITracer":
        from driftbase.integrations.openai import OpenAITracer
        return OpenAITracer
    elif name == "AutoGenTracer":
        from driftbase.integrations.autogen import AutoGenTracer
        return AutoGenTracer
    elif name == "CrewAITracer":
        from driftbase.integrations.crewai import CrewAITracer
        return CrewAITracer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
