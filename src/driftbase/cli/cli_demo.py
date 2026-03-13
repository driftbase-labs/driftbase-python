import time
import random
import json
from datetime import datetime, timedelta
import click
from driftbase.cli._deps import safe_import_rich
from driftbase.local.local_store import enqueue_run

# Lazy import of heavy [analyze] dependencies
Console, Panel, Table = safe_import_rich()

def generate_synthetic_runs(version: str, count: int, is_regression: bool):
    """Generates synthetic telemetry data."""
    now = datetime.utcnow()
    
    for i in range(count):
        # Time distribution over the last hour
        run_time = now - timedelta(minutes=random.randint(1, 60))
        
        prompt_text = "Find the latest transaction for user ID 8472 and summarize the status."
        
        if not is_regression:
            # v1.0: Fast, cheap, highly resolved
            p_tokens = random.randint(400, 600)
            c_tokens = random.randint(100, 200)
            latency = random.randint(300, 600)
            tools = ["query_database"]
            outcome = "resolved" if random.random() > 0.05 else "escalated"
            output_text = "Transaction TXN-8472 is marked as COMPLETED. Amount: €450.00."
        else:
            # v2.0: Heavy context, hallucinating long answers, higher escalation
            p_tokens = random.randint(800, 1100) # +50% prompt cost
            c_tokens = random.randint(400, 700)  # +200% generation cost
            latency = random.randint(1100, 1800) # +200% latency
            tools = ["query_database", "web_search", "web_search"] # Agent got confused
            outcome = "escalated" if random.random() > 0.60 else "resolved" # Huge failure spike
            output_text = "I searched the database and the web. The user 8472 might be related to a historical event in 8472 BC. Also, I cannot verify the transaction status right now. Please contact support."

        payload = {
            "session_id": f"demo_session_{version}_{i}",
            "deployment_version": version,
            "environment": "production",
            "started_at": run_time,
            "completed_at": run_time + timedelta(milliseconds=latency),
            "task_input_hash": f"hash_{random.randint(1000,9999)}",
            "tool_sequence": json.dumps(tools),
            "tool_call_count": len(tools),
            "output_length": c_tokens * 4,
            "output_structure_hash": "struct_hash_demo",
            "latency_ms": latency,
            "error_count": 0,
            "retry_count": 0,
            "semantic_cluster": outcome,
            "prompt_tokens": p_tokens,
            "completion_tokens": c_tokens,
            "raw_prompt": prompt_text,
            "raw_output": output_text,
        }
        enqueue_run(payload)

@click.command("demo")
@click.pass_context
def cmd_demo(ctx: click.Context) -> None:
    """Inject synthetic runs to instantly see the drift engine in action."""
    console: Console = ctx.obj["console"]
    
    console.print("🧪 [bold cyan]Injecting synthetic telemetry...[/]")
    
    # 1. Generate Baseline
    generate_synthetic_runs("v1.0", 50, is_regression=False)
    console.print("  └─ Generated 50 runs for [bold]v1.0[/] (Baseline)")
    
    # 2. Generate Regression
    generate_synthetic_runs("v2.0", 50, is_regression=True)
    console.print("  └─ Generated 50 runs for [bold]v2.0[/] (Regression)")
    
    # Allow background SQLite thread to flush
    time.sleep(1.0) 
    
    console.print("\n[bold green]Success![/] Local database populated.")
    console.print("Run this command to see the financial and behavioral insights:\n")
    console.print("👉 [bold]driftbase diff v1.0 v2.0[/]\n")