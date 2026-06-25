import logging
from urllib.parse import urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config import SERP_TOP_N
from llm_client import GeminiClient
from models import SerpResult

logger = logging.getLogger(__name__)

SERPER_ENDPOINT = "https://google.serper.dev/search"


def _domain(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


class SerpClient:
    def __init__(self, api_key: str, llm: GeminiClient | None = None):
        self._api_key = api_key
        self._llm = llm
        self._review_word_cache: dict[str, str] = {}

    def search(self, keyword: str, geo: str, language: str = "en") -> list[SerpResult]:
        # Raw keyword + a localized "casino review" query so genuine review sites
        # surface in the target language (e.g. "aviator casino avis" for fr),
        # instead of movies/clones that dominate a bare brand query.
        review_word = self._review_word(language)
        base = keyword if "casino" in keyword.lower() else f"{keyword} casino"
        queries = [keyword, f"{base} {review_word}"]

        result_lists = [self._search_once(q, geo) for q in queries]

        merged: list[SerpResult] = []
        seen_domains: set[str] = set()
        for tier in range(max((len(lst) for lst in result_lists), default=0)):
            for lst in result_lists:
                if tier < len(lst):
                    r = lst[tier]
                    if r.domain not in seen_domains:
                        seen_domains.add(r.domain)
                        merged.append(r)

        merged = merged[:SERP_TOP_N]
        for i, r in enumerate(merged, 1):
            r.position = i

        logger.info(
            "Merged SERP: %d unique result(s) from %d quer(ies)", len(merged), len(queries)
        )
        return merged

    def _review_word(self, language: str) -> str:
        lang = language.lower().strip()
        if not lang or lang in ("en", "english"):
            return "review"
        if lang in self._review_word_cache:
            return self._review_word_cache[lang]
        if not self._llm:
            return "review"

        prompt = (
            f'Translate the single word "review" (as used in "casino review") '
            f'into the language "{language}". Reply with ONLY that one word, nothing else.'
        )
        try:
            word = self._llm.generate(prompt, max_tokens=20).strip().split()[0].strip('".,')
            word = word or "review"
        except Exception as exc:
            logger.warning("Review-word translation failed for %r (%s); using 'review'", language, exc)
            word = "review"
        self._review_word_cache[lang] = word
        logger.info("Localized review word for %r -> %r", language, word)
        return word

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _search_once(self, query: str, geo: str) -> list[SerpResult]:
        """Fetch the top-N organic results for a single query, localized to `geo`."""
        payload = {"q": query, "gl": geo.lower(), "num": SERP_TOP_N}
        headers = {"X-API-KEY": self._api_key, "Content-Type": "application/json"}

        logger.info("SERP query: %r (gl=%s)", query, geo)
        with httpx.Client(timeout=30) as client:
            resp = client.post(SERPER_ENDPOINT, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        results: list[SerpResult] = []
        for item in data.get("organic", [])[:SERP_TOP_N]:
            link = item.get("link", "")
            if not link:
                continue
            results.append(
                SerpResult(
                    position=item.get("position", len(results) + 1),
                    title=item.get("title", ""),
                    link=link,
                    snippet=item.get("snippet", ""),
                    domain=_domain(link),
                )
            )
        logger.info("  -> %d organic result(s)", len(results))
        return results