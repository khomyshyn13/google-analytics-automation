import argparse
import logging
import sys

from affiliate_filter import AffiliateFilter
from ai_generator import AiGenerator
from config import GOOGLE_SCOPES, SERP_TOP_N, TARGET_AFFILIATE_COUNT, Settings
from docs_client import DocsClient
from google_auth import get_user_credentials
from llm_client import GeminiClient
from models import InputRow, RowOutcome
from scraper import scrape_competitor
from serp_client import SerpClient
from sheets_client import SheetsClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


class Pipeline:
    def __init__(self, settings: Settings):
        self.settings = settings
        creds = get_user_credentials(
            settings.credentials_file, settings.token_file, GOOGLE_SCOPES
        )
        llm = GeminiClient(settings.gemini_api_key, settings.gemini_model)
        self.sheets = SheetsClient(
            creds,
            settings.spreadsheet_url,
            settings.worksheet_name,
        )
        self.serp = SerpClient(settings.serper_api_key)
        self.filter = AffiliateFilter(llm)
        self.generator = AiGenerator(llm)
        self.docs = DocsClient(creds, settings.drive_folder_id)

    def process_row(self, row: InputRow) -> RowOutcome:
        outcome = RowOutcome(row=row)
        logger.info("=== Row %d: %r | %s | %s ===", row.row_number, row.keyword, row.geo, row.language)

        # SERP (top-10)
        serp_results = self.serp.search(row.keyword, row.geo)[:SERP_TOP_N]
        if not serp_results:
            outcome.error = "SERP returned no results"
            return outcome

        # Pick up to 3 affiliate review sites from the top-10
        selected, notes = self.filter.select(
            serp_results, row.keyword, TARGET_AFFILIATE_COUNT
        )
        outcome.notes.extend(notes)

        # Scrape each selected site (fault tolerant)
        for result in selected:
            outcome.competitors.append(scrape_competitor(result))

        ok = sum(1 for c in outcome.competitors if c.success)
        logger.info("Scraped %d/%d competitor(s) successfully", ok, len(selected))

        # Generate optimized meta
        outcome.seo = self.generator.generate(
            row.keyword, row.geo, row.language, outcome.competitors
        )

        # Create the Google Doc and share as commenter
        outcome.doc_url = self.docs.create_report(
            row, outcome.competitors, outcome.seo, outcome.notes
        )

        # Write the doc URL back to the sheet
        self.sheets.write_result(row.row_number, outcome.doc_url)
        return outcome

    def run(self, only_empty: bool) -> int:
        rows = self.sheets.read_pending_rows(only_empty_result=only_empty)
        if not rows:
            logger.info("Nothing to process.")
            return 0

        failures = 0
        for row in rows:
            try:
                outcome = self.process_row(row)
                if outcome.error:
                    failures += 1
                    logger.error("Row %d failed: %s", row.row_number, outcome.error)
                else:
                    logger.info("Row %d done -> %s", row.row_number, outcome.doc_url)
            except Exception as exc:  # noqa: BLE001 - isolate per-row failures
                failures += 1
                logger.exception("Row %d crashed: %s", row.row_number, exc)
        logger.info("Finished. %d/%d row(s) failed.", failures, len(rows))
        return failures


def main():
    parser = argparse.ArgumentParser(description="SEO meta automation pipeline")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process every row, even those that already have a Result URL.",
    )
    args = parser.parse_args()

    try:
        settings = Settings()
    except RuntimeError as exc:
        logger.error(str(exc))
        sys.exit(2)

    pipeline = Pipeline(settings)
    failures = pipeline.run(only_empty=not args.all)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()