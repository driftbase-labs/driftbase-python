"""
Example: Using LlamaIndexTracer for RAG and agentic workflows.

This demonstrates how to track LlamaIndex executions with comprehensive event capture.
"""

from driftbase.integrations import LlamaIndexTracer

# Example with LlamaIndex (requires: pip install llama-index)
try:
    from llama_index.core import Document, VectorStoreIndex
    from llama_index.core.settings import Settings

    # Initialize the tracer
    tracer = LlamaIndexTracer(version="v1.0", agent_id="rag-engine")

    # Add the tracer to LlamaIndex's callback manager
    Settings.callback_manager.add_handler(tracer)

    print("Creating sample documents...")
    # Create sample documents (in production, use SimpleDirectoryReader)
    documents = [
        Document(
            text="LlamaIndex is a data framework for LLM applications. It provides tools for ingesting, structuring, and accessing private or domain-specific data.",
            metadata={"source": "llamaindex_intro.txt", "category": "overview"},
        ),
        Document(
            text="LlamaIndex supports various data sources including APIs, PDFs, SQL databases, and vector stores. It provides a unified interface for data ingestion.",
            metadata={"source": "llamaindex_data.txt", "category": "features"},
        ),
        Document(
            text="Query engines in LlamaIndex enable natural language querying over your indexed data. They combine retrieval and synthesis for accurate answers.",
            metadata={"source": "llamaindex_query.txt", "category": "usage"},
        ),
    ]

    print("Building index...")
    # Create an index from the documents
    # Note: This requires an OpenAI API key set in environment or via Settings.llm
    index = VectorStoreIndex.from_documents(documents)

    # Create a query engine
    query_engine = index.as_query_engine()

    print("\nRunning query with tracing enabled...")
    print("=" * 60)

    # Run a query - the tracer will automatically capture:
    # - Query events (user query)
    # - Embedding events (query vectorization)
    # - Retrieval events (documents retrieved from index)
    # - LLM events (response generation with token usage)
    # - Synthesis events (combining retrieved context)
    try:
        response = query_engine.query("What is LlamaIndex and what does it support?")
        print(f"\nResponse: {response}")
    except Exception as e:
        print(f"Note: This example requires an OpenAI API key. Error: {e}")

    print("\n" + "=" * 60)
    print("Tracking summary:")
    print("=" * 60)
    print(f"  - Events captured: {len(tracer.events)}")
    print(f"  - Queries: {len(tracer.queries)}")
    print(f"  - Retrieved nodes: {len(tracer.retrieved_nodes)}")
    print(f"  - LLM calls: {tracer.llm_calls}")
    print(
        f"  - Total tokens: {tracer.total_prompt_tokens + tracer.total_completion_tokens}"
    )
    print(f"  - Tool sequence: {tracer.tool_sequence}")

    # Inspect events
    print("\nEvent breakdown:")
    for i, event in enumerate(tracer.events[:10], 1):  # Show first 10
        print(f"  {i}. {event['event_type']} ({event['latency_ms']}ms)")
        if event["metadata"]:
            for key, value in list(event["metadata"].items())[:3]:
                print(f"      {key}: {value}")

    # Inspect retrieved nodes (GDPR-compliant - content hashed)
    if tracer.retrieved_nodes:
        print("\nRetrieved nodes (hashed):")
        for i, node in enumerate(tracer.retrieved_nodes[:5], 1):  # Show first 5
            print(f"  {i}. Hash: {node['content_hash'][:16]}...")
            print(f"      Source: {node['metadata'].get('source', 'unknown')}")
            print(f"      Score: {node['score']}")
            print(f"      Length: {node['content_length']} chars")

    # The run data is automatically saved to ~/.driftbase/runs.db
    # View it with: driftbase diff v1.0 v1.1

    print("\n" + "=" * 60)
    print("Integration Note:")
    print("=" * 60)
    print("✓ Explicit tracer - no magic auto-detection")
    print("✓ Comprehensive event capture (query, retrieve, llm, embed, synthesize)")
    print("✓ Token usage tracking per LLM call")
    print("✓ GDPR-compliant node hashing (content hashed, metadata preserved)")
    print("✓ Full audit trail for RAG workflows")

    print("\nTo use in production:")
    print("  1. Add tracer to Settings.callback_manager.add_handler(tracer)")
    print("  2. Run your LlamaIndex code normally")
    print("  3. Tracer automatically captures all events via callbacks")

except ImportError as e:
    print(f"Error: {e}")
    print("\nTo run this example, install LlamaIndex:")
    print("  pip install llama-index")
