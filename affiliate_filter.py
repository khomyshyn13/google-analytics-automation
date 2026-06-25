import json
import logging

from config import SERP_TOP_N
from llm_client import GeminiClient
from models import SerpResult

logger = logging.getLogger(__name__)

_HARD_EXCLUDE = (
    "wikipedia.org",
    "facebook.com",
    "youtube.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "reddit.com",
    "apps.apple.com",
    "play.google.com",
    "linkedin.com",
    "tiktok.com",
)

_CLASSIFY_PROMPT = """You audit Google results for the query "{keyword}" to find
AFFILIATE CASINO-REVIEW sites.

DEFINITION — an affiliate casino-review site is a THIRD-PARTY website whose
purpose is to review, compare, rate, rank or recommend online casinos/bookmakers
to visitors (earning commission via referral links). Typical signs: words like
"review", "best casinos", "top casino", rating/comparison tables, or bonus guides
that cover MULTIPLE operators.

Mark is_affiliate_review = TRUE ONLY for such third-party review/comparison sites.

Mark is_affiliate_review = FALSE for everything else, including:
- the operator's own official website,
- mirror / clone / landing pages that promote ONE single operator (even if the
  domain contains the brand name, e.g. "brand-india.in", "brandbonus.com") — these
  are not review sites,
- news/media, blogs not focused on casino reviews, forums, social media,
  app stores, regulators, Wikipedia, payment providers,
- generic consumer-review platforms.

When unsure, mark FALSE.

For EACH item return an object: {{"position": <int>, "is_affiliate_review": <true|false>, "reason": "<short>"}}
Return ONLY a JSON array, in the SAME order.

Items:
{results}
"""


class AffiliateFilter:
    def __init__(self, client: GeminiClient):
        self._client = client

    def select(
        self, results: list[SerpResult], keyword: str, target: int) -> tuple[list[SerpResult], list[str]]:
        notes: list[str] = []
        candidates = [r for r in results if not self._hard_excluded(r, notes)]
        if not candidates:
            return [], _dedupe_notes(notes)

        verdicts = self._classify(candidates, keyword)
        selected: list[SerpResult] = []
        for r in candidates:
            v = verdicts.get(r.position) or {}
            if v.get("is_affiliate_review"):
                selected.append(r)
                if len(selected) == target:
                    break
            else:
                reason = v.get("reason", "not a casino-review affiliate site")
                notes.append(f"{r.domain} (pos {r.position}) skipped — {reason}")

        if len(selected) < target:
            notes.append(
                f"Only {len(selected)} affiliate casino-review site(s) found within "
                f"the top-{SERP_TOP_N} (target was {target})."
            )
        return selected, _dedupe_notes(notes)

    def _hard_excluded(self, r: SerpResult, notes: list[str]) -> bool:
        if any(bad in r.domain for bad in _HARD_EXCLUDE):
            notes.append(f"{r.domain} (pos {r.position}) skipped — non-review platform")
            return True
        return False

    def _classify(self, results: list[SerpResult], keyword: str) -> dict[int, dict]:
        lines = [
            f'{{"position": {r.position}, "domain": "{r.domain}", '
            f'"title": {json.dumps(r.title)}, "snippet": {json.dumps(r.snippet)}}}'
            for r in results
        ]
        prompt = _CLASSIFY_PROMPT.format(keyword=keyword, results="\n".join(lines))

        text = self._client.generate(prompt, max_tokens=2048, json_mode=True)
        try:
            parsed = json.loads(_extract_json(text))
            return {int(item["position"]): item for item in parsed}
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("Classifier parse failed (%s); rejecting all candidates", exc)
            return {}


def _dedupe_notes(notes: list[str]) -> list[str]:
    """Drop duplicate note lines while preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for n in notes:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _extract_json(text: str) -> str:
    """Pull the first JSON array out of a possibly fenced model response."""
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text