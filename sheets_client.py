import logging

import gspread
from google.oauth2.credentials import Credentials

from models import InputRow

logger = logging.getLogger(__name__)

COL_KEYWORD = "keyword"
COL_GEO = "geo"
COL_LANGUAGE = "language"
COL_RESULT = "result"


class SheetsClient:
    def __init__(self, credentials: Credentials, spreadsheet_url: str, worksheet_name: str):
        self._gc = gspread.authorize(credentials)
        self._sheet = self._gc.open_by_url(spreadsheet_url)
        self._ws = self._sheet.worksheet(worksheet_name)
        self._col_index = self._map_columns()

    def _map_columns(self) -> dict[str, int]:
        header = [h.strip().lower() for h in self._ws.row_values(1)]
        required = {COL_KEYWORD, COL_GEO, COL_LANGUAGE, COL_RESULT}
        index = {name: i + 1 for i, name in enumerate(header)}
        missing = required - set(index)
        if missing:
            raise RuntimeError(
                f"Spreadsheet is missing required columns: {sorted(missing)}. "
                f"Found: {header}"
            )
        return index

    def read_pending_rows(self, only_empty_result: bool = True) -> list[InputRow]:
        """Return data rows. By default only those with an empty Result cell."""
        records = self._ws.get_all_records()
        rows: list[InputRow] = []
        for offset, rec in enumerate(records):
            lower = {str(k).strip().lower(): v for k, v in rec.items()}
            keyword = str(lower.get(COL_KEYWORD, "")).strip()
            if not keyword:
                continue
            result = str(lower.get(COL_RESULT, "")).strip()
            if only_empty_result and result:
                continue
            rows.append(
                InputRow(
                    row_number=offset + 2,
                    keyword=keyword,
                    geo=str(lower.get(COL_GEO, "")).strip(),
                    language=str(lower.get(COL_LANGUAGE, "")).strip(),
                    result=result,
                )
            )
        logger.info("Read %d pending row(s) from sheet", len(rows))
        return rows

    def write_result(self, row_number: int, doc_url: str) -> None:
        """Write the Google Doc URL into the Result column for a given row."""
        self._ws.update_cell(row_number, self._col_index[COL_RESULT], doc_url)
        logger.info("Wrote result for row %d", row_number)