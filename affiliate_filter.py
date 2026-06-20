import json
import logging

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

_CLASSIFY_PROMPT = """You are classifying Google search results for the query "{keyword}".

Goal: find third-party AFFILIATE / REVIEW sites about casinos/bookmakers
(portals that review, compare, rank or promote operators to earn referral).

Classify each result. Mark is_affiliate_review = FALSE only for:
- the ONE official website of the operator itself. The official site is the
  short, canonical brand domain (e.g. "brand.com"). Domains that contain the
  brand name PLUS extra words or geo (e.g. "brand-india.in", "brand-review.com",
  "brand-bonus.net", "brandbookmaker.com") are almost always AFFILIATES, not the
  official site -> mark them TRUE.
- news/media outlets, forums, social media, app stores, regulators, Wikipedia,
  and generic consumer-review platforms (e.g. trustpilot.com).

Everything else that is casino/bookmaker related -> is_affiliate_review = TRUE.

Return ONLY a JSON array, one object per result, in the SAME order:
[{{"position": <int>, "is_affiliate_review": <true|false>, "reason": "<short>"}}]

Results:
{results}
"""


class AffiliateFilter:
    def __init__(self, client: GeminiClient):
        self._client = client

    def select(
        self, results: list[SerpResult], keyword: str, target: int) -> tuple[list[SerpResult], list[str]]:
        """Return up to `target` affiliate sites + notes about what was skipped.

        Never goes beyond the provided list (caller passes only top-10)."""
        notes: list[str] = []
        candidates = [r for r in results if not self._hard_excluded(r, notes)]
        if not candidates:
            return [], notes

        verdicts = self._classify(candidates, keyword)
        selected: list[SerpResult] = []
        seen_domains: set[str] = set()
        fallback_pool: list[SerpResult] = []
        for r in candidates:
            v = verdicts.get(r.position) or {}
            reason = v.get("reason", "not an affiliate review site")
            if v.get("is_affiliate_review") and r.domain not in seen_domains:
                selected.append(r)
                seen_domains.add(r.domain)
                if len(selected) == target:
                    break
            else:
                notes.append(f"pos {r.position} ({r.domain}) skipped: {reason}")
                if "official" not in reason.lower() and r.domain not in seen_domains:
                    fallback_pool.append(r)

        if len(selected) < target:
            for r in fallback_pool:
                if len(selected) >= target:
                    break
                if r.domain in seen_domains:
                    continue
                selected.append(r)
                seen_domains.add(r.domain)
                notes.append(
                    f"pos {r.position} ({r.domain}) included as fallback competitor "
                    f"(no clear affiliate site found in top-{len(results)})."
                )

        if len(selected) < target:
            notes.append(
                f"Only {len(selected)} competitor site(s) available within "
                f"top-{len(results)} (no affiliate sites in the SERP)."
            )
        return selected, notes

    def _hard_excluded(self, r: SerpResult, notes: list[str]) -> bool:
        if any(bad in r.domain for bad in _HARD_EXCLUDE):
            notes.append(f"pos {r.position} ({r.domain}) skipped: non-affiliate domain")
            return True
        return False

    def _classify(self, results: list[SerpResult], keyword: str) -> dict[int, dict]:
        lines = [
            f'{{"position": {r.position}, "domain": "{r.domain}", '
            f'"title": {json.dumps(r.title)}, "snippet": {json.dumps(r.snippet)}}}'
            for r in results
        ]
        prompt = _CLASSIFY_PROMPT.format(keyword=keyword, results="\n".join(lines))

        text = self._client.generate(prompt, max_tokens=1024)
        try:
            parsed = json.loads(_extract_json(text))
            return {int(item["position"]): item for item in parsed}
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("Classifier parse failed (%s); treating all as affiliate", exc)
            return {r.position: {"is_affiliate_review": True} for r in results}


def _extract_json(text: str) -> str:
    """Pull the first JSON array out of a possibly fenced model response."""
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text