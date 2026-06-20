import logging
import re
import time

from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

_MAX_RATE_RETRIES = 5
_DEFAULT_RATE_WAIT = 30


class GeminiClient:
    def __init__(self, api_key: str, model: str):
        self._client = genai.Client(api_key=api_key)
        self._model = model

    def generate(self, prompt: str, system: str | None = None, max_tokens: int = 1024) -> str:
        for attempt in range(_MAX_RATE_RETRIES + 1):
            try:
                return self._generate_once(prompt, system, max_tokens)
            except ClientError as exc:
                if exc.code == 429 and _is_per_minute(exc) and attempt < _MAX_RATE_RETRIES:
                    wait = _retry_delay(exc)
                    logger.warning(
                        "Gemini per-minute rate limit hit; waiting %ss (retry %d/%d)",
                        wait, attempt + 1, _MAX_RATE_RETRIES,
                    )
                    time.sleep(wait)
                    continue
                raise
        raise RuntimeError("Exhausted rate-limit retries")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(ServerError),
    )
    def _generate_once(self, prompt: str, system: str | None, max_tokens: int) -> str:
        config = types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=0.7,
            system_instruction=system,
        )
        resp = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=config,
        )
        text = (resp.text or "").strip()
        if not text:
            raise RuntimeError("Gemini returned an empty response")
        return text


def _is_per_minute(exc: ClientError) -> bool:
    msg = str(exc)
    if "PerDay" in msg:
        return False
    return "PerMinute" in msg


def _retry_delay(exc: ClientError) -> int:
    """Pull the suggested retry delay (seconds) from the error, else a default."""
    m = re.search(r"retry in ([\d.]+)s", str(exc)) or re.search(r"retryDelay'?:?\s*'?(\d+)s", str(exc))
    if m:
        return int(float(m.group(1))) + 2  # small safety margin
    return _DEFAULT_RATE_WAIT
