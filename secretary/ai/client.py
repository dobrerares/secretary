"""LiteLLM wrapper with retry and timeout handling."""

import logging

import litellm

logger = logging.getLogger(__name__)

# Suppress litellm's verbose logging
litellm.suppress_debug_info = True


class LLMClient:
    """Thin async wrapper around litellm.acompletion."""

    def __init__(self, model: str, api_key: str) -> None:
        self.model = model
        self.api_key = api_key

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> dict:
        """Call the LLM and return the response dict.

        Retries up to 2 times on transient errors. Timeout is 30 seconds.
        """
        last_exc: Exception | None = None
        max_attempts = 3  # initial + 2 retries

        for attempt in range(max_attempts):
            try:
                kwargs: dict = {
                    "model": self.model,
                    "api_key": self.api_key,
                    "messages": messages,
                    "timeout": 30,
                }
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"

                response = await litellm.acompletion(**kwargs)
                return response.model_dump()

            except (litellm.exceptions.RateLimitError, litellm.exceptions.ServiceUnavailableError) as exc:
                last_exc = exc
                logger.warning("LLM transient error (attempt %d/%d): %s", attempt + 1, max_attempts, exc)
                continue
            except litellm.exceptions.Timeout as exc:
                last_exc = exc
                logger.warning("LLM timeout (attempt %d/%d): %s", attempt + 1, max_attempts, exc)
                continue
            except Exception as exc:
                # Non-retryable errors (auth, bad request, etc.)
                logger.error("LLM non-retryable error: %s", exc)
                raise

        # All retries exhausted
        logger.error("LLM call failed after %d attempts", max_attempts)
        raise last_exc  # type: ignore[misc]
