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


def scrape_competitor(result: SerpResult) -> CompetitorReport:
    report = CompetitorReport(
        link=result.link, position=result.position, domain=result.domain
    )
    try:
        with httpx.Client(
            timeout=20, follow_redirects=True, headers=_HEADERS
        ) as client:
            resp = client.get(result.link)
            resp.raise_for_status()
            html = resp.text
    except httpx.HTTPStatusError as exc:
        report.success = False
        report.failure_reason = f"HTTP {exc.response.status_code}"
        logger.warning("Scrape failed %s: %s", result.link, report.failure_reason)
        return report
    except Exception as exc:  # noqa: BLE001 - any network error -> reported, not fatal
        report.success = False
        report.failure_reason = f"{type(exc).__name__}: {exc}"
        logger.warning("Scrape failed %s: %s", result.link, report.failure_reason)
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