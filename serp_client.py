import logging
from urllib.parse import urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config import SERP_TOP_N
from models import SerpResult

logger = logging.getLogger(__name__)

SERPER_ENDPOINT = "https://google.serper.dev/search"


def _domain(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


class SerpClient:
    def __init__(self, api_key: str):
        self._api_key = api_key

    def search(self, keyword: str, geo: str) -> list[SerpResult]:
        queries = [keyword]
        if "casino" not in keyword.lower():
            queries.append(f"{keyword} casino")

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