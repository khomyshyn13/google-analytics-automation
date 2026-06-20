import json
import logging
import re

from config import (
    DESCRIPTION_MAX_LEN,
    STOP_WORDS,
    TITLE_MAX_LEN,
    TITLE_MIN_LEN,
)
from llm_client import GeminiClient
from models import CompetitorReport, SeoContent

logger = logging.getLogger(__name__)

_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF←-⇿⬀-⯿]"
)

_MAX_ATTEMPTS = 4

_SYSTEM = """You are an expert multilingual SEO copywriter for iGaming/casino sites.
You write meta content that obeys strict mechanical constraints exactly."""

_PROMPT = """Write optimized meta content for this page.

TARGET KEYWORD: {keyword}
GEO: {geo}
OUTPUT LANGUAGE: {language}   (write H1, Meta Title and Meta Description in THIS language)

Competitor meta currently ranking (for inspiration, do NOT copy):
{competitors}

RULES (must all hold):
1. KEYWORD FIRST: H1 and Meta Title MUST begin with the exact keyword "{keyword}".
2. FORBIDDEN: no emojis. Never use these stop words: {stop_words}.
3. ANTI-TEMPLATE: avoid cliches. Emphasise bonuses or payout speed.
4. LIMITS: Meta Title between {title_min} and {title_max} characters.
   Meta Description strictly under {desc_max} characters.
5. CAPITALIZATION: Title Case for every word in the Meta Title;
   sentences in the Meta Description start with a capital letter.

{feedback}
Return ONLY this JSON object, nothing else:
{{"h1": "...", "meta_title": "...", "meta_description": "..."}}
"""


class AiGenerator:
    def __init__(self, client: GeminiClient):
        self._client = client

    def generate(
        self,
        keyword: str,
        geo: str,
        language: str,
        competitors: list[CompetitorReport]) -> SeoContent:
        
        feedback = ""
        last_errors: list[str] = []
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                content = self._call(keyword, geo, language, competitors, feedback)
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                # Model returned malformed/empty JSON — retry instead of crashing.
                last_errors = [f"invalid JSON output: {exc}"]
                logger.warning("AI attempt %d returned invalid JSON: %s", attempt, exc)
                feedback = (
                    "Your previous answer was not valid JSON. Return ONLY a JSON "
                    'object: {"h1": "...", "meta_title": "...", "meta_description": "..."}\n'
                )
                continue
            errors = validate(content, keyword)
            if not errors:
                logger.info("AI meta accepted on attempt %d", attempt)
                return content
            last_errors = errors
            logger.warning("AI attempt %d violated rules: %s", attempt, errors)
            feedback = (
                "Your previous answer broke these rules — fix them precisely:\n"
                + "\n".join(f"- {e}" for e in errors)
                + "\n"
            )
        raise RuntimeError(
            f"AI could not satisfy rules after {_MAX_ATTEMPTS} attempts: {last_errors}"
        )

    def _call(
        self,
        keyword: str,
        geo: str,
        language: str,
        competitors: list[CompetitorReport],
        feedback: str) -> SeoContent:
        
        comp_text = _format_competitors(competitors)
        prompt = _PROMPT.format(
            keyword=keyword,
            geo=geo,
            language=language,
            competitors=comp_text,
            stop_words=", ".join(STOP_WORDS),
            title_min=TITLE_MIN_LEN,
            title_max=TITLE_MAX_LEN,
            desc_max=DESCRIPTION_MAX_LEN,
            feedback=feedback,
        )
        raw = self._client.generate(prompt, system=_SYSTEM, max_tokens=2048, json_mode=True)
        data = json.loads(_extract_json(raw))
        return SeoContent(
            h1=data["h1"].strip(),
            meta_title=data["meta_title"].strip(),
            meta_description=data["meta_description"].strip(),
        )


def validate(content: SeoContent, keyword: str) -> list[str]:
    """Return a list of rule violations (empty == valid)."""
    errors: list[str] = []
    kw = keyword.strip().lower()

    if not content.h1.lower().startswith(kw):
        errors.append(f'H1 must start with the keyword "{keyword}".')
    if not content.meta_title.lower().startswith(kw):
        errors.append(f'Meta Title must start with the keyword "{keyword}".')

    tlen = len(content.meta_title)
    if not (TITLE_MIN_LEN <= tlen <= TITLE_MAX_LEN):
        errors.append(
            f"Meta Title length {tlen} not in {TITLE_MIN_LEN}-{TITLE_MAX_LEN}."
        )
    if len(content.meta_description) >= DESCRIPTION_MAX_LEN:
        errors.append(
            f"Meta Description length {len(content.meta_description)} "
            f"must be < {DESCRIPTION_MAX_LEN}."
        )

    blob = f"{content.h1} {content.meta_title} {content.meta_description}"
    for word in STOP_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", blob, flags=re.IGNORECASE):
            errors.append(f'Forbidden stop word used: "{word}".')
    if _EMOJI_RE.search(blob):
        errors.append("Emoji detected; emojis are forbidden.")

    return errors


def _format_competitors(competitors: list[CompetitorReport]) -> str:
    ok = [c for c in competitors if c.success]
    if not ok:
        return "(no competitor data available)"
    parts = []
    for c in ok:
        parts.append(
            f"- {c.domain} (pos {c.position}): "
            f"H1={c.h1!r}; Title={c.meta_title!r}; Desc={c.meta_description!r}"
        )
    return "\n".join(parts)


def _extract_json(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text