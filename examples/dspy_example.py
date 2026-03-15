"""
Example: Using DSPyTracer for EU AI Act LM traceability.

This demonstrates how to track DSPy module executions with full model metadata.
"""

from driftbase.integrations import DSPyTracer

# Example with DSPy (requires: pip install dspy-ai)
try:
    import dspy

    # Initialize the tracer (track_optimizer=False by default for GDPR compliance)
    tracer = DSPyTracer(
        version="v1.0",
        agent_id="qa-system",
        track_optimizer=False  # DO NOT track compilation unless explicitly needed
    )

    # Configure DSPy with the tracer
    # Note: Replace with your actual LM configuration
    lm = dspy.LM(model="openai/gpt-4o-mini", api_key="your-key-here")
    dspy.configure(callbacks=[tracer], lm=lm)

    # Define a simple QA module
    class BasicQA(dspy.Module):
        def __init__(self):
            super().__init__()
            self.generate_answer = dspy.Predict("question -> answer")

        def forward(self, question):
            return self.generate_answer(question=question)

    # Create and run the module
    qa_system = BasicQA()

    print("Running DSPy module with tracing enabled...")
    print("=" * 60)

    try:
        result = qa_system(question="What is the capital of France?")
        print(f"\nResult: {result}")
    except Exception as e:
        print(f"Note: This example requires a valid API key. Error: {e}")

    print("\n" + "=" * 60)
    print("Tracking summary:")
    print("=" * 60)
    print(f"  - Modules executed: {len(tracer.module_executions)}")
    print(f"  - Reasoning steps: {len(tracer.reasoning_steps)}")
    print(f"  - Total tokens: {tracer.total_prompt_tokens + tracer.total_completion_tokens}")
    print(f"  - Models used: {set(tracer.model_names)}")
    print(f"  - Errors encountered: {tracer.error_count}")

    # Inspect module executions (EU AI Act compliance data)
    print("\nModule executions (with LM metadata):")
    for i, exec_rec in enumerate(tracer.module_executions, 1):
        print(f"\n  {i}. {exec_rec['module_type']}")
        print(f"     Signature: {exec_rec['signature_string']}")
        print(f"     Input fields: {exec_rec['input_fields']}")
        print(f"     Output fields: {exec_rec['output_fields']}")
        print(f"     LM model: {exec_rec['lm_metadata'].get('model', 'N/A')}")
        print(f"     Tokens: {exec_rec['lm_metadata'].get('total_tokens', 'N/A')}")
        print(f"     Latency: {exec_rec['latency_ms']}ms")

    # The run data is automatically saved to ~/.driftbase/runs.db
    # View it with: driftbase diff v1.0 v1.1

    print("\n" + "=" * 60)
    print("EU AI Act Compliance Note:")
    print("=" * 60)
    print("✓ Exact model string captured (e.g., 'openai/gpt-4o-mini')")
    print("✓ Token counts tracked per module")
    print("✓ Signature strings preserved (documented intent)")
    print("✓ Resolved field schemas logged (actual data structure)")
    print("\nIf a model provider updates weights and causes issues,")
    print("auditors can trace back to the exact model version used.")

    print("\n" + "=" * 60)
    print("GDPR Data Minimization:")
    print("=" * 60)
    print("track_optimizer=False (default)")
    print("  → Only production inference is tracked")
    print("  → Compilation runs are NOT stored")
    print("  → Prevents database bloat and GDPR violations")
    print("\nSet track_optimizer=True ONLY for explicit debugging.")

except ImportError as e:
    print(f"Error: {e}")
    print("\nTo run this example, install DSPy:")
    print("  pip install dspy-ai")
