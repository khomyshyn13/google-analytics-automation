from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SerpResult:
    position: int
    title: str
    link: str
    snippet: str
    domain: str


@dataclass
class CompetitorReport:
    link: str
    position: int
    domain: str
    h1: str = ""
    meta_title: str = ""
    meta_description: str = ""
    structure: list[str] = field(default_factory=list)  # H2/H3 outline
    success: bool = True
    failure_reason: str = ""


@dataclass
class SeoContent:
    h1: str
    meta_title: str
    meta_description: str


@dataclass
class InputRow:
    row_number: int
    keyword: str
    geo: str
    language: str
    result: str = ""


@dataclass
class RowOutcome:
    row: InputRow
    competitors: list[CompetitorReport] = field(default_factory=list)
    seo: Optional[SeoContent] = None
    doc_url: str = ""
    error: str = ""
    notes: list[str] = field(default_factory=list)