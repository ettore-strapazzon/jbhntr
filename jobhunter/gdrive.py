"""Google auth + Drive helpers (shared by the generator and the sheet writer).

Uses a service account. The SA creates Google Docs in your configured Drive
folder and shares each with your own email so you can open the links. No public
'anyone with link' sharing is used.
"""

from __future__ import annotations

import io
import logging
from functools import lru_cache
from typing import Optional

from google.oauth2.service_account import Credentials

from .config import Settings

log = logging.getLogger("jobhunter.gdrive")

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]


@lru_cache(maxsize=1)
def credentials(sa_file: str) -> Credentials:
    return Credentials.from_service_account_file(sa_file, scopes=SCOPES)


class Drive:
    """Thin wrapper around the Drive v3 API for creating shareable Google Docs."""

    def __init__(self, settings: Settings):
        from googleapiclient.discovery import build

        self.settings = settings
        creds = credentials(str(settings.service_account_path()))
        self.service = build("drive", "v3", credentials=creds, cache_discovery=False)

    def create_doc(self, title: str, text: str) -> str:
        """Create a Google Doc from plain text and return its web link."""
        from googleapiclient.http import MediaIoBaseUpload

        metadata = {
            "name": title,
            "mimeType": "application/vnd.google-apps.document",
        }
        if self.settings.google_drive_folder_id:
            metadata["parents"] = [self.settings.google_drive_folder_id]

        media = MediaIoBaseUpload(
            io.BytesIO(text.encode("utf-8")),
            mimetype="text/plain",
            resumable=False,
        )
        try:
            file = (
                self.service.files()
                .create(body=metadata, media_body=media, fields="id, webViewLink")
                .execute()
            )
        except Exception as exc:
            log.warning("Drive doc creation failed for %r: %s", title, exc)
            return ""

        file_id = file.get("id")
        self._share_with_user(file_id)
        return file.get("webViewLink", "")

    def _share_with_user(self, file_id: str) -> None:
        email = self.settings.email_to
        if not (file_id and email):
            return
        try:
            self.service.permissions().create(
                fileId=file_id,
                body={"type": "user", "role": "reader", "emailAddress": email},
                sendNotificationEmail=False,
                fields="id",
            ).execute()
        except Exception as exc:
            log.warning("Could not share doc %s with %s: %s", file_id, email, exc)
