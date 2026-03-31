# 014 — Confidence Tiers and Verdict Gating

**Status:** Accepted
**Date:** 2026-03-30
**Files affected:** `local/diff.py`, `verdict.py`, `cli/cli_diff.py`

---

## Decision

Verdicts (SHIP/MONITOR/REVIEW/BLOCK) are only shown when both versions
have at least `min_runs_needed` runs (TIER3). Below this threshold, only
directional signal (↑↓→) is shown (TIER2) or nothing (TIER1). This is
a hard constraint — not configurable, not bypassable.

## Why no verdict below statistical significance

Showing SHIP/MONITOR/REVIEW/BLOCK at n=12 implies false precision. The
developer will act on this verdict — potentially blocking a valid deploy
or shipping a broken one. A verdict should only be shown when the
statistical machinery can back it up.

The core issue is that developers trust numbers. A "REVIEW" verdict at
n=15 looks the same as a "REVIEW" verdict at n=150. The developer has no
way to know one is noise and one is signal. By withholding the verdict
until statistical significance is reached, we eliminate this trust problem
entirely.

## Why three tiers, not two (enough / not enough)

**TIER1 (n < 15):** No analysis at all. Below 15 runs, even directional
comparison is unreliable — a single unusual run could flip the direction.
Showing anything would mislead.

**TIER2 (15 ≤ n < min_runs_needed):** Directional signal only. At 15-30
runs, the mean direction of drift is often visible even if the magnitude
is not reliable. Showing ↑ elevated on decision_drift gives the developer
useful information ("something looks interesting here") without implying
a confident magnitude estimate. The progress bar motivates them to collect
more runs.

**TIER3 (n ≥ min_runs_needed):** Full analysis. Statistical machinery is
reliable. Verdict is trustworthy.

The three-tier design converts a binary gate ("not enough / enough") into
a continuous journey the developer can see themselves progressing through.
This is better UX and more honest about the underlying statistics.

## Why min_runs_needed is adaptive, not fixed

See ADR 012 for full reasoning. Summary: a consistent agent can produce a
reliable verdict at 28 runs. A noisy agent might need 85. A fixed threshold
of 50 is wrong for both.

The fixed default of 50 applies only when insufficient baseline data exists
for power analysis (n < 10 baseline runs). Once power analysis can run,
it replaces the fixed threshold.

## Why TIER2 shows direction but not magnitude

Showing drift score values (e.g. "decision_drift: 0.23") in TIER2 implies
a precision that doesn't exist at these sample sizes. The number 0.23 at
n=23 has a very wide confidence interval — it could be anywhere from 0.05
to 0.45 with 95% confidence.

Direction (↑ elevated, → stable, ↓ reduced) is more honest. It says "this
dimension appears to be moving in this direction" without implying we know
how much it moved.

## Why partial TIER3 at 8/12 reliable dimensions

When 8 or more of the 12 dimensions have individually reached their
per-dimension significance threshold, the composite score is reliable
enough for a verdict even if 3-4 low-weight dimensions are still in
TIER2 territory.

The threshold of 8/12 was chosen because:
1. It's a supermajority — not a bare majority
2. The 4 dimensions still in TIER2 are typically the low-weight ones
   (verbosity_ratio, output_length, tool_sequence_transitions)
3. A composite score dominated by 8 reliable high-weight dimensions is
   more trustworthy than waiting for all 12

8/12 is a hard threshold. 7/12 is not partial TIER3 — the reliability
improvement from 7 to 8 dimensions is meaningful.

## Connection to scoring pipeline

The confidence tier system is the front door to the scoring pipeline.
The pipeline (calibration → diff → verdict) runs in full only when TIER3
is reached. This is intentional — running the full pipeline at n=15 would
produce unreliable weights (calibration needs 30 runs) and unreliable
thresholds (power analysis needs sufficient variance estimates).

TIER2 uses a simplified pipeline: extract dimension means, compare means,
derive direction. No calibration, no thresholds, no verdict.

## Exit codes

TIER1: exit 0 (not enough data is not an error)
TIER2: exit 0 (indicative signal only, no actionable verdict)
TIER3: follows normal verdict exit codes (SHIP=0, MONITOR=0, REVIEW=1, BLOCK=1)

This means CI pipelines that run `driftbase diff` before enough data
is collected will not fail the build — they will exit 0 with an
informational message. This is correct: failing the build because the
developer hasn't collected enough runs yet would be punishing the
wrong thing.

## Alternative considered

**Show verdict with explicit uncertainty caveat.**
"REVIEW (low confidence, n=23)" was considered. Rejected because
developers ignore caveats in CI pipelines. The exit code would
still be 1, blocking the deploy, based on unreliable data.
Withholding the verdict is more honest and more useful.

**User-configurable minimum runs.**
Let the developer override min_runs_needed. Rejected because it
creates responsibility transfer — if a developer sets min_runs=10
and gets a wrong verdict, they might blame Driftbase rather than
their configuration choice. Adaptive power analysis is a better answer:
the system computes the right minimum for each agent automatically.
