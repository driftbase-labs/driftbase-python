import logging
from functools import wraps
from driftbase.sdk.track import track

logger = logging.getLogger(__name__)

def instrument_openai(version: str = "auto"):
    """
    Globally patches the OpenAI client.
    One line of code instruments the entire application.
    """
    try:
        import openai
    except ImportError:
        logger.warning("[Driftbase] OpenAI package not found. Skipping auto-instrumentation.")
        return

    try:
        # Target the synchronous chat completions create method
        original_create = openai.resources.chat.completions.Completions.create
    except AttributeError:
        logger.warning("[Driftbase] Incompatible OpenAI version. Skipping instrumentation.")
        return

    # Wrap it using your existing track decorator
    @wraps(original_create)
    @track(version=version)
    def patched_create(*args, **kwargs):
        return original_create(*args, **kwargs)

    # Apply the patch globally
    openai.resources.chat.completions.Completions.create = patched_create
    logger.info("[Driftbase] OpenAI client successfully instrumented.")