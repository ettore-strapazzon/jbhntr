"""Google Sheet output + feedback read-back.

The sheet is the user-facing dashboard AND the feedback UI: the tool appends
ranked rows; the user fills the `Feedback` and `Why` columns over time; the next
run reads those back to teach the matcher.
"""

from __future__ import annotations

import logging
from datetime import date

import gspread

from .config import Settings
from .gdrive import credentials
from .models import RankedJob

log = logging.getLogger("jobhunter.sheets")

WORKSHEET = "Jobs"
HEADER = [
    "Run date",
    "ID",         # quote this to `python -m jobhunter.apply <ID>`
    "Tier",
    "Score",
    "Role",
    "Company",
    "Location",
    "Tags",       # criteria this job meets — filter on these
    "Vertical",
    "Seniority",
    "Remote",
    "Posted",
    "Apply link",
    "CV link",
    "CL link",
    "Match reasons",
    "Source",
    "Status",
    "Feedback",  # user fills: e.g. "good" / "bad"
    "Why",       # user fills: free text
]


class Sheet:
    def __init__(self, settings: Settings):
        self.settings = settings
        creds = credentials(str(settings.service_account_path()))
        self.gc = gspread.authorize(creds)
        self.sh = self.gc.open_by_key(settings.google_sheet_id)
        self.ws = self._ensure_ws()

    def _ensure_ws(self):
        try:
            ws = self.sh.worksheet(WORKSHEET)
        except gspread.WorksheetNotFound:
            ws = self.sh.add_worksheet(title=WORKSHEET, rows=1000, cols=len(HEADER))
        values = ws.get_all_values()
        if not values:
            ws.append_row(HEADER, value_input_option="RAW")
        return ws

    # ------------------------------------------------------------------ #
    def read_feedback(self) -> list[dict]:
        """Collect rows where the user filled the Feedback column."""
        rows = self.ws.get_all_records(expected_headers=HEADER)
        out: list[dict] = []
        for row in rows:
            verdict = str(row.get("Feedback", "")).strip()
            if not verdict:
                continue
            out.append(
                {
                    "title": row.get("Role") or "",
                    "company": row.get("Company") or "",
                    "url": row.get("Apply link") or "",
                    "verdict": verdict,
                    "why": str(row.get("Why", "")).strip(),
                }
            )
        log.info("Read %d feedback examples from sheet", len(out))
        return out

    # ------------------------------------------------------------------ #
    def update_document_links(self, short_id: str, cv_link: str, cl_link: str) -> bool:
        """Write CV/cover-letter links onto the row with this job ID."""
        try:
            values = self.ws.get_all_values()
            if not values:
                return False
            header = values[0]
            id_col = header.index("ID")
            cv_col = header.index("CV link")
            cl_col = header.index("CL link")
        except (ValueError, Exception) as exc:  # missing column or API error
            log.warning("Could not locate sheet columns: %s", exc)
            return False

        for row_num, row in enumerate(values[1:], start=2):
            if len(row) > id_col and row[id_col].strip() == short_id:
                try:
                    # gspread columns are 1-indexed.
                    self.ws.update_cell(row_num, cv_col + 1, cv_link)
                    self.ws.update_cell(row_num, cl_col + 1, cl_link)
                    return True
                except Exception as exc:
                    log.warning("Could not write links to row %d: %s", row_num, exc)
                    return False
        return False

    # ------------------------------------------------------------------ #
    def append_ranked(self, ranked: list[RankedJob]) -> None:
        run = date.today().isoformat()
        rows = [self._to_row(r, run) for r in ranked]
        if rows:
            self.ws.append_rows(rows, value_input_option="USER_ENTERED")
            log.info("Appended %d rows to sheet", len(rows))

    def _to_row(self, r: RankedJob, run: str) -> list:
        m, j = r.match, r.job
        cv = r.cv_link or ""
        cl = r.cl_link or ""
        return [
            run,
            j.short_id(),
            f"{m.tier} {m.tier_label}",
            m.score,
            m.role or j.title,
            m.company or j.company,
            m.location or j.location,
            ", ".join(m.tags),
            m.vertical,
            m.seniority,
            m.remote,
            j.posted_date.isoformat() if j.posted_date else "",
            j.url,
            cv,
            cl,
            m.reasons,
            j.source,
            "new",
            "",  # Feedback (user fills)
            "",  # Why (user fills)
        ]
