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

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def search(self, keyword: str, geo: str) -> list[SerpResult]:
        payload = {"q": keyword, "gl": geo.lower(), "num": SERP_TOP_N}
        headers = {"X-API-KEY": self._api_key, "Content-Type": "application/json"}

        logger.info("SERP query: %r (gl=%s)", keyword, geo)
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
        logger.info("SERP returned %d organic results", len(results))
        return results