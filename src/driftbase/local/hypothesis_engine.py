"""
Rule-based root cause hypothesis engine for drift reports.
Uses YAML rules; no LLM. Fast, offline, extensible.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

# Type alias for drift report attributes we need
DriftReportLike = Any


def _bundled_rules_path() -> Optional[Path]:
    """Return path to bundled hypothesis_rules.yaml (for _rules_path fallback)."""
    try:
        from importlib.resources import files

        ref = files("driftbase") / "hypothesis_rules.yaml"
        try:
            if ref.is_file():
                return Path(str(ref))
        except AttributeError:
            pass
        try:
            ref.read_bytes()
            return Path(str(ref))
        except Exception:
            return None
    except Exception:
        return None


def _rules_path() -> Path:
    """Path to hypothesis_rules.yaml (env DRIFTBASE_HYPOTHESIS_RULES or bundled default)."""
    env_path = os.getenv("DRIFTBASE_HYPOTHESIS_RULES")
    if env_path:
        return Path(env_path).resolve()
    bundled = _bundled_rules_path()
    if bundled is not None:
        return bundled
    return Path(__file__).resolve().parent / "hypothesis_rules.yaml"


def _load_rules() -> list[dict[str, Any]]:
    import yaml

    env_path = os.getenv("DRIFTBASE_HYPOTHESIS_RULES")
    if env_path:
        path = Path(env_path).resolve()
        if path.is_file():
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return (data or {}).get("rules") or []
        return []
    try:
        from importlib.resources import files

        ref = files("driftbase") / "hypothesis_rules.yaml"
        content = ref.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        return (data or {}).get("rules") or []
    except Exception:
        pass
    path = Path(__file__).resolve().parent / "hypothesis_rules.yaml"
    if path.is_file():
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return (data or {}).get("rules") or []
    return []


def _compute_tool_deltas(
    baseline_tools: dict[str, float],
    current_tools: dict[str, float],
) -> tuple[Optional[tuple[str, float]], Optional[tuple[str, float]]]:
    """Return (biggest_drop, biggest_rise) as (tool_name, delta_pct)."""
    biggest_drop: Optional[tuple[str, float]] = None
    biggest_rise: Optional[tuple[str, float]] = None
    all_tools = sorted(set(baseline_tools.keys()) | set(current_tools.keys()))
    for tool in all_tools:
        b = baseline_tools.get(tool, 0.0) * 100
        c = current_tools.get(tool, 0.0) * 100
        if b == 0:
            if c > 0:
                pct = 100.0
                if biggest_rise is None or pct > biggest_rise[1]:
                    biggest_rise = (tool, pct)
            continue
        delta_pct = ((c - b) / b) * 100
        if delta_pct < -20 and (biggest_drop is None or delta_pct < biggest_drop[1]):
            biggest_drop = (tool, delta_pct)
        if delta_pct > 50 and (biggest_rise is None or delta_pct > biggest_rise[1]):
            biggest_rise = (tool, delta_pct)
    return biggest_drop, biggest_rise


def _evaluate_condition(
    cond: dict[str, Any],
    ctx: dict[str, Any],
) -> bool:
    """Return True if all condition keys in cond are satisfied by ctx."""
    for key, val in cond.items():
        if key in (
            "observation",
            "likely_cause",
            "recommended_action",
            "confidence",
            "id",
        ):
            continue
        if key == "overall_drift_max":
            if ctx.get("overall_drift", 1.0) > val:
                return False
            continue
        if key == "overall_drift_min":
            if ctx.get("overall_drift", 0.0) < val:
                return False
            continue
        if key == "decision_drift_min":
            if ctx.get("decision_drift", 0.0) < val:
                return False
            continue
        if key == "decision_drift_max":
            if ctx.get("decision_drift", 1.0) > val:
                return False
            continue
        if key == "latency_drift_min":
            if ctx.get("latency_drift", 0.0) < val:
                return False
            continue
        if key == "error_drift_min":
            if ctx.get("error_drift", 0.0) < val:
                return False
            continue
        if key == "tool_decrease_min_pct":
            drop = ctx.get("tool_decrease")
            if drop is None or abs(drop[1]) < val:
                return False
            continue
        if key == "tool_increase_min_pct":
            rise = ctx.get("tool_increase")
            if rise is None or rise[1] < val:
                return False
            continue
        if key == "tool_increase_name_contains":
            rise = ctx.get("tool_increase")
            if rise is None or val.lower() not in rise[0].lower():
                return False
            continue
        if key == "baseline_runs_min":
            if ctx.get("baseline_n", 0) < val:
                return False
            continue
        if key == "current_runs_min":
            if ctx.get("current_n", 0) < val:
                return False
            continue
        if key == "tool_drift_max":
            if ctx.get("tool_drift", 0.0) > val:
                return False
            continue
        if key == "escalation_rate_delta_min":
            if ctx.get("escalation_rate_delta", 0.0) < val:
                return False
            continue
        if key == "escalation_rate_delta_max":
            if ctx.get("escalation_rate_delta", 0.0) > val:
                return False
            continue
    return True


def generate_hypotheses(
    report: DriftReportLike,
    baseline_tools: dict[str, float],
    current_tools: dict[str, float],
    baseline_n: int,
    current_n: int,
) -> list[dict[str, str]]:
    """
    Evaluate YAML rules against the drift context. Returns a list of
    {observation, likely_cause, recommended_action, confidence}.
    """
    rules = _load_rules()
    if not rules:
        return []
    drop, rise = _compute_tool_deltas(baseline_tools, current_tools)
    from driftbase.local.diff import _jensen_shannon_divergence

    tool_drift = _jensen_shannon_divergence(baseline_tools, current_tools)
    ctx: dict[str, Any] = {
        "overall_drift": getattr(report, "drift_score", 0.0),
        "decision_drift": getattr(report, "decision_drift", 0.0),
        "latency_drift": getattr(report, "latency_drift", 0.0),
        "error_drift": getattr(report, "error_drift", 0.0),
        "tool_drift": tool_drift,
        "escalation_rate_delta": getattr(report, "escalation_rate_delta", 0.0),
        "tool_decrease": drop,
        "tool_increase": rise,
        "baseline_n": baseline_n,
        "current_n": current_n,
    }
    out: list[dict[str, str]] = []
    for rule in rules:
        cond = rule.get("condition") or rule
        if not _evaluate_condition(cond, ctx):
            continue
        obs = (rule.get("observation") or "").strip()
        cause = (rule.get("likely_cause") or "").strip()
        action = (rule.get("recommended_action") or "").strip()
        confidence = (rule.get("confidence") or "Investigate further").strip()
        rule_id = (rule.get("id") or "").lower()
        # Fill placeholders from the relevant source (drop vs rise)
        if "drop" in rule_id or "decrease" in rule_id or "specific_tool" in rule_id:
            if drop:
                tool_name, delta_pct = drop
                # Use concrete language for 100% drops
                if abs(delta_pct) >= 99:
                    obs = f"Tool '{tool_name}' dropped from baseline — no longer being called"
                else:
                    obs = obs.replace("{{tool_name}}", tool_name).replace(
                        "{{delta_pct}}", f"{abs(delta_pct):.0f}"
                    )
                action = action.replace("{{tool_name}}", tool_name)
        elif "rise" in rule_id or "increase" in rule_id or "escalation" in rule_id:
            if rise:
                tool_name, delta_pct = rise
                # Use concrete language for new tools
                if delta_pct >= 99 and "100" in obs:
                    obs = f"Tool '{tool_name}' is new in current version — not present in baseline"
                else:
                    obs = obs.replace("{{tool_name}}", tool_name).replace(
                        "{{delta_pct}}", f"{delta_pct:.0f}"
                    )
                action = action.replace("{{tool_name}}", tool_name)
        else:
            if drop:
                tool_name, delta_pct = drop
                if abs(delta_pct) >= 99:
                    obs = f"Tool '{tool_name}' dropped from baseline — no longer being called"
                else:
                    obs = obs.replace("{{tool_name}}", tool_name).replace(
                        "{{delta_pct}}", f"{abs(delta_pct):.0f}"
                    )
                action = action.replace("{{tool_name}}", tool_name)
            if rise:
                tool_name, delta_pct = rise
                if delta_pct >= 99:
                    obs = f"Tool '{tool_name}' is new in current version — not present in baseline"
                else:
                    obs = obs.replace("{{tool_name}}", tool_name).replace(
                        "{{delta_pct}}", f"{delta_pct:.0f}"
                    )
                action = action.replace("{{tool_name}}", tool_name)
        out.append(
            {
                "observation": obs,
                "likely_cause": cause,
                "recommended_action": action,
                "confidence": confidence,
            }
        )
    return out


def format_hypotheses(hypotheses: list[dict[str, str]]) -> str:
    """Format hypothesis list for terminal (plain English)."""
    if not hypotheses:
        return (
            "  → No specific hypothesis. Review dimension breakdown and tool changes."
        )
    lines = []
    for h in hypotheses:
        lines.append(f"  → {h['observation']}")
        lines.append(f"    Likely cause: {h['likely_cause']}")
        lines.append(f"    Recommended action: {h['recommended_action']}")
        lines.append(f"    [{h['confidence']}]")
        lines.append("")
    return "\n".join(lines).strip()
