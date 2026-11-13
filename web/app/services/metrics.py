"""R3-06 BI metrics — the numbers behind /admin "Business metrics" and
/admin/metrics.json (the feed the CEO refreshes company/state/KPIS.md from).

Rules this module keeps:

* **Real numbers only.** A metric that cannot be computed has ``value=None``,
  ``display="—"`` and a ``reason``. Nothing is estimated or back-filled.
* **One activation rule.** "Activated" = account + profile ready + >=1 scan,
  where *profile ready* is ``Completeness.can_search`` (every required field
  filled, which is exactly the >=70% / REQUIRED_WEIGHT bar the product
  enforces in start_search) computed by profile_service's own pure helpers,
  and *scan* is activation.has_scanned's rule (free-scan flag set, or any
  Search that is not an "Imported job").
* **Query-efficient.** A fixed number of aggregate/bulk SELECTs regardless of
  user count (tests assert it) — no per-user queries.
* **No PII.** The payload carries counts and ratios only — no emails, no ids.
* **Read-only.** Nothing here writes.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import ROOT
from ..models import (
    GateAnswer, JobState, Material, ProductEvent, Profile, ReferralReward, Search,
    SeedCompany, User, utcnow,
)
from .activation import first_scan_rate_by_variant
from .gate import ANSWERS as GATE_ANSWER_CHOICES
from .gate import MAX_ASKS as GATE_MAX_ASKS
from .profile_service import Completeness, completeness_from, present_from
from .referral import TRIAGE_EVENTS

LEDGER_PATH = ROOT / "company" / "state" / "LEDGER.csv"
BUDGET_CAP_USD = 1000          # CHARTER: USD 1,000 lifetime
IMPORTED_STAGE = "Imported job"  # activation.has_scanned: an import is not a scan
SHARE_EVENTS = ("match_card_shared", "market_read_shared")
# "Outcome" = a user doing something with a result, not just looking at it.
OUTCOME_EVENTS = (*TRIAGE_EVENTS, "document_generated", *SHARE_EVENTS)
REWARD_STATUSES = ("pending", "held", "paid")
DASH = "—"
# R3-14 gate tile: below this many answers one reply moves the % by >10 points,
# so the tile shows "—" with the n rather than a number nobody should act on.
GATE_MIN_N = 10
GATE_ANSWERS = tuple(v for v, _ in GATE_ANSWER_CHOICES)


# ---------------------------------------------------------------- helpers --
def _metric(label: str, value, formula: str, *, reason: str = "",
            fmt: str = "int", **extra) -> dict:
    if value is None:
        display = DASH
    elif fmt == "pct":
        display = f"{value * 100:.1f}%"
    elif fmt == "ratio":
        display = f"{value:.2f}"
    elif fmt == "usd":
        display = f"${value:,.2f}"
    else:
        display = f"{value:,}"
    return {"label": label, "value": value, "display": display,
            "formula": formula, "reason": reason if value is None else "", **extra}


def _ratio(num: int, den: int, nd: int = 3):
    return round(num / den, nd) if den else None


# ---------------------------------------------------------- bulk loaders --
def profile_states(db: Session) -> dict[int, Completeness]:
    """Completeness for every user in three bulk SELECTs (profiles, material
    kinds, seed counts), scored by the same pure helpers completeness() uses."""
    profiles = {p.user_id: p for p in db.query(Profile).all()}
    kinds: dict[int, set[str]] = defaultdict(set)
    for uid, kind in db.query(Material.user_id, Material.kind).distinct():
        kinds[uid].add(kind)
    seeds = dict(db.query(SeedCompany.user_id, func.count(SeedCompany.id))
                 .group_by(SeedCompany.user_id).all())
    return {uid: completeness_from(present_from(profiles.get(uid), kinds.get(uid, set()),
                                                seeds.get(uid, 0)))
            for (uid,) in db.query(User.id)}


def _user_ids(q) -> set[int]:
    return {uid for (uid,) in q if uid is not None}


# ---------------------------------------------------------------- ledger --
def read_ledger(path: Path) -> tuple[dict | None, str]:
    """(totals, "") or (None, reason). Lines starting with '#' are comments.
    An unknown type or unparsable amount makes the whole read fail — a ledger
    we cannot read exactly is shown as "—", never partially summed."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None, f"LEDGER.csv not readable at {Path(path).name} on this host"
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    totals = {"actual": 0.0, "committed": 0.0, "revenue": 0.0, "rows": 0}
    if not lines:
        return totals, ""
    for i, row in enumerate(csv.DictReader(io.StringIO("\n".join(lines))), start=1):
        kind = (row.get("type") or "").strip().lower()
        if kind not in ("actual", "committed", "revenue"):
            return None, f"LEDGER row {i}: unknown type {kind!r}"
        try:
            usd = float((row.get("usd") or "").strip())
        except ValueError:
            return None, f"LEDGER row {i}: usd is not a number"
        totals[kind] += usd
        totals["rows"] += 1
    return totals, ""


# --------------------------------------------------------------- compute --
def compute(db: Session, *, now=None, ledger_path: Path | None = None) -> dict:
    now = now or utcnow()
    week_ago = now - timedelta(days=7)
    out: dict[str, dict] = {}

    # --- base sets (constant number of queries) ---
    users = db.query(User.id, User.created_at, User.first_scan_used_at,
                     User.referred_by_user_id).all()
    signups = len(users)
    signups_7d = db.query(func.count(User.id)).filter(User.created_at >= week_ago).scalar() or 0
    states = profile_states(db)
    ready = {uid for uid, st in states.items() if st.can_search}
    scanned = ({u.id for u in users if u.first_scan_used_at is not None}
               | _user_ids(db.query(Search.user_id)
                           .filter(Search.stage != IMPORTED_STAGE).distinct()))
    triaged_or_shared = (
        _user_ids(db.query(ProductEvent.user_id)
                  .filter(ProductEvent.name.in_((*TRIAGE_EVENTS, *SHARE_EVENTS))).distinct())
        | _user_ids(db.query(JobState.user_id).distinct()))
    activated = ready & scanned

    # --- headline counts ---
    out["signups"] = _metric(
        "Signups (accounts)", signups, "COUNT(users)", last_7d=signups_7d)
    out["activated"] = _metric(
        "Activated users", len(activated),
        "users with Completeness.can_search (all required fields = the 70% bar) "
        "AND >=1 scan (first_scan_used_at set, or a Search whose stage is not "
        "'Imported job')")
    out["activation_rate"] = _metric(
        "Activation rate", _ratio(len(activated), signups), "activated / signups",
        reason="no signups yet", fmt="pct")

    # --- funnel (nested: each step is a subset of the one before) ---
    s_ready = ready
    s_scan = s_ready & scanned
    s_act = s_scan & triaged_or_shared
    counts = [signups, len(s_ready), len(s_scan), len(s_act)]
    labels = ["Signed up", "Profile ready (>=70%, can_search)", "First scan",
              "First triage or share"]
    steps = []
    for i, (label, n) in enumerate(zip(labels, counts)):
        steps.append({"label": label, "count": n,
                      "pct_of_prev": None if i == 0 else _ratio(n, counts[i - 1]),
                      "pct_of_signups": _ratio(n, signups)})
    out["funnel"] = _metric(
        "Funnel (signup → profile → scan → triage/share)", signups,
        "nested user sets; triage = job_saved|job_dismissed|job_marked_applied|"
        "match_rated event or any JobState row (referral.has_triaged rule); "
        "share = match_card_shared|market_read_shared event", steps=steps)

    # --- gate prompt (R3-14: services/gate.py, one GateAnswer row per user) ---
    by_answer = {a: 0 for a in GATE_ANSWERS}
    asked = dismissed_for_good = 0
    for ans, dismissed, n in (db.query(GateAnswer.answer,
                                       GateAnswer.dismiss_count >= GATE_MAX_ASKS,
                                       func.count(GateAnswer.id))
                              .group_by(GateAnswer.answer,
                                        GateAnswer.dismiss_count >= GATE_MAX_ASKS)):
        asked += int(n)
        if ans in by_answer:
            by_answer[ans] += int(n)
        elif ans is None and dismissed:
            dismissed_for_good += int(n)
    gate_n = sum(by_answer.values())
    pos = by_answer["much_better"] + by_answer["better"]
    if gate_n == 0:
        gate_why = "no gate answers yet"
    elif gate_n < GATE_MIN_N:
        gate_why = f"n={gate_n} answers, below the {GATE_MIN_N} needed to read a %"
    else:
        gate_why = ""
    better = _ratio(pos, gate_n) if not gate_why else None
    much = _ratio(by_answer["much_better"], gate_n) if not gate_why else None
    much_txt = f"{much * 100:.1f}%" if much is not None else DASH
    gate_extra = {"n": gate_n, "by_answer": by_answer, "asked": asked,
                  "dismissed_for_good": dismissed_for_good, "min_n": GATE_MIN_N}
    out["gate_better"] = _metric(
        f'Gate "vs how you search today": better+much-better '
        f'(much-better {much_txt}, n={gate_n})', better,
        "answers in (much_better, better) / all gate answers; '—' while "
        f"n < {GATE_MIN_N} (KPI: >=60% better, >=30% much-better)",
        reason=gate_why, fmt="pct", much_better=much, **gate_extra)
    out["gate_much_better"] = _metric(
        f'Gate: much-better (n={gate_n})', much,
        f"answers = much_better / all gate answers; '—' while n < {GATE_MIN_N}",
        reason=gate_why, fmt="pct", **gate_extra)

    # --- K-factor ---
    referred_activated = {u.id for u in users
                          if u.referred_by_user_id and u.id in activated}
    inviters = {u.referred_by_user_id for u in users if u.referred_by_user_id}
    activated_inviters = inviters & activated
    out["k_factor"] = _metric(
        "K-factor", _ratio(len(referred_activated), len(activated)),
        "referred activated users / all activated users (viral coefficient; "
        "the Phase-2 >=0.3 gate)",
        reason="no activated users yet", fmt="ratio",
        referred_activated=len(referred_activated), activated=len(activated),
        activated_inviters=len(activated_inviters),
        per_activated_inviter=_ratio(len(referred_activated), len(activated_inviters)),
        per_activated_inviter_formula=(
            "referred activated users / activated users who referred >=1 signup"))

    # --- outcome events per active user, last 7 days ---
    outcome_n = (db.query(func.count(ProductEvent.id))
                 .filter(ProductEvent.created_at >= week_ago,
                         ProductEvent.user_id.isnot(None),
                         ProductEvent.name.in_(OUTCOME_EVENTS)).scalar() or 0)
    active_n = (db.query(func.count(func.distinct(ProductEvent.user_id)))
                .filter(ProductEvent.created_at >= week_ago,
                        ProductEvent.user_id.isnot(None)).scalar() or 0)
    out["outcome_events_per_active_user_week"] = _metric(
        "Outcome events / active user (last 7 days)", _ratio(outcome_n, active_n, 2),
        "outcome events (save, dismiss, applied, rated, draft generated, shared) in "
        "last 7d / distinct users with any product event in last 7d",
        reason="no active users in the last 7 days", fmt="ratio",
        outcome_events=outcome_n, active_users=active_n)

    # --- first-scan rate by activation-meter arm (R3-04) ---
    arms = first_scan_rate_by_variant(db)
    out["first_scan_rate_by_variant"] = _metric(
        "First-scan rate by meter variant", sum(a["signups"] for a in arms.values()),
        "per arm: users with scan_started / users with signup_completed "
        "(activation.first_scan_rate_by_variant)", arms=arms)

    # --- referral rewards ---
    rr = {s: {"count": 0, "credits": 0} for s in REWARD_STATUSES}
    for status, n, credits in (db.query(ReferralReward.status, func.count(ReferralReward.id),
                                        func.coalesce(func.sum(ReferralReward.amount), 0))
                               .group_by(ReferralReward.status)):
        rr.setdefault(status, {"count": 0, "credits": 0})
        rr[status] = {"count": int(n), "credits": int(credits or 0)}
    out["referral_rewards"] = _metric(
        "Referral rewards", sum(v["count"] for v in rr.values()),
        "COUNT / SUM(amount) of referral_rewards GROUP BY status", by_status=rr)

    # --- spend / revenue (company/state/LEDGER.csv) ---
    ledger, why = read_ledger(ledger_path or LEDGER_PATH)
    if ledger is None:
        out["spend_usd"] = _metric("Spend (USD, actual)", None,
                                   "SUM(usd) where type=actual", reason=why, fmt="usd")
        out["revenue_usd"] = _metric("Revenue (USD)", None,
                                     "SUM(usd) where type=revenue", reason=why, fmt="usd")
    else:
        spent, committed = round(ledger["actual"], 2), round(ledger["committed"], 2)
        out["spend_usd"] = _metric(
            "Spend (USD, actual)", spent, "SUM(usd) where type=actual", fmt="usd",
            committed=committed, rows=ledger["rows"],
            remaining_of_cap=round(BUDGET_CAP_USD - spent - committed, 2))
        out["revenue_usd"] = _metric(
            "Revenue (USD)", round(ledger["revenue"], 2), "SUM(usd) where type=revenue",
            fmt="usd", rows=ledger["rows"])

    return {"generated_at": now.isoformat(), "metrics": out}
