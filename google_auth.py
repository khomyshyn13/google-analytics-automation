import logging
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

logger = logging.getLogger(__name__)


def get_user_credentials(credentials_file: str, token_file: str, scopes: list[str]) -> Credentials:
    """Return valid user credentials, prompting the browser only when needed."""
    creds: Credentials | None = None

    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, scopes)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing cached OAuth token")
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_file):
                raise RuntimeError(
                    f"OAuth client file not found: {credentials_file}. "
                    f"Create an OAuth client ID (Desktop app) in Google Cloud and "
                    f"save it as this file."
                )
            logger.info("Opening browser for one-time Google authorization…")
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, scopes)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as fh:
            fh.write(creds.to_json())
        logger.info("Saved OAuth token to %s", token_file)

    return creds