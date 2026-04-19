"""
Privacy-first telemetry for Driftbase.

TODO (PHASE 8 - DEFERRED until Cloud API is live):
    This module will implement privacy-first usage telemetry with the following requirements:

    1. Opt-out by default - users must explicitly opt-in via environment variable
    2. Local aggregation - no raw data transmission
    3. No PII - all identifiers are hashed/anonymized
    4. Clear value exchange - users see what data is sent before enabling
    5. API endpoint: POST api.driftbase.io/api/v1/telemetry (does not exist yet)

    Telemetry data will include:
    - Command usage frequency (e.g., "diff", "diagnose", "connect")
    - Drift score distributions (aggregated, not per-run)
    - Error types and frequencies
    - Performance metrics (latency, memory)
    - Feature adoption (e.g., "weight learning enabled", "MCP server used")

    What is NOT collected:
    - Agent prompts or outputs
    - User identifiers (email, name, etc.)
    - Repository names or project names
    - Individual drift scores
    - Individual run data

    Configuration:
        export DRIFTBASE_TELEMETRY=true  # Opt-in
        driftbase telemetry enable       # Interactive opt-in with consent dialog
        driftbase telemetry status       # Show what data would be sent
        driftbase telemetry disable      # Opt-out

    Implementation blocked by:
    - api.driftbase.io/api/v1/telemetry endpoint does not exist yet
    - Cloud backend infrastructure not deployed

    Shipping telemetry code that phones home to a non-existent endpoint is worse
    than no telemetry. This will be implemented after Cloud is running.

    See CHANGELOG.md for more context on why this is deferred.
"""


def is_telemetry_enabled() -> bool:
    """Telemetry is disabled until Cloud API is live."""
    return False
