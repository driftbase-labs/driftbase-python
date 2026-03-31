# 007 — Learned Weights Blending Formula

**Status:** Accepted
**Date:** 2026-03-30
**Files affected:** `local/weight_learner.py`, `local/baseline_calibrator.py`

---

## Decision

Learned weights from deploy outcome labeling blend with calibrated preset
weights using an adaptive factor that scales with training set size:

```python
learned_factor = min(0.90, (n_samples - 10) / 100 + 0.20)
preset_factor  = 1.0 - learned_factor

blended[dim] = learned_factor * learned_weights[dim]
             + preset_factor  * calibrated_weights[dim]
```

At n=10:  learned_factor = 0.20  (20% learned, 80% calibrated)
At n=20:  learned_factor = 0.30
At n=50:  learned_factor = 0.60
At n=100: learned_factor = 0.90
At n=200: learned_factor = 0.90  (cap — never exceeds 0.90)

## Why blend rather than replace

Fully replacing calibrated weights with learned weights at any sample size
would create fragile scoring. Point-biserial correlation on 10-15 labeled
deploys is statistically noisy — a few coincidental correlations could produce
learned weights that overfit to those specific incidents.

Blending with calibrated weights provides a regularization effect: the
calibrated weights (derived from baseline variance and use-case inference)
act as a prior. The learned weights shift the system toward patterns specific
to this agent's incident history without fully discarding the principled prior.

## Why the cap is 0.90, not 1.0

Even at 200+ labeled deploys, we never fully trust learned weights alone.
Two reasons:

1. **Label quality degrades over time.** What counts as "bad" changes as
   the agent matures. Early bad deploys may have been bad for reasons no
   longer relevant. Keeping 10% calibrated weight maintains a floor of
   principled signal.

2. **Catastrophic forgetting prevention.** If a dimension has never been
   elevated before a bad deploy (correlation = 0, learned weight = 0),
   fully learned weights would zero it out entirely. But absence of evidence
   is not evidence of absence — that dimension might matter for a novel
   failure mode not yet seen. The 10% calibrated floor keeps all dimensions
   non-zero.

## Why the minimum is 0.20, not 0.0

At exactly n=10 (minimum required), learned weights are very noisy. But
they still carry signal — the developer labeled these deploys deliberately.
Starting at 0.20 respects that signal without over-trusting it.

Below n=10, learned weights are not used at all (function returns None).

## Why the slope is 1/100

The formula `(n - 10) / 100` means each additional labeled deploy increases
the learned factor by 0.01. This is intentional — you need 90 additional
deploys (beyond the minimum 10) to go from minimum trust to maximum trust.
Slower ramp = more conservative = fewer false positives during the learning
period.

A steeper slope (e.g. 1/50) would reach full trust at n=55, which is too
aggressive for the amount of label data typically available.

## Why point-biserial correlation, not logistic regression

Both approaches work. Point-biserial correlation was chosen because:

1. **Interpretability.** The correlation coefficient directly tells you
   "how strongly does this dimension predict bad outcomes." Easy to explain.

2. **No hyperparameters.** Logistic regression requires regularization
   tuning. Point-biserial is parameter-free.

3. **Small sample robustness.** Logistic regression can overfit on small
   samples (n=10-30). Point-biserial is more stable at these sizes.

4. **Negative correlations are clipped to 0.** A dimension that goes DOWN
   before bad outcomes (negative correlation) is not double-counting — it's
   a different signal. We only up-weight dimensions that reliably predict
   problems. Clipping to 0 is natural with correlation but requires extra
   handling in logistic regression.

## Alternative considered

**Use the learned weights directly without blending.**
Rejected — creates fragile, overfitted scoring at low sample sizes.

**Use Bayesian updating instead of linear blending.**
Rejected — more theoretically correct but requires specifying a prior
distribution over weight space, adding complexity with minimal practical
benefit at the sample sizes we're working with.

**Weight by statistical significance (p-value) rather than sample size.**
Rejected — p-values at n=10-30 are unreliable and would create
inconsistent behavior across agents with different behavioral variance.
Sample size is a more stable proxy for trustworthiness.
