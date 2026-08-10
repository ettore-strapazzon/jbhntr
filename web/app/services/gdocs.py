"""Create a formatted Google Doc from a tailored CV / cover letter.

Uses the app's Google service account (shared with jobhunter.gdrive): the SA
creates the Doc in a configured Drive folder and shares it with the signed-in
user's Google email as an editor, so they get real WYSIWYG editing and perfect
PDF/DOCX export from Google — no per-user OAuth, no Google verification review.

The formatting is applied with the Docs API (docs v1) batchUpdate: our plain-text
draft's lines are classified (heading / bullet / body) and mapped to Google Docs
paragraph styles + bullets, so the doc looks structured, not like a text dump.

Enabled only when a service account + Drive folder are configured; otherwise
`enabled()` is False and the caller hides the button. Never raises to the caller
on an API error — returns "" and lets the workbench keep working.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("jbhntr.gdocs")

_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]


def _settings():
    from jobhunter.config import Settings
    return Settings.from_env()


def enabled() -> bool:
    """True when a usable service account file + a target Drive folder exist."""
    s = _settings()
    try:
        return bool(s.google_drive_folder_id) and Path(s.service_account_path()).is_file()
    except Exception:
        return False


def _line_style(line: str) -> tuple[str, str]:
    """(kind, cleaned_text) — reuses the export classifier so Docs matches PDF/DOCX."""
    from .export import _line_kind
    kind = _line_kind(line)
    if kind == "bullet":
        return "bullet", line.strip().lstrip("-•*▪◦· ").strip()
    return kind, line.strip() if kind == "heading" else line


def build_doc_requests(title: str, body: str) -> list[dict]:
    """Docs API batchUpdate requests: insert the whole text once, then style each
    line by its computed character range. Built end-to-first so earlier inserts
    never shift a later request's indices.

    Pure and side-effect-free, so the formatting logic is unit-testable without
    touching Google.
    """
    lines: list[tuple[str, str]] = []
    if title:
        lines.append(("title", title))
    for raw in (body or "").split("\n"):
        if not raw.strip():
            lines.append(("blank", ""))
        else:
            lines.append(_line_style(raw))

    # Full document text (each line + newline). Docs starts body content at index 1.
    text = "".join((t + "\n") for _, t in lines)
    requests: list[dict] = [{"insertText": {"location": {"index": 1}, "text": text}}]

    idx = 1
    ranges = []
    for kind, t in lines:
        start = idx
        end = idx + len(t) + 1          # include the trailing newline
        ranges.append((kind, start, end))
        idx = end

    for kind, start, end in ranges:
        if kind == "title":
            requests.append({"updateParagraphStyle": {
                "range": {"startIndex": start, "endIndex": end},
                "paragraphStyle": {"namedStyleType": "TITLE"},
                "fields": "namedStyleType"}})
        elif kind == "heading":
            requests.append({"updateParagraphStyle": {
                "range": {"startIndex": start, "endIndex": end},
                "paragraphStyle": {"namedStyleType": "HEADING_2"},
                "fields": "namedStyleType"}})
        elif kind == "bullet":
            requests.append({"createParagraphBullets": {
                "range": {"startIndex": start, "endIndex": end},
                "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE"}})
    return requests


def create_doc(title: str, body: str, share_email: str) -> str:
    """Create a formatted Google Doc, share it with `share_email` as editor, and
    return its web link. Returns "" on any failure (caller falls back)."""
    if not enabled():
        return ""
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
    except Exception as exc:
        log.warning("gdocs: Google client libraries unavailable: %s", exc)
        return ""

    s = _settings()
    try:
        creds = Credentials.from_service_account_file(str(s.service_account_path()),
                                                      scopes=_SCOPES)
        drive = build("drive", "v3", credentials=creds, cache_discovery=False)
        docs = build("docs", "v1", credentials=creds, cache_discovery=False)

        meta = {"name": title[:200] or "Document",
                "mimeType": "application/vnd.google-apps.document",
                "parents": [s.google_drive_folder_id]}
        f = drive.files().create(body=meta, fields="id, webViewLink").execute()
        file_id = f.get("id")
        if not file_id:
            return ""

        reqs = build_doc_requests(title, body)
        if reqs:
            docs.documents().batchUpdate(documentId=file_id, body={"requests": reqs}).execute()

        if share_email:
            try:
                drive.permissions().create(
                    fileId=file_id,
                    body={"type": "user", "role": "writer", "emailAddress": share_email},
                    sendNotificationEmail=False, fields="id").execute()
            except Exception as exc:
                log.warning("gdocs: share with %s failed: %s", share_email, exc)
        return f.get("webViewLink", "")
    except Exception as exc:
        log.warning("gdocs: create failed for %r: %s", title, exc)
        return ""
