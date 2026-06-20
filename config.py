import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


@dataclass(frozen=True)
class Settings:
    # Google (user OAuth)
    credentials_file: str = field(
        default_factory=lambda: os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json").strip()
    )
    token_file: str = field(
        default_factory=lambda: os.getenv("GOOGLE_TOKEN_FILE", "token.json").strip()
    )
    spreadsheet_url: str = field(default_factory=lambda: _require("SPREADSHEET_URL"))
    worksheet_name: str = field(
        default_factory=lambda: os.getenv("WORKSHEET_NAME", "Sheet1").strip()
    )
    drive_folder_id: str = field(
        default_factory=lambda: os.getenv("DRIVE_FOLDER_ID", "").strip()
    )

    # SERP
    serper_api_key: str = field(default_factory=lambda: _require("SERPER_API_KEY"))

    # Gemini
    gemini_api_key: str = field(default_factory=lambda: _require("GEMINI_API_KEY"))
    gemini_model: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    )


GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]


STOP_WORDS = ["Discover", "Thrilling", "Enjoy", "Excitement", "Dive into", "Experience"]

TITLE_MIN_LEN = 40
TITLE_MAX_LEN = 60
DESCRIPTION_MAX_LEN = 160

TARGET_AFFILIATE_COUNT = 3
SERP_TOP_N = 10