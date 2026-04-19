#!/usr/bin/env python3
"""
Driftbase GitHub Action - Drift Check Runner

Executes drift comparison between two agent versions and posts results
as a PR comment with optional CI gating based on verdict.

Supports two modes:
- STANDALONE: Uses local SQLite + `driftbase diff --ci` command
- CLOUD: POSTs to api.driftbase.io/api/v1/ci/diff

Environment Variables (from action inputs):
- INPUT_BASELINE_VERSION: Baseline version identifier
- INPUT_CURRENT_VERSION: Current version identifier
- INPUT_DRIFTBASE_API_KEY: Driftbase Cloud API key (optional)
- INPUT_FAIL_ON_REVIEW: Exit 1 on REVIEW verdict (true/false)
- INPUT_FAIL_ON_MONITOR: Exit 1 on MONITOR verdict (true/false)
- INPUT_GITHUB_TOKEN: GitHub token for API calls
- INPUT_ENVIRONMENT: Environment filter (production/staging/etc)
- INPUT_SENSITIVITY: Threshold sensitivity (strict/standard/relaxed)

GitHub Context Variables:
- GITHUB_REPOSITORY: owner/repo
- GITHUB_EVENT_NAME: pull_request, push, etc.
- GITHUB_EVENT_PATH: Path to event payload JSON
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


def log(message: str) -> None:
    """Print to stdout with GitHub Actions formatting."""
    print(f"::notice::{message}")


def error(message: str) -> None:
    """Print error to stdout with GitHub Actions formatting."""
    print(f"::error::{message}", file=sys.stderr)


def set_output(name: str, value: str) -> None:
    """Set GitHub Actions output."""
    output_file = os.getenv("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"{name}={value}\n")


def get_input(name: str, required: bool = False, default: str = "") -> str:
    """Get action input from environment variable."""
    # Convert hyphen-separated names to underscore-separated
    env_name = name.upper().replace("-", "_")
    value = os.getenv(f"INPUT_{env_name}", default)
    if required and not value:
        error(f"Missing required input: {name}")
        sys.exit(1)
    return value


def get_pr_number() -> Optional[int]:
    """Extract PR number from GitHub event context."""
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if not event_path or not os.path.exists(event_path):
        return None

    try:
        with open(event_path) as f:
            event = json.load(f)

        # pull_request event
        if "pull_request" in event:
            return event["pull_request"]["number"]

        # issue_comment event
        if "issue" in event and "pull_request" in event["issue"]:
            return event["issue"]["number"]

        return None
    except Exception as e:
        error(f"Failed to parse GitHub event: {e}")
        return None


def run_standalone_mode(
    baseline: str, current: str, environment: str, sensitivity: str
) -> Dict[str, Any]:
    """
    Execute driftbase diff command in standalone mode (local SQLite).

    Returns dict with keys: drift_score, verdict, dimensions, explanation, next_steps, etc.
    """
    cmd = ["driftbase", "diff", baseline, current, "--ci"]

    if environment:
        cmd.extend(["--environment", environment])
    if sensitivity:
        cmd.extend(["--sensitivity", sensitivity])

    log(f"Running standalone mode: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        # Try to parse JSON output (--ci flag returns JSON)
        output = result.stdout.strip()
        if output:
            try:
                data = json.loads(output)
                return data
            except json.JSONDecodeError as e:
                error(f"Failed to parse JSON output: {e}")
                error(f"Raw output: {output}")

        # Handle error cases
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "No runs found" in stderr or "No runs found" in output:
                return {
                    "error": "no_data",
                    "message": f"No baseline runs found for {baseline}",
                }
            if "Insufficient data" in stderr or "TIER1" in output or "TIER2" in output:
                return {
                    "error": "insufficient_data",
                    "message": "Insufficient data to compute drift score (need 50+ runs per version)",
                }

            error(f"driftbase diff failed: {stderr}")
            return {"error": "command_failed", "message": stderr}

        return {"error": "empty_output", "message": "No output from driftbase diff"}

    except subprocess.TimeoutExpired:
        error("driftbase diff command timed out after 120s")
        return {"error": "timeout", "message": "Command timeout"}
    except Exception as e:
        error(f"Unexpected error running driftbase diff: {e}")
        return {"error": "unexpected", "message": str(e)}


def run_cloud_mode(
    baseline: str, current: str, api_key: str, environment: str, sensitivity: str
) -> Dict[str, Any]:
    """
    Execute drift check via Driftbase Cloud API.

    POSTs to https://api.driftbase.io/api/v1/ci/diff
    Returns DriftReport JSON.
    """
    url = "https://api.driftbase.io/api/v1/ci/diff"

    payload = {
        "baseline_version": baseline,
        "current_version": current,
        "environment": environment or "production",
        "sensitivity": sensitivity or "standard",
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    log(f"Running cloud mode: POST {url}")

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            # Add cloud_mode flag for PR comment formatting
            data["cloud_mode"] = True
            return data

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        error(f"Cloud API error {e.code}: {error_body}")
        return {"error": "api_error", "message": f"HTTP {e.code}: {error_body}"}
    except Exception as e:
        error(f"Cloud API request failed: {e}")
        return {"error": "api_request_failed", "message": str(e)}


def github_api_request(
    endpoint: str, method: str, token: str, data: Optional[Dict] = None
) -> Optional[Dict]:
    """Make authenticated GitHub API request."""
    url = f"https://api.github.com{endpoint}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            if method == "DELETE":
                return {"status": "deleted"}
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error(f"GitHub API error {e.code}: {e.reason}")
        return None
    except Exception as e:
        error(f"GitHub API request failed: {e}")
        return None


def delete_previous_comments(repo: str, pr_number: int, token: str) -> None:
    """Delete previous Driftbase comments on this PR to avoid spam."""
    comments = github_api_request(
        f"/repos/{repo}/issues/{pr_number}/comments", "GET", token
    )

    if not comments:
        return

    # Find and delete Driftbase comments (identified by footer marker)
    marker = "Driftbase Behavioral Report"
    deleted_count = 0

    for comment in comments:
        if marker in comment.get("body", ""):
            comment_id = comment["id"]
            result = github_api_request(
                f"/repos/{repo}/issues/comments/{comment_id}", "DELETE", token
            )
            if result:
                deleted_count += 1

    if deleted_count > 0:
        log(f"Deleted {deleted_count} previous Driftbase comment(s)")


def format_drift_report(data: Dict[str, Any], baseline: str, current: str) -> str:
    """
    Format drift data as markdown PR comment.

    This is the most important UX moment - must be immediately readable
    by a CTO who has never heard of Driftbase.
    """

    # Handle error cases
    if "error" in data:
        if data["error"] == "no_data":
            return f"""## 🔍 Driftbase Behavioral Report

**{baseline}** → **{current}**

---

### ⚠️ No baseline data found

Driftbase cannot compute drift because there are no recorded runs for `{baseline}`.

**Next steps:**
- Ensure baseline version has been deployed and runs recorded
- Check that version identifiers match exactly (case-sensitive)
- Verify environment filter is correct

---
<sub>🤖 Generated by [Driftbase](https://driftbase.io) — 100% local, zero data transmission</sub>
"""

        if data["error"] == "insufficient_data":
            return f"""## 🔍 Driftbase Behavioral Report

**{baseline}** → **{current}**

---

### ⏳ Insufficient data for statistical analysis

Both versions need at least **50 runs** to compute a meaningful drift score.

Currently: **{data.get("baseline_n", "unknown")}** baseline runs, **{data.get("current_n", "unknown")}** current runs

**What to do:**
- Continue deploying and collecting runs
- Check back when you have 50+ runs per version
- Typical timeline: 1-7 days depending on traffic

---
<sub>🤖 Generated by [Driftbase](https://driftbase.io) — 100% local, zero data transmission</sub>
"""

        # Generic error
        return f"""## 🔍 Driftbase Behavioral Report

**{baseline}** → **{current}**

---

### ❌ Drift check failed

```
{data.get("message", "Unknown error")}
```

---
<sub>🤖 Generated by [Driftbase](https://driftbase.io) — 100% local, zero data transmission</sub>
"""

    # Extract data
    drift_score = data.get("drift_score", 0.0)
    verdict = data.get("verdict", "unknown")
    severity = data.get("severity", "unknown")
    baseline_n = data.get("baseline_n", "N/A")
    eval_n = data.get("eval_n", "N/A")
    confidence_tier = data.get("confidence_tier", "TIER3")
    cloud_mode = data.get("cloud_mode", False)

    # Verdict badge and styling
    verdict_config = {
        "ship": {"emoji": "✅", "text": "SHIP IT", "color": "#22c55e"},
        "monitor": {"emoji": "👀", "text": "SHIP WITH MONITORING", "color": "#eab308"},
        "review": {"emoji": "⚠️", "text": "REVIEW BEFORE SHIPPING", "color": "#f97316"},
        "block": {"emoji": "🚫", "text": "DO NOT SHIP", "color": "#ef4444"},
    }

    verdict_lower = verdict.lower()
    config = verdict_config.get(
        verdict_lower, {"emoji": "•", "text": verdict.upper(), "color": "#6b7280"}
    )

    # Build dimensions table
    dimensions = []
    dimension_data = data.get("dimensions", {}) or {}

    # Map dimension keys to display names
    dim_names = {
        "decision_drift": "Decision patterns",
        "latency_drift": "Latency",
        "error_drift": "Error rate",
        "tool_sequence": "Tool sequencing",
        "semantic_drift": "Semantic clusters",
        "loop_depth_drift": "Reasoning depth",
        "verbosity_drift": "Verbosity",
        "retry_drift": "Retry rate",
        "output_length_drift": "Output length",
        "planning_latency_drift": "Planning latency",
        "tool_sequence_transitions_drift": "Tool transitions",
    }

    for key, display_name in dim_names.items():
        value = dimension_data.get(key)
        if value is not None and value > 0:
            # Format as percentage change
            pct = value * 100
            if pct >= 50:
                icon = "🔴"
            elif pct >= 20:
                icon = "🟡"
            else:
                icon = "🟢"
            dimensions.append(f"| {icon} **{display_name}** | {pct:.0f}% |")

    dims_table = "\n".join(dimensions) if dimensions else "| 🟢 **All stable** | <5% |"

    # Explanation and next steps
    explanation = data.get("explanation", "Behavioral analysis completed")
    next_steps = data.get("next_steps", [])
    next_steps_md = (
        "\n".join([f"- {step}" for step in next_steps])
        if next_steps
        else "- Continue monitoring"
    )

    # Cloud mode: add "View full report" link
    cloud_link = ""
    if cloud_mode and data.get("report_url"):
        cloud_link = f"\n\n[📊 View full report →]({data['report_url']})"

    # Format the comment
    return f"""## 🔍 Driftbase Behavioral Report

**{baseline}** → **{current}**

---

### {config["emoji"]} **{config["text"]}**

| | |
|---|---|
| **Drift Score** | **{drift_score:.2f}** ({severity}) |
| **Confidence** | {confidence_tier} |
| **Sample Size** | {baseline_n} baseline · {eval_n} current |

### What Changed

| Dimension | Drift |
|---|---|
{dims_table}

### Analysis

{explanation}

**Recommended actions:**
{next_steps_md}{cloud_link}

---
<sub>🤖 Generated by [Driftbase](https://driftbase.io){" — Cloud API" if cloud_mode else " — 100% local, zero data transmission"}</sub>
"""


def post_comment(repo: str, pr_number: int, token: str, body: str) -> bool:
    """Post comment to PR."""
    result = github_api_request(
        f"/repos/{repo}/issues/{pr_number}/comments", "POST", token, {"body": body}
    )
    return result is not None


def main() -> int:
    """Main execution flow."""

    # Parse inputs
    baseline_version = get_input("baseline-version", required=True)
    current_version = get_input("current-version", required=True)
    api_key = get_input("driftbase-api-key", default="")
    fail_on_review = get_input("fail-on-review", default="true").lower() == "true"
    fail_on_monitor = get_input("fail-on-monitor", default="false").lower() == "true"
    github_token = get_input("github-token", required=True)
    environment = get_input("environment", default="production")
    sensitivity = get_input("sensitivity", default="standard")

    repository = os.getenv("GITHUB_REPOSITORY")
    if not repository:
        error("GITHUB_REPOSITORY not set")
        return 1

    log(
        f"Comparing {baseline_version} → {current_version} (env: {environment}, sensitivity: {sensitivity})"
    )

    # Get PR number
    pr_number = get_pr_number()
    if pr_number:
        log(f"Running drift check for PR #{pr_number}")
    else:
        log("Not running in PR context - skipping comment posting")

    # Run drift check (cloud or standalone)
    if api_key:
        log("Using CLOUD mode (Driftbase API)")
        diff_data = run_cloud_mode(
            baseline_version, current_version, api_key, environment, sensitivity
        )
    else:
        log("Using STANDALONE mode (local SQLite)")
        diff_data = run_standalone_mode(
            baseline_version, current_version, environment, sensitivity
        )

    # Format comment
    comment_body = format_drift_report(diff_data, baseline_version, current_version)

    # Always print the report for visibility
    print("\n" + "=" * 80)
    print(comment_body)
    print("=" * 80 + "\n")

    # Post comment to PR
    if pr_number:
        delete_previous_comments(repository, pr_number, github_token)

        if post_comment(repository, pr_number, github_token, comment_body):
            log(f"Posted drift report to PR #{pr_number}")
        else:
            error("Failed to post PR comment")

    # Set outputs
    verdict = diff_data.get("verdict", "unknown")
    drift_score = diff_data.get("drift_score", 0.0)

    set_output("verdict", verdict)
    set_output("drift-score", str(drift_score))

    # Handle error cases (never fail on missing data)
    if "error" in diff_data:
        log(f"Drift check skipped: {diff_data.get('message')}")
        set_output("exit-code", "0")
        return 0

    # Determine exit code based on verdict
    verdict_lower = verdict.lower()

    if verdict_lower == "block":
        error(f"Drift check FAILED: verdict is {verdict}")
        set_output("exit-code", "1")
        return 1

    if verdict_lower == "review" and fail_on_review:
        error(f"Drift check FAILED: verdict is {verdict} (fail-on-review=true)")
        set_output("exit-code", "1")
        return 1

    if verdict_lower == "monitor" and fail_on_monitor:
        error(f"Drift check FAILED: verdict is {verdict} (fail-on-monitor=true)")
        set_output("exit-code", "1")
        return 1

    log(f"Drift check passed: verdict is {verdict}")
    set_output("exit-code", "0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
