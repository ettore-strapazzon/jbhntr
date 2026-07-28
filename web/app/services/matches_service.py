"""Accumulating Matches view (§11.5 / F-05).

The old page showed only the latest run and threw the rest away. Here a run is a
diff, not a replacement: results accumulate across runs keyed by posting
identity (dedup_key), the newest version of each wins, and anything that first
appeared in the most recent run is flagged "new". Per-user state (saved /
dismissed / applied) rides along; dismissed and applied drop out of the main
list.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session as DbSession

from ..models import JobResult, JobState, Search, aware
from .job_state import state_map
from .text import as_bullets

# Tier -> group. 1/2/3 get their own group; 4 and 5 are long shots.
TIER_GROUPS = [(1, "Apply now"), (2, "Strong"), (3, "Possible")]
SORTS = {
    "best": lambda c: (-c.r.score, c.r.position),
    "newest": lambda c: (0 if c.is_new else 1, -c.r.id),
    "fit": lambda c: (-c.r.fit_candidate, -c.r.score),
}


@dataclass
class Card:
    r: JobResult
    st: JobState | None
    is_new: bool

    @property
    def good_bullets(self) -> list[str]:
        return as_bullets(self.r.why_good, 3)

    @property
    def bad_bullets(self) -> list[str]:
        return as_bullets(self.r.why_bad, 2)


@dataclass
class Group:
    label: str
    cards: list = field(default_factory=list)


@dataclass
class Matches:
    searches: list          # all done runs, newest first (for the run selector)
    latest: Search | None
    run: Search | None      # a single selected run, or None for the accumulation
    groups: list            # [Group] for tiers 1-3
    long_shots: list        # [Card] tier 4-5
    sources: list           # distinct sources present (filter options)
    total: int              # matches after state filtering, before facet filters
    shown: int              # matches actually rendered
    new_count: int
    has_prior_run: bool     # whether to show the "new since" divider at all


def build(db: DbSession, user, *, run_id: int | None = None,
          tiers: set[int] | None = None, source: str = "",
          sort: str = "best", saved_only: bool = False) -> Matches:
    runs = (db.query(Search)
              .filter(Search.user_id == user.id, Search.status == "done")
              .order_by(Search.started_at.desc())
              .all())
    latest = runs[0] if runs else None
    selected = next((s for s in runs if s.id == run_id), None) if run_id else None

    q = db.query(JobResult).filter(JobResult.user_id == user.id)
    if selected:
        q = q.filter(JobResult.search_id == selected.id)
    else:
        q = q.filter(JobResult.search_id.in_([s.id for s in runs] or [0]))
    rows = q.all()

    # Collapse to one row per posting: newest wins, but remember first appearance.
    newest: dict[str, JobResult] = {}
    first_seen: dict[str, object] = {}
    for r in sorted(rows, key=lambda r: r.id):
        key = r.dedup_key or f"legacy-{r.id}"
        first_seen.setdefault(key, r.created_at)
        newest[key] = r

    states = state_map(db, user.id)
    cutoff = aware(latest.started_at) if (latest and len(runs) > 1) else None

    cards: list[Card] = []
    sources: set[str] = set()
    for key, r in newest.items():
        st = states.get(r.dedup_key)
        if st and (st.dismissed or st.applied_at):     # these leave the main list
            continue
        if r.source:
            sources.add(r.source)
        is_new = bool(cutoff and aware(first_seen[key]) and aware(first_seen[key]) >= cutoff)
        cards.append(Card(r=r, st=st, is_new=is_new))

    total = len(cards)

    # Facet filters.
    if tiers:
        cards = [c for c in cards if c.r.tier in tiers]
    if source:
        cards = [c for c in cards if c.r.source == source]
    if saved_only:
        cards = [c for c in cards if c.st and c.st.saved]

    cards.sort(key=SORTS.get(sort, SORTS["best"]))

    groups = []
    for tier, label in TIER_GROUPS:
        g = [c for c in cards if c.r.tier == tier]
        if g:
            groups.append(Group(label=label, cards=g))
    long_shots = [c for c in cards if c.r.tier >= 4]

    return Matches(
        searches=runs, latest=latest, run=selected,
        groups=groups, long_shots=long_shots,
        sources=sorted(sources), total=total, shown=len(cards),
        new_count=sum(1 for c in cards if c.is_new),
        has_prior_run=len(runs) > 1,
    )
