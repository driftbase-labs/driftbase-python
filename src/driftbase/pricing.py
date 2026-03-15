"""Cost estimation engine for AI token usage."""
import os

def _get_rate(env_var: str, default: float) -> float:
    """Safely fetch numeric pricing rates from environment or config."""
    try:
        from driftbase.config import get_settings
        settings = get_settings()
        if hasattr(settings, env_var):
            return float(getattr(settings, env_var))
    except Exception:
        pass
    
    val = os.getenv(env_var)
    if val is not None:
        try:
            return float(val)
        except ValueError:
            pass
            
    return default


def get_rates_for_display() -> tuple[float, float]:
    """Return (rate_prompt_per_1m, rate_completion_per_1m) in EUR for display in CLI."""
    return (
        _get_rate("DRIFTBASE_RATE_PROMPT_1M", 2.50),
        _get_rate("DRIFTBASE_RATE_COMPLETION_1M", 10.00),
    )


def estimate_run_cost(prompt_tokens: float, completion_tokens: float) -> float:
    """Calculates cost based on configurable rates (EUR per 1M tokens)."""
    rate_prompt = _get_rate("DRIFTBASE_RATE_PROMPT_1M", 2.50)
    rate_completion = _get_rate("DRIFTBASE_RATE_COMPLETION_1M", 10.00)
    
    return (prompt_tokens / 1_000_000 * rate_prompt) + (completion_tokens / 1_000_000 * rate_completion)

def calculate_cost_per_10k(run_dicts: list[dict]) -> float:
    """Calculates the aggregate cost for 10,000 runs based on average window usage."""
    if not run_dicts:
        return 0.0
    
    total_prompt = sum(r.get("prompt_tokens") or 0 for r in run_dicts)
    total_comp = sum(r.get("completion_tokens") or 0 for r in run_dicts)
    
    avg_prompt = total_prompt / len(run_dicts)
    avg_comp = total_comp / len(run_dicts)
    
    return estimate_run_cost(avg_prompt, avg_comp) * 10000