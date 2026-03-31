# Glossary

**Driftbase-specific terminology.**

## Core Concepts

**Behavioral Drift**
The degree to which an AI agent's behavior has changed between two versions. Measured as a composite score [0, 1] across 12 dimensions.

**Fingerprint**
An aggregate statistical summary of an agent's behavior across multiple runs. Contains distributions, percentiles, and counts. See `BehavioralFingerprint` in local_store.py.

**Run**
A single execution of an agent (from input to output). Captured by @track decorator. See `AgentRun` in local_store.py.

**Version**
A unique identifier for a deployment of an agent (e.g., "v1.0", "main", "pr-123"). Used to group runs for comparison.

---

## Scoring System

**Use Case**
A category of agent behavior (FINANCIAL, CUSTOMER_SUPPORT, etc.). Determines preset dimension weights. See USE_CASE_WEIGHTS in use_case_inference.py.

**Dimension**
A single behavioral metric (e.g., decision_drift, latency, error_rate). Agents are scored on 12 dimensions.

**Weight**
The importance of a dimension in the composite drift score. Weights sum to 1.0. Higher weight = more influence on verdict.

**Calibration**
The process of adjusting preset weights based on baseline variance and reliability. See calibrate() in baseline_calibrator.py.

**Reliability Multiplier**
A factor [0, 1] that reduces weight of noisy dimensions. Computed as 1/(1+cv) where cv = coefficient of variation.

**Correlation Adjustment**
Reduction of weights for correlated dimensions to avoid double-counting. Applied after reliability multipliers.

**Learned Weights**
Dimension weights trained on labeled deploy outcomes (good/bad). Blended with calibrated weights when n ≥ 10 labels.

---

## Statistical Concepts

**JSD (Jensen-Shannon Divergence)**
A metric [0, 1] for comparing two probability distributions. 0 = identical, 1 = completely different. Used for decision_drift and semantic_drift.

**Power Analysis**
Statistical computation of minimum sample size needed to detect a given effect size with specified confidence. See compute_min_runs_needed().

**Effect Size**
The minimum drift shift worth detecting (use case-specific). Financial agents use 0.05, content generation uses 0.15.

**t-distribution**
A probability distribution used for small sample statistics. Wider than normal distribution at n < 100, converges to normal as n → ∞.

**Bootstrap Confidence Interval**
A resampling method to estimate uncertainty in drift score. Runs 500 iterations of resampling with replacement.

**Coefficient of Variation (CV)**
Standard deviation divided by mean. Measures relative variability. High CV = unreliable dimension.

---

## Confidence Tiers

**TIER1**
Insufficient data (n < 15). Shows progress bars only, no drift scores or verdict.

**TIER2**
Indicative data (15 ≤ n < min_runs_needed). Shows directional signals (↑↓→) but no numeric scores or verdict.

**TIER3**
Reliable data (n ≥ min_runs_needed). Shows full drift scores, verdict, and confidence intervals.

**Partial TIER3**
Special case: 8+ dimensions reliable and n ≥ 80% of min_runs_needed. Promoted to TIER3 despite overall n below threshold.

**Reliable Dimension**
A dimension where n ≥ min_runs_per_dimension[dim]. Indicates sufficient data for statistical significance.

**Indicative Dimension**
A dimension where 15 ≤ n < min_runs_per_dimension[dim]. Can detect large shifts but not small ones.

---

## Verdicts

**SHIP (exit code 0)**
No significant drift detected. Safe to deploy.

**MONITOR (exit code 10)**
Minor drift detected. Deploy but watch closely.

**REVIEW (exit code 20)**
Moderate drift detected. Manual review recommended before deploy.

**BLOCK (exit code 30)**
Critical drift detected. Do not deploy without investigation.

---

## Budgets

**Budget**
A hard limit on a performance metric (e.g., latency_p95_ms ≤ 5000). Enforced at runtime by @track decorator.

**Budget Breach**
Event where a rolling average exceeds a budget limit. Recorded in budget_breaches table.

**Budget Config**
Persisted budget definition. Stored in budget_configs table at decorator call time.

**Rolling Average**
Mean of last N runs (default N=10). Used to smooth noisy metrics before breach detection.

---

## Inference System

**Keyword Classifier**
Tool name → use case inference via keyword matching. Returns use case + confidence.

**Behavioral Classifier**
Run patterns → use case inference via behavioral signals (escalation_rate, latency, etc.). Returns use case + confidence.

**Blending**
Combining keyword and behavioral classifiers proportionally by confidence. Resolves conflicts (incompatible use cases).

**Preset Weights**
Default dimension weights for each use case. Derived from production data across 14 use cases.

---

## Dimensions (12)

**decision_drift**
JSD of tool sequence distribution. Measures what the agent does.

**tool_sequence**
JSD of tool call order. Detects reordering even when same tools used.

**latency**
P95 latency drift, sigmoid-normalized. Measures response time.

**tool_distribution**
Tool usage pattern drift. Currently uses decision_drift as proxy.

**error_rate**
Absolute error count delta. Measures reliability.

**loop_depth**
P95 loop count delta. Measures reasoning complexity.

**verbosity_ratio**
Output tokens / input tokens delta. Measures chattiness.

**retry_rate**
Average retry count delta. Measures retry frequency.

**output_length**
Average output length delta. Measures response size.

**time_to_first_tool**
Planning latency before first tool call. Measures thinking time.

**semantic_drift**
JSD of semantic cluster distribution. Measures outcome patterns. Requires [semantic] extra.

**tool_sequence_transitions**
Transition matrix divergence. Measures state machine changes. Not yet implemented (uses decision_drift as proxy).

---

## Backend

**StorageBackend**
Abstract interface for persistence. See backends/base.py.

**SQLiteBackend**
Concrete implementation using SQLite + SQLModel. See backends/sqlite.py.

**Factory Pattern**
get_backend() returns cached singleton instance. See backends/factory.py.

**Migration**
Schema change applied via ALTER TABLE in _migrate_schema(). See sqlite.py:193.

---

## CLI

**Rich Markup**
Formatting syntax used by Rich library (e.g., [green]text[/green]). Must escape brackets in dynamic strings.

**CliRunner**
Click testing utility. Simulates CLI invocations without shell. See click.testing.CliRunner.

**Exit Code**
Numeric value returned by CLI command. 0 = success, 1 = error, 10/20/30 = verdicts.

---

## Abbreviations

**P95**
95th percentile. Value below which 95% of data falls.

**JSD**
Jensen-Shannon divergence. Symmetric version of KL divergence.

**CV**
Coefficient of variation. std / mean.

**CI**
Confidence interval. Range containing true value with specified probability (typically 95%).

**SDK**
Software Development Kit. The @track decorator and supporting code.

**CLI**
Command Line Interface. The driftbase command and subcommands.

**ADR**
Architecture Decision Record. Lightweight document explaining a technical decision.
