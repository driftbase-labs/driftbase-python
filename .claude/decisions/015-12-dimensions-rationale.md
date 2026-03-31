# 015 — Why These 12 Dimensions

**Status:** Accepted
**Date:** 2026-03-30
**Files affected:** `local/fingerprinter.py`, `local/diff.py`

---

## Decision

The composite drift score uses exactly 12 behavioral dimensions. Adding more
dimensions beyond these 12 would increase noise without adding signal. Removing
any of these would create blind spots for real classes of behavioral drift.

The 12 dimensions:
1. decision_drift
2. tool_sequence
3. tool_distribution
4. latency (composite of p50/p95/p99)
5. error_rate
6. loop_depth
7. verbosity_ratio
8. retry_rate
9. output_length
10. time_to_first_tool
11. semantic_drift (conditional)
12. tool_sequence_transitions (conditional)

## Why these 12 specifically

**decision_drift** — The most direct signal. Outcome distribution (resolved /
escalated / fallback / error) is what the business actually cares about.
Any agent that starts making different decisions is exhibiting the most
important form of behavioral drift.

**tool_sequence** — Reasoning path changes. An agent that still calls the
same tools but in a different order has a different decision-making process.
JSD over Markov chains of tool calls.

**tool_distribution** — Tool selection changes. Independent from sequence —
an agent might maintain its sequence pattern while calling a completely
different mix of tools.

**latency** — Performance signal and behavioral signal. Latency changes
reveal added reasoning steps, model updates, or retrieval overhead changes.
Composite of p50/p95/p99 with tail-weighted combination (p99 matters most).

**error_rate** — Unambiguous regression signal. An agent that fails more
often is worse by definition. No weighting ambiguity.

**loop_depth** — Reasoning complexity. Agents that loop more are struggling.
Early warning for runaway behavior before it manifests as errors.

**verbosity_ratio** — Output behavior relative to input. Detects prompt
drift that makes agents over- or under-explain. Ratio (not absolute length)
normalizes for input size variation.

**retry_rate** — Tool/LLM reliability signal. High retry rate means the
agent is getting unreliable responses. Independent from error_rate (retries
may eventually succeed).

**output_length** — Absolute response size. Independent from verbosity_ratio
(input size may have changed). Catches schema changes in responses.

**time_to_first_tool** — Reasoning overhead before action. Isolates model
and prompt latency from tool execution latency. A spike here points to
the LLM or prompt; a spike in total latency could be either.

**semantic_drift** — Meaning shift in outputs. Catches behavioral drift
that produces structurally normal outputs with changed meaning. Requires
[semantic] extra. Conditional — redistributed when unavailable.

**tool_sequence_transitions** — Specific A→B Markov transitions. More
granular than tool_sequence — catches new paths through the tool graph
that didn't exist before. Particularly valuable for detecting decision
boundary shifts (e.g. suddenly going approve→escalate when that path
never existed before). Conditional — redistributed when unavailable.

## Why latency uses a single weight slot (not three)

p50, p95, p99 each tell a different story:
- p50: typical user experience
- p95: tail latency — slow path triggers
- p99: worst case — edge case behavior

They are correlated but not identical. However, using three separate weight
slots would require users to reason about the relationship between them,
and the calibration system would treat them as independent when they're not.

The composite latency score combines all three internally with tail-weighted
combination (p50×0.2, p95×0.5, p99×0.3), then the composite feeds into a
single `latency` weight slot. This preserves the information from all three
percentiles while keeping the weight table manageable.

## Why not more dimensions

Every additional dimension:
1. Adds weight to maintain (14 use cases × n dimensions = growing table)
2. Reduces the per-dimension weight, making individual signals weaker
3. Increases the risk of correlated dimensions double-counting

Dimensions considered and rejected:
- **Token count per run:** Captured by output_length + verbosity_ratio. Redundant.
- **Model version:** A metadata field, not a behavioral signal. Captured by change_events.
- **Tool call count:** Partially captured by loop_depth and tool_distribution. Marginal signal.
- **Cost per run:** Derived from token counts. Not a behavioral signal — a financial consequence.
- **Response schema:** Would require structural parsing of outputs. Too agent-specific.

## Why not fewer dimensions

The minimum viable set to detect the major classes of behavioral drift:

| Drift class | Primary detecting dimension |
|-------------|---------------------------|
| Decision behavior changes | decision_drift |
| Reasoning path changes | tool_sequence, tool_sequence_transitions |
| Tool selection changes | tool_distribution |
| Performance changes | latency, time_to_first_tool |
| Reliability changes | error_rate, retry_rate |
| Reasoning complexity changes | loop_depth |
| Output behavior changes | verbosity_ratio, output_length |
| Semantic meaning changes | semantic_drift |

Removing any dimension creates a blind spot for a real class of drift.
