# Feedback Loop

Driftbase learns from your drift verdicts. When you dismiss a drift alert as expected behavior, the system automatically downweights that dimension for future comparisons on that agent.

## What is the Feedback Loop?

The feedback loop is a weight learning system that adapts drift detection to your agent's evolution. When you mark certain dimensions as "expected changes", Driftbase remembers this and reduces their contribution to future drift scores — but only for that specific agent.

## Why Per-Agent Learning?

Different agents have different behavioral signatures:
- Agent A might frequently change tool sequences (expected)
- Agent B might have stable sequences but variable latency (expected)

Feedback for Agent A doesn't affect Agent B. This prevents cross-agent pollution and ensures accurate drift detection across your fleet.

## Commands

### Record Feedback

```bash
# Dismiss a verdict (downweight dimensions)
driftbase feedback <verdict_id> --dismiss \
  --reason "Tool sequence change is intentional" \
  --dimensions "decision_drift,tool_sequence"

# Acknowledge a verdict (neutral record)
driftbase feedback <verdict_id> --acknowledge \
  --reason "Reviewed and noted"

# Mark for investigation
driftbase feedback <verdict_id> --investigate \
  --reason "Needs further analysis"
```

### View Feedback Impact

```bash
# Show weight adjustments for an agent
driftbase feedback <agent_id> --impact
```

Output:
```
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┓
┃ Dimension      ┃ Base Weight ┃ Adjusted Weight ┃ Dismiss Count ┃ Effective % ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━┩
│ decision_drift │       0.220 │           0.108 │             2 │         49% │
│ tool_sequence  │       0.160 │           0.112 │             1 │         70% │
└────────────────┴─────────────┴─────────────────┴───────────────┴─────────────┘
```

### List Feedback History

```bash
# List all feedback
driftbase feedback --list

# List feedback for specific agent
driftbase feedback --list --agent <agent_id>
```

### Reset Feedback

```bash
# Reset (delete) all feedback for an agent
driftbase feedback <agent_id> --reset --confirm
```

## Weight Decay Formula

Each dismissal applies exponential decay:

```
adjusted_weight = base_weight × (0.7 ** dismiss_count)
```

Examples:
- 1 dismiss → 70% of original weight
- 2 dismisses → 49% (0.7²)
- 3 dismisses → 34% (0.7³)

### Weight Floor

Weights never drop below 10% of the original value, ensuring dimensions can still detect catastrophic regressions even after many dismissals.

## Example Workflow

### Scenario: Tool Sequence Evolution

Your agent v2 intentionally switches from `["search", "read"]` to `["search", "write"]` as part of a planned architectural change.

1. **Run diff**:
   ```bash
   driftbase diff v1 v2
   ```

   Output shows high `decision_drift` (0.85) → `REVIEW` verdict.

2. **Dismiss as expected**:
   ```bash
   # Get verdict_id from diff output or `driftbase explain`
   driftbase feedback <verdict_id> --dismiss \
     --reason "Planned migration to write-heavy architecture" \
     --dimensions "decision_drift,tool_sequence"
   ```

3. **Future comparisons**:
   - v2 → v3 diff now uses 70% weight for `decision_drift`
   - If v3 → v4 also changes tool sequences: 49% weight (0.7²)
   - Latency, error_rate, etc. remain fully weighted

4. **Verify impact**:
   ```bash
   driftbase feedback <agent_id> --impact
   ```

## Best Practices

### When to Dismiss

- **Planned changes**: New features, refactors, migrations
- **Expected drift**: Tool sequence evolution, output format changes
- **Calibration adjustments**: After validating a dimension is overly sensitive

### When NOT to Dismiss

- **Performance regressions**: Latency increases, error spikes
- **Unexpected behavior**: Changes you don't understand
- **One-off anomalies**: Use `--investigate` instead to track without downweighting

### Dimension Selection

Be specific:
```bash
# Good: Only dismiss what you reviewed
--dimensions "decision_drift,tool_sequence"

# Risky: Dismissing everything
--dimensions "decision_drift,latency,error_rate,..."  # Avoid
```

## Integration with CI

```yaml
# .github/workflows/drift.yml
- name: Run drift check
  run: driftbase diff ${{ github.base_ref }} ${{ github.head_ref }}
  continue-on-error: true

- name: Dismiss expected drift (optional)
  if: contains(github.event.pull_request.labels.*.name, 'expected-drift')
  run: |
    VERDICT_ID=$(driftbase diff --format=json | jq -r '.verdict_id')
    driftbase feedback $VERDICT_ID --dismiss \
      --reason "PR labeled as expected drift: ${{ github.event.pull_request.title }}" \
      --dimensions "${{ github.event.inputs.dimensions }}"
```

## Feedback Storage

Feedback is stored in SQLite (`~/.driftbase/runs.db`) in the `feedback` table:

```sql
CREATE TABLE feedback (
    id TEXT PRIMARY KEY,
    verdict_id TEXT NOT NULL,
    action TEXT NOT NULL,  -- 'dismiss' | 'acknowledge' | 'investigate'
    agent_id TEXT,
    reason TEXT,
    dismissed_dimensions TEXT,  -- JSON array
    created_at TIMESTAMP,
    FOREIGN KEY (verdict_id) REFERENCES verdict_history(id)
);
```

## Troubleshooting

### Feedback not reducing drift scores

Check:
1. `agent_id` is correctly extracted (should match across runs)
2. Dismissed dimensions match exactly (e.g., `decision_drift` not `decisionDrift`)
3. Backend is passed to `compute_drift()` (required for feedback application)

### Resetting feedback

If you over-dismissed and want to restore original weights:
```bash
driftbase feedback <agent_id> --reset --confirm
```

This deletes all feedback for that agent. Future diffs will use default weights.

## See Also

- [OTLP Metrics](otlp-metrics.md) - Observability integration
- [Weight Learning](../CLAUDE.md#weight-learning) - Technical details
