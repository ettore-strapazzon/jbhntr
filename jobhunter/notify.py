"""Email digest over SMTP. Sends only when there are new jobs to report."""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .config import Settings
from .models import RankedJob

log = logging.getLogger("jobhunter.notify")

from .models import TIER_LABELS as TIER_LABEL


def _sheet_url(settings: Settings) -> str:
    if settings.google_sheet_id:
        return f"https://docs.google.com/spreadsheets/d/{settings.google_sheet_id}/edit"
    return ""


def _plain(ranked: list[RankedJob], settings: Settings) -> str:
    lines = [f"{len(ranked)} new job match(es) today.", ""]
    for r in ranked:
        m, j = r.match, r.job
        lines.append(
            f"[{TIER_LABEL.get(m.tier, m.tier)} {m.score}] {m.role or j.title} "
            f"@ {m.company or j.company}   (id: {j.short_id()})"
        )
        lines.append(f"    {m.location or j.location} | {j.source}")
        if m.tags:
            lines.append(f"    tags: {', '.join(m.tags)}")
        lines.append(f"    {m.reasons}")
        if j.url:
            lines.append(f"    Apply: {j.url}")
        lines.append("")
    sheet = _sheet_url(settings)
    if sheet:
        lines.append(f"Full ranked list (and leave feedback): {sheet}")
    lines.append(
        "\nWant a tailored CV + cover letter for one of these?\n"
        "  python -m jobhunter.apply <id>"
    )
    return "\n".join(lines)


def _html(ranked: list[RankedJob], settings: Settings) -> str:
    rows = []
    for r in ranked:
        m, j = r.match, r.job
        apply_link = f'<a href="{j.url}">Apply</a>' if j.url else ""
        tags = (
            f"<br><span style='color:#666;font-size:12px'>{', '.join(m.tags)}</span>"
            if m.tags else ""
        )
        rows.append(
            f"<tr>"
            f"<td>{TIER_LABEL.get(m.tier, m.tier)}<br>"
            f"<span style='color:#888;font-size:12px'>{m.score}</span></td>"
            f"<td><b>{m.role or j.title}</b><br>{m.company or j.company}{tags}</td>"
            f"<td>{m.location or j.location}</td>"
            f"<td>{m.reasons}</td>"
            f"<td>{apply_link}</td>"
            f"<td><code>{j.short_id()}</code></td>"
            f"</tr>"
        )
    sheet = _sheet_url(settings)
    footer = (
        f'<p><a href="{sheet}">Open the full ranked list and leave feedback →</a></p>'
        if sheet
        else ""
    )
    return (
        f"<h2>{len(ranked)} new job match(es) today</h2>"
        "<table border='1' cellpadding='6' cellspacing='0' "
        "style='border-collapse:collapse;font-family:sans-serif;font-size:14px'>"
        "<tr><th>Tier</th><th>Role</th><th>Location</th>"
        "<th>Why</th><th>Apply</th><th>ID</th></tr>"
        + "".join(rows)
        + "</table>"
        + footer
        + "<p style='font-family:sans-serif;font-size:13px;color:#555'>"
        "Want a tailored CV + cover letter? Run "
        "<code>python -m jobhunter.apply &lt;id&gt;</code></p>"
    )


def send_digest(ranked: list[RankedJob], settings: Settings) -> bool:
    """Send the digest. Returns True if an email was actually sent."""
    if not ranked:
        log.info("No new jobs — no email sent.")
        return False
    if not (settings.smtp_user and settings.smtp_password and settings.email_to):
        log.warning("SMTP not configured — skipping email.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Job matches: {len(ranked)} new today"
    msg["From"] = settings.email_from or settings.smtp_user
    msg["To"] = settings.email_to
    msg.attach(MIMEText(_plain(ranked, settings), "plain", "utf-8"))
    msg.attach(MIMEText(_html(ranked, settings), "html", "utf-8"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(msg["From"], [settings.email_to], msg.as_string())
        log.info("Digest email sent to %s", settings.email_to)
        return True
    except Exception as exc:
        log.warning("Failed to send digest email: %s", exc)
        return False
