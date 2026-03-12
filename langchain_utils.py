"""
Example agent invocation that merges platform callbacks with @track() callbacks.

_invoke_single(agent, task, handler, config=None) accepts an optional config from outside
(e.g. from a @track()-decorated caller). It merges the platform's handler into
config['callbacks'] so both the platform's DriftbaseCallbackHandler (Postgres) and
@track()'s injected handler (SQLite) run during the same agent.invoke().
"""

from __future__ import annotations

from typing import Any, Optional


def _invoke_single(
    agent: Any,
    task: Any,
    handler: Any,
    config: Optional[dict[str, Any]] = None,
) -> Any:
    """Invoke the agent with the given handler merged into config callbacks.

    Starts with config or {}, then merges handler into the callbacks list
    alongside any existing callbacks (e.g. from @track()). This way both the
    platform's DriftbaseCallbackHandler and @track()'s handler run simultaneously.
    """
    base = config if config is not None else {}
    if not isinstance(base, dict):
        base = {}
    callbacks = list(base.get("callbacks", []))
    callbacks.append(handler)
    final_config = {**base, "callbacks": callbacks}
    return agent.invoke(task, config=final_config)
