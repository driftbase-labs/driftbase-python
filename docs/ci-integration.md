# CI/CD Integration

Integrate Driftbase into your deployment pipeline to catch behavioral regressions before they reach production.

## Quick Start

```yaml
# .github/workflows/drift-check.yml
name: Drift Check

on: [pull_request]

jobs:
  drift-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install Driftbase
        run: pip install driftbase

      - name: Run drift check
        run: |
          driftbase diff v1.2.3 v1.3.0 --ci
        env:
          DRIFTBASE_DB_PATH: ./runs.db
```

The `--ci` flag enables:
- JSON output
- Non-zero exit code on drift
- Compact formatting

## Output Formats

### JSON (`--format=json`)

Machine-readable output for programmatic consumption:

```bash
driftbase diff v1.2.3 v1.3.0 --format=json
```

Output structure:

```json
{
  "version": "1.0",
  "verdict": "REVIEW",
  "composite_score": 0.305,
  "confidence_tier": "TIER3",
  "confidence": {
    "ci_lower": 0.252,
    "ci_upper": 0.358
  },
  "top_contributors": [
    {
      "dimension": "decision_drift",
      "observed": 0.412,
      "ci_lower": 0.331,
      "ci_upper": 0.493,
      "significant": true,
      "contribution_pct": 43.2,
      "evidence": "Tool path ['search', 'write'] went from 3% to 27%"
    }
  ],
  "rollback_target": "v1.2.2",
  "power_forecast": {
    "message": "With 15 more runs, statistical power will be sufficient",
    "runs_needed": {
      "decision_drift": 15,
      "latency": 8
    }
  },
  "mdes": {
    "decision_drift": 0.080,
    "latency": 0.050
  },
  "sample_sizes": {
    "baseline": 120,
    "current": 85
  },
  "thresholds": {
    "monitor": 0.15,
    "review": 0.30,
    "block": 0.60
  }
}
```

### Markdown (`--format=markdown`)

GitHub-flavored markdown for PR comments:

```bash
driftbase diff v1.2.3 v1.3.0 --format=markdown
```

Output:

```markdown
## Drift Report: v1.2.3 → v1.3.0

**Verdict:** REVIEW
**Composite Score:** 0.305 (CI: 0.252–0.358)
**Confidence:** TIER3

### Top Contributors

| Dimension       | Observed | CI Lower | CI Upper | Significant | Contribution % | Evidence                               |
|-----------------|----------|----------|----------|-------------|----------------|----------------------------------------|
| decision_drift  | 0.412    | 0.331    | 0.493    | ✓           | 43.2%          | Tool path [...] went from 3% to 27%    |
| latency         | 0.183    | 0.120    | 0.246    | ✓           | 31.5%          | P95 latency increased from 1,240ms...  |
| error_rate      | 0.095    | 0.042    | 0.148    | —           | 18.7%          | Error rate increased from 2.1% to 8.4% |

**MDEs:** decision_drift=0.080, latency=0.050, error_rate=0.030

**Rollback Suggested:** v1.2.2 (last SHIP)
```

## Exit Codes

Driftbase uses exit codes to control CI/CD pipelines:

| Exit Code | Meaning | Default Verdicts |
|-----------|---------|------------------|
| **0** | Safe to deploy | SHIP, MONITOR |
| **1** | Review required | REVIEW, BLOCK |

### Override Exit Behavior

```bash
# Always fail on any drift (even minor)
driftbase diff v1 v2 --fail-on-drift

# Fail only if drift exceeds threshold
driftbase diff v1 v2 --exit-nonzero-above 0.15
```

## GitHub Actions Examples

### PR Comment with Drift Report

```yaml
name: Drift Report

on: [pull_request]

jobs:
  drift:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - run: pip install driftbase

      - name: Generate drift report
        id: drift
        run: |
          OUTPUT=$(driftbase diff v1.2.3 v1.3.0 --format=markdown)
          echo "report<<EOF" >> $GITHUB_OUTPUT
          echo "$OUTPUT" >> $GITHUB_OUTPUT
          echo "EOF" >> $GITHUB_OUTPUT
        env:
          DRIFTBASE_DB_PATH: ./runs.db

      - name: Comment on PR
        uses: actions/github-script@v7
        with:
          script: |
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.name,
              body: `${{ steps.drift.outputs.report }}`
            })
```

### Block Deployment on Drift

```yaml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  drift-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5

      - run: pip install driftbase

      - name: Drift gate
        run: driftbase diff ${{ env.LAST_DEPLOY }} ${{ github.sha }} --ci
        env:
          DRIFTBASE_DB_PATH: ./runs.db
          LAST_DEPLOY: v1.2.3

  deploy:
    needs: drift-gate
    runs-on: ubuntu-latest
    steps:
      - name: Deploy
        run: ./deploy.sh
```

### Store Verdict for Later Analysis

```yaml
- name: Run drift check and save verdict
  id: drift
  run: |
    OUTPUT=$(driftbase diff v1 v2 --format=json)
    echo "$OUTPUT" > drift-report.json
    echo "verdict=$(echo $OUTPUT | jq -r .verdict)" >> $GITHUB_OUTPUT

- name: Upload artifact
  uses: actions/upload-artifact@v4
  with:
    name: drift-report
    path: drift-report.json

- name: Fail on BLOCK
  if: steps.drift.outputs.verdict == 'BLOCK'
  run: exit 1
```

## GitLab CI Example

```yaml
drift_check:
  image: python:3.11
  script:
    - pip install driftbase
    - driftbase diff ${LAST_DEPLOY} ${CI_COMMIT_SHA} --ci
  variables:
    DRIFTBASE_DB_PATH: ./runs.db
  only:
    - merge_requests
```

## CircleCI Example

```yaml
version: 2.1

jobs:
  drift-check:
    docker:
      - image: cimg/python:3.11
    steps:
      - checkout
      - run: pip install driftbase
      - run: driftbase diff v1.2.3 v1.3.0 --ci

workflows:
  pr-check:
    jobs:
      - drift-check
```

## Best Practices

### 1. Import Traces Before Diffing

```bash
# Import traces from Langfuse
driftbase connect --import-last 7d

# Then run diff
driftbase diff v1.2.3 v1.3.0 --ci
```

### 2. Use Environment Variables

```bash
export DRIFTBASE_DB_PATH=/path/to/runs.db
export DRIFTBASE_ENVIRONMENT=staging

driftbase diff v1 v2 --ci
```

### 3. Filter by Time Window

```bash
# Compare only runs from last 24 hours
driftbase diff v1 v2 --since 24h --ci

# Compare specific date range
driftbase diff v1 v2 --between 2026-03-01..2026-03-15 --ci
```

### 4. Speed Optimization

For faster CI runs with large datasets:

```bash
# Limit sample size (trades precision for speed)
driftbase diff v1 v2 --max-samples 500 --ci

# Skip slow analyses (not recommended for production gates)
driftbase diff v1 v2 --no-stats --ci
```

### 5. Rollback on BLOCK

```bash
#!/bin/bash
VERDICT=$(driftbase diff v1.2.3 v1.3.0 --format=json | jq -r .verdict)
ROLLBACK=$(driftbase diff v1.2.3 v1.3.0 --format=json | jq -r .rollback_target)

if [ "$VERDICT" = "BLOCK" ]; then
  echo "Behavioral regression detected. Rolling back to $ROLLBACK"
  kubectl set image deployment/agent agent=$ROLLBACK
  exit 1
fi
```

## Interpreting Results in CI

### SHIP (Exit 0)
✅ Deploy without restrictions.

### MONITOR (Exit 0)
⚠️ Safe to deploy, but watch initial rollout:
- Set up alerts for error rates
- Monitor first 24h closely
- Consider canary deployment

### REVIEW (Exit 1)
🔍 Manual review required:
1. Run `driftbase explain` to see breakdown
2. Check top contributors against code changes
3. If expected: merge and deploy
4. If unexpected: investigate before deploying

### BLOCK (Exit 1)
🚫 Do not deploy:
1. Run `driftbase explain` to identify root cause
2. Check rollback target: `jq -r .rollback_target drift-report.json`
3. Investigate code changes
4. Fix issue or revert changes
5. Re-run tests with more runs if sample size is low

## Troubleshooting

### "Not enough runs to diff"

Minimum 15 runs per version required (TIER2), 50+ recommended (TIER3).

**Solution:**
```bash
# Check run counts
driftbase runs -v v1.2.3 --format json | jq '.total_count'

# Import more traces
driftbase connect --import-last 14d
```

### "TIER2: Directional signal only"

15–49 runs available—shows trend but no statistical verdict.

**Solution:** Collect more runs or accept directional signal for low-risk deploys.

### Slow CI Runs

**Solutions:**
- Use `--max-samples 500` to limit data
- Cache `runs.db` between CI runs
- Run drift check nightly instead of per-PR

### False Positives

**Solutions:**
- Check MDEs: Drift < MDE may be noise
- Review evidence: Is change intentional?
- Increase sample size for higher confidence
- Adjust thresholds: `export DRIFTBASE_DRIFT_THRESHOLD=0.25`

## Advanced: Custom Thresholds

Override verdict thresholds per environment:

```bash
# Staging: more lenient
export DRIFTBASE_DRIFT_THRESHOLD=0.40
driftbase diff v1 v2 --ci

# Production: stricter
export DRIFTBASE_DRIFT_THRESHOLD=0.15
driftbase diff v1 v2 --ci
```

Thresholds can also be set in `.driftbase/config`:

```
DRIFTBASE_DRIFT_THRESHOLD=0.20
DRIFTBASE_MIN_SAMPLES=30
```

## Verdict History API

Access verdict history programmatically:

```bash
# List recent verdicts
driftbase history --format json

# Get specific verdict
driftbase explain <VERDICT_ID> --format json
```

Use in automation:

```bash
LAST_VERDICT=$(driftbase history --format json | jq -r '.[0].verdict')
if [ "$LAST_VERDICT" = "SHIP" ]; then
  echo "Last deployment was safe—proceeding"
fi
```
