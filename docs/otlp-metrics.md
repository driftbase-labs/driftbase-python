# OTLP Metrics Emission

Driftbase emits drift scores as OpenTelemetry Protocol (OTLP) compatible metrics, enabling integration with your existing observability stack (Prometheus, Grafana, Datadog, etc.).

## Overview

Every time you run `driftbase diff`, drift metrics are automatically written to a local JSON file in OTLP-compatible format. External collectors can scrape this file and forward metrics to your monitoring system.

## Configuration

### Metrics File Location

Default: `~/.driftbase/metrics.json`

Override:
```bash
export DRIFTBASE_METRICS_PATH=/path/to/metrics.json
```

### Enable/Disable Metrics

Metrics are enabled by default. To disable:
```bash
driftbase diff v1 v2 --no-emit-metrics
```

### Metrics Endpoint (Future)

The `--metrics-endpoint` flag is reserved for future direct OTLP push support:
```bash
driftbase diff v1 v2 --metrics-endpoint http://localhost:4318
```

Currently, this flag is accepted but unused. Use file-based scraping for now.

## Metrics Emitted

### Drift Scores

#### `driftbase.drift.composite`
**Type**: Gauge
**Range**: [0, 1]
**Description**: Overall drift score combining all dimensions

```json
{
  "name": "driftbase.drift.composite",
  "type": "gauge",
  "value": 0.45,
  "attributes": {
    "baseline_version": "v1.0.0",
    "current_version": "v1.1.0",
    "environment": "production",
    "verdict": "MONITOR"
  }
}
```

#### Per-Dimension Drift

- `driftbase.drift.decision` - Tool sequence outcome distribution
- `driftbase.drift.latency` - P95 latency drift
- `driftbase.drift.error` - Error rate change
- `driftbase.drift.semantic` - Semantic cluster distribution
- `driftbase.drift.tool_distribution` - Tool frequency changes
- `driftbase.drift.verbosity` - Output verbosity ratio
- `driftbase.drift.loop_depth` - Loop count changes
- `driftbase.drift.output_length` - Output length changes
- `driftbase.drift.tool_sequence` - Tool sequence patterns
- `driftbase.drift.retry` - Retry rate changes
- `driftbase.drift.time_to_first_tool` - Planning time changes
- `driftbase.drift.tool_sequence_transitions` - Bigram transition patterns

### Verdict

#### `driftbase.verdict`
**Type**: Gauge
**Range**: [0, 3]
**Description**: Numeric verdict mapping

- 0 = SHIP
- 1 = MONITOR
- 2 = REVIEW
- 3 = BLOCK

### Confidence Tier

#### `driftbase.confidence_tier`
**Type**: Gauge
**Range**: [1, 3]
**Description**: Statistical confidence level

- 1 = TIER1 (n < 15, insufficient data)
- 2 = TIER2 (15 ≤ n < min_runs, directional signal only)
- 3 = TIER3 (n ≥ min_runs, full analysis)

## Metrics File Format

```json
{
  "format": "driftbase_otlp_v1",
  "exported_at": "2026-04-23T10:30:00.123456",
  "metrics": [
    {
      "name": "driftbase.drift.composite",
      "type": "gauge",
      "value": 0.45,
      "timestamp": 1745324600000,
      "attributes": {
        "baseline_version": "v1.0.0",
        "current_version": "v1.1.0",
        "environment": "production",
        "verdict": "MONITOR"
      }
    }
  ]
}
```

## Prometheus Integration

### Node Exporter Textfile Collector

1. **Convert JSON to Prometheus format**:

```bash
#!/bin/bash
# /usr/local/bin/driftbase-to-prom.sh

METRICS_FILE="${DRIFTBASE_METRICS_PATH:-$HOME/.driftbase/metrics.json}"
OUTPUT_FILE="/var/lib/node_exporter/textfile_collector/driftbase.prom"

if [ ! -f "$METRICS_FILE" ]; then
  echo "# No metrics file found" > "$OUTPUT_FILE"
  exit 0
fi

# Extract metrics and convert to Prometheus format
jq -r '.metrics[] |
  "# TYPE " + .name + " gauge\n" +
  .name + "{" +
    (.attributes | to_entries | map(.key + "=\"" + .value + "\"") | join(",")) +
  "} " + (.value | tostring)
' "$METRICS_FILE" > "$OUTPUT_FILE.tmp"

mv "$OUTPUT_FILE.tmp" "$OUTPUT_FILE"
```

2. **Schedule conversion**:

```cron
* * * * * /usr/local/bin/driftbase-to-prom.sh
```

3. **Configure Node Exporter**:

```bash
node_exporter --collector.textfile.directory=/var/lib/node_exporter/textfile_collector
```

### Prometheus Scrape Config

```yaml
scrape_configs:
  - job_name: 'driftbase'
    static_configs:
      - targets: ['localhost:9100']
    relabel_configs:
      - source_labels: [__name__]
        regex: 'driftbase_.*'
        action: keep
```

## Grafana Dashboard

### Example PromQL Queries

**Drift Score Over Time**:
```promql
driftbase_drift_composite{environment="production"}
```

**Verdict Distribution**:
```promql
count by (verdict) (driftbase_verdict)
```

**High-Drift Dimensions**:
```promql
topk(5,
  rate(driftbase_drift_decision[1h]) or
  rate(driftbase_drift_latency[1h]) or
  rate(driftbase_drift_error[1h])
)
```

### Dashboard Template

```json
{
  "dashboard": {
    "title": "Driftbase Drift Monitoring",
    "panels": [
      {
        "title": "Composite Drift Score",
        "targets": [
          {
            "expr": "driftbase_drift_composite",
            "legendFormat": "{{baseline_version}} → {{current_version}}"
          }
        ],
        "type": "graph"
      },
      {
        "title": "Verdicts",
        "targets": [
          {
            "expr": "driftbase_verdict",
            "legendFormat": "{{verdict}}"
          }
        ],
        "type": "stat",
        "mappings": [
          {"value": 0, "text": "SHIP", "color": "green"},
          {"value": 1, "text": "MONITOR", "color": "yellow"},
          {"value": 2, "text": "REVIEW", "color": "orange"},
          {"value": 3, "text": "BLOCK", "color": "red"}
        ]
      }
    ]
  }
}
```

## Datadog Integration

### Datadog Agent Custom Check

```python
# /etc/datadog-agent/checks.d/driftbase.py

import json
from checks import AgentCheck

class DriftbaseCheck(AgentCheck):
    def check(self, instance):
        metrics_file = instance.get('metrics_file',
                                    '/home/user/.driftbase/metrics.json')

        try:
            with open(metrics_file) as f:
                data = json.load(f)

            for metric in data['metrics']:
                tags = [f"{k}:{v}" for k, v in metric['attributes'].items()]
                self.gauge(metric['name'], metric['value'], tags=tags)

        except Exception as e:
            self.log.warning(f"Failed to read driftbase metrics: {e}")
```

```yaml
# /etc/datadog-agent/conf.d/driftbase.yaml
instances:
  - metrics_file: /home/user/.driftbase/metrics.json
```

## Alerting Examples

### Prometheus Alerting Rules

```yaml
groups:
  - name: driftbase
    interval: 1m
    rules:
      - alert: HighDriftScore
        expr: driftbase_drift_composite > 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High drift detected: {{ $labels.baseline_version }} → {{ $labels.current_version }}"
          description: "Composite drift score is {{ $value }}"

      - alert: BlockVerdict
        expr: driftbase_verdict == 3
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "BLOCK verdict: {{ $labels.baseline_version }} → {{ $labels.current_version }}"

      - alert: InsufficientData
        expr: driftbase_confidence_tier < 3
        for: 10m
        labels:
          severity: info
        annotations:
          summary: "Insufficient data for reliable drift detection"
```

### Slack Webhook

```bash
#!/bin/bash
# Alert on high drift

DRIFT_SCORE=$(jq -r '.metrics[] | select(.name == "driftbase.drift.composite") | .value' \
  ~/.driftbase/metrics.json)

if (( $(echo "$DRIFT_SCORE > 0.5" | bc -l) )); then
  curl -X POST https://hooks.slack.com/services/YOUR/WEBHOOK/URL \
    -H 'Content-Type: application/json' \
    -d "{\"text\": \"🚨 High drift detected: $DRIFT_SCORE\"}"
fi
```

## Troubleshooting

### Metrics file not updating

Check:
```bash
# Verify metrics emission is enabled
driftbase diff v1 v2  # Should create/update metrics file

# Check file location
echo $DRIFTBASE_METRICS_PATH
ls -l ~/.driftbase/metrics.json

# Verify file permissions
chmod 644 ~/.driftbase/metrics.json
```

### Prometheus not scraping

Check:
```bash
# Verify Prometheus format conversion
cat /var/lib/node_exporter/textfile_collector/driftbase.prom

# Check Node Exporter
curl http://localhost:9100/metrics | grep driftbase
```

### Missing metrics

Metrics are only emitted after a successful `driftbase diff`. Run a diff first:
```bash
driftbase diff v1 v2
cat ~/.driftbase/metrics.json
```

## See Also

- [Feedback Loop](feedback.md) - Weight learning from drift verdicts
- [Prometheus Documentation](https://prometheus.io/docs/)
- [OpenTelemetry Protocol](https://opentelemetry.io/docs/specs/otlp/)
