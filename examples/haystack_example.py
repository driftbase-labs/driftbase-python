"""
Example: Using HaystackTracer for GDPR-compliant RAG monitoring.

This demonstrates how to track Haystack pipeline executions with document retrieval auditability.
"""

from driftbase.integrations import HaystackTracer

# Example with Haystack (requires: pip install haystack-ai)
try:
    from haystack import Document, Pipeline
    from haystack.components.builders import PromptBuilder
    from haystack.components.retrievers.in_memory import InMemoryBM25Retriever
    from haystack.document_stores.in_memory import InMemoryDocumentStore
    from haystack.tracing import enable_tracing

    # Create a simple document store with sample documents
    document_store = InMemoryDocumentStore()
    documents = [
        Document(
            content="GDPR requires data controllers to implement appropriate technical and organizational measures.",
            meta={"source": "gdpr_article_32.txt", "article": 32},
        ),
        Document(
            content="Under GDPR Article 17, individuals have the right to erasure (right to be forgotten).",
            meta={"source": "gdpr_article_17.txt", "article": 17},
        ),
        Document(
            content="GDPR Article 15 grants individuals the right to access their personal data.",
            meta={"source": "gdpr_article_15.txt", "article": 15},
        ),
    ]
    document_store.write_documents(documents)

    # Initialize the tracer (GDPR-safe: hashes document content by default)
    tracer = HaystackTracer(
        version="v1.0",
        agent_id="gdpr-rag-pipeline",
        record_full_text=False,  # Default: hash content, store metadata only
    )

    # Enable tracing BEFORE building the pipeline
    enable_tracing(tracer)

    # Build a simple RAG pipeline
    pipeline = Pipeline()
    pipeline.add_component(
        "retriever", InMemoryBM25Retriever(document_store=document_store)
    )
    pipeline.add_component(
        "prompt_builder",
        PromptBuilder(
            template="""
            Given these documents:
            {% for doc in documents %}
                {{ doc.content }}
            {% endfor %}

            Answer the question: {{ query }}
            """
        ),
    )

    # Connect components
    pipeline.connect("retriever.documents", "prompt_builder.documents")

    # Run the pipeline - the tracer automatically captures:
    # - Component execution sequence
    # - Retrieved document metadata (hashed content)
    # - Filters applied
    # - Latency per component
    result = pipeline.run(
        {
            "retriever": {
                "query": "What are the technical measures required by GDPR?",
                "top_k": 2,
            },
            "prompt_builder": {
                "query": "What are the technical measures required by GDPR?"
            },
        }
    )

    print(f"Pipeline result: {result}")
    print("\nTracking summary:")
    print(f"  - Components executed: {len(tracer.component_sequence)}")
    print(f"  - Documents retrieved: {len(tracer.retrieved_chunks)}")
    print(f"  - Errors encountered: {tracer.error_count}")
    print(f"  - Tool sequence: {tracer.tool_sequence}")

    # Inspect retrieved documents (GDPR-compliant metadata)
    print("\nRetrieved documents (hashed):")
    for i, chunk in enumerate(tracer.retrieved_chunks, 1):
        print(f"  {i}. Hash: {chunk['content_hash'][:16]}...")
        print(f"     Source: {chunk['metadata'].get('source', 'unknown')}")
        print(f"     Score: {chunk['score']}")
        print(f"     Length: {chunk['content_length']} chars")

    # The run data is automatically saved to ~/.driftbase/runs.db
    # View it with: driftbase diff v1.0 v1.1

    print("\n" + "=" * 60)
    print("GDPR Compliance Note:")
    print("=" * 60)
    print("Document content is SHA256-hashed by default.")
    print("Raw text is NOT stored to avoid GDPR liability.")
    print("To verify content integrity, hash the source file and match.")
    print("\nTo store full text (GDPR risk), set record_full_text=True")

except ImportError as e:
    print(f"Error: {e}")
    print("\nTo run this example, install Haystack:")
    print("  pip install haystack-ai")
