import logging
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from models import CompetitorReport, SerpResult

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en;q=0.9",
}
_MAX_STRUCTURE_ITEMS = 25
_SCRAPERAPI_ENDPOINT = "https://api.scraperapi.com/"


def scrape_competitor(result: SerpResult, scraper_api_key: str = "") -> CompetitorReport:
    report = CompetitorReport(
        link=result.link, position=result.position, domain=result.domain
    )

    html, reason = _fetch_direct(result.link)
    if html is None and scraper_api_key:
        logger.info("Direct fetch failed (%s); retrying via ScraperAPI: %s", reason, result.link)
        html, proxy_reason = _fetch_via_scraperapi(result.link, scraper_api_key)
        if html is None:
            reason = f"{reason}; proxy: {proxy_reason}"

    if html is None:
        report.success = False
        report.failure_reason = reason
        logger.warning("Scrape failed %s: %s", result.link, reason)
        return report

    try:
        _parse_into(html, report)
    except Exception as exc:  # noqa: BLE001
        report.success = False
        report.failure_reason = f"parse error: {exc}"
        return report

    if not (report.h1 or report.meta_title or report.meta_description):
        report.success = False
        report.failure_reason = "no H1/title/meta found (likely JS-rendered or blocked)"
    return report


def _fetch_direct(url: str) -> tuple[str | None, str]:
    try:
        with httpx.Client(timeout=20, follow_redirects=True, headers=_HEADERS) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text, ""
    except httpx.HTTPStatusError as exc:
        return None, f"HTTP {exc.response.status_code}"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _fetch_via_scraperapi(url: str, api_key: str) -> tuple[str | None, str]:
    params = {"api_key": api_key, "url": url, "render": "true"}
    try:
        with httpx.Client(timeout=70, follow_redirects=True) as client:
            resp = client.get(_SCRAPERAPI_ENDPOINT, params=params)
            resp.raise_for_status()
            return resp.text, ""
    except httpx.HTTPStatusError as exc:
        return None, f"HTTP {exc.response.status_code}"
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def _parse_into(html: str, report: CompetitorReport) -> None:
    soup = BeautifulSoup(html, "html.parser")

    if soup.title and soup.title.string:
        report.meta_title = soup.title.string.strip()

    md = soup.find("meta", attrs={"name": "description"})
    if md and md.get("content"):
        report.meta_description = md["content"].strip()

    h1 = soup.find("h1")
    if h1:
        report.h1 = h1.get_text(strip=True)

    structure: list[str] = []
    for tag in soup.find_all(["h2", "h3"]):
        text = tag.get_text(strip=True)
        if text:
            structure.append(f"{tag.name.upper()}: {text}")
        if len(structure) >= _MAX_STRUCTURE_ITEMS:
            break
    report.structure = structure