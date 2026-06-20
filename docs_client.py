import logging

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from models import CompetitorReport, InputRow, SeoContent

logger = logging.getLogger(__name__)


class DocsClient:
    def __init__(self, credentials: Credentials, drive_folder_id: str = ""):
        self._docs = build("docs", "v1", credentials=credentials)
        self._drive = build("drive", "v3", credentials=credentials)
        self._folder_id = drive_folder_id.strip()

    def create_report(
        self,
        row: InputRow,
        competitors: list[CompetitorReport],
        seo: SeoContent,
        notes: list[str] ) -> str:
        
        """Create the doc, fill it, share as commenter, return the shareable URL."""
        title = f"{row.keyword}-{row.geo}"
        doc = self._docs.documents().create(body={"title": title}).execute()
        doc_id = doc["documentId"]

        if self._folder_id:
            self._move_to_folder(doc_id)

        text, requests = self._build_body(row, competitors, seo, notes)
        self._docs.documents().batchUpdate(
            documentId=doc_id, body={"requests": requests}
        ).execute()

        self._share_as_commenter(doc_id)
        url = f"https://docs.google.com/document/d/{doc_id}/edit"
        logger.info("Created doc %s", url)
        return url

    def _move_to_folder(self, doc_id: str) -> None:
        meta = self._drive.files().get(fileId=doc_id, fields="parents").execute()
        prev = ",".join(meta.get("parents", []))
        self._drive.files().update(
            fileId=doc_id,
            addParents=self._folder_id,
            removeParents=prev,
            fields="id, parents",
        ).execute()

    def _share_as_commenter(self, doc_id: str) -> None:
        self._drive.permissions().create(
            fileId=doc_id,
            body={"type": "anyone", "role": "commenter"},
            fields="id",
        ).execute()

    def _build_body(
        self,
        row: InputRow,
        competitors: list[CompetitorReport],
        seo: SeoContent,
        notes: list[str]) -> tuple[str, list[dict]]:
        
        segments: list[tuple[str, str | None]] = []

        segments.append((f"Analysis for {row.keyword} - {row.geo}\n", "HEADING_1"))
        segments.append(("\nCompetitor Reports\n", "HEADING_2"))

        if not competitors:
            segments.append(("No competitor sites could be collected.\n", None))
        for i, c in enumerate(competitors, 1):
            segments.append((f"\n{i}. {c.domain}\n", "HEADING_3"))
            if c.success:
                body = (
                    f"Link: {c.link}\n"
                    f"Position: {c.position}\n"
                    f"H1: {c.h1}\n"
                    f"Meta Title: {c.meta_title}\n"
                    f"Meta Description: {c.meta_description}\n"
                    f"Site structure:\n"
                    + ("".join(f"  - {s}\n" for s in c.structure) or "  - (none found)\n")
                )
            else:
                body = (
                    f"Link: {c.link}\n"
                    f"Position: {c.position}\n"
                    f"FAILED: {c.failure_reason}\n"
                )
            segments.append((body, None))

        if notes:
            segments.append(("\nNotes\n", "HEADING_2"))
            segments.append(("".join(f"- {n}\n" for n in notes), None))

        segments.append(("\nOptimized SEO Content\n", "HEADING_2"))
        segments.append(
            (
                f"H1: {seo.h1}\n"
                f"Meta Title: {seo.meta_title}\n"
                f"Meta Description: {seo.meta_description}\n",
                None,
            )
        )

        full_text = "".join(s[0] for s in segments)
        requests: list[dict] = [
            {"insertText": {"location": {"index": 1}, "text": full_text}}
        ]

        cursor = 1
        for text, style in segments:
            if style:
                requests.append(
                    {
                        "updateParagraphStyle": {
                            "range": {"startIndex": cursor, "endIndex": cursor + len(text)},
                            "paragraphStyle": {"namedStyleType": style},
                            "fields": "namedStyleType",
                        }
                    }
                )
            cursor += len(text)
        return full_text, requests