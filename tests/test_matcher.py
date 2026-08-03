"""The scoring prompt must keep enforcing location and weighting seniority — the
two failures the operator audit surfaced (foreign on-site roles and non-executive
roles ranking for an executive candidate)."""

from jobhunter.config import Materials, Profile
from jobhunter.matcher import PROMPT_VERSION, _system_prompt


def _prompt() -> str:
    p = Profile(raw={"objective": "P&L ownership", "seniority": ["executive"],
                     "locations": ["Italy"]})
    return _system_prompt(p, Materials(), [])


def test_location_is_a_hard_blocker():
    text = _prompt().lower()
    assert "location is a hard blocker" in text
    # It must forbid softening a wrong-country role back up to a keep tier.
    assert "wrong country" in text


def test_seniority_is_weighted_both_ways():
    text = _prompt().lower()
    assert "seniority" in text
    assert "below" in text and "tier 3" in text          # under-level roles capped
    assert "cv actually demonstrates" in text            # target AND demonstrated level


def test_prompt_version_bumped_to_invalidate_cache():
    # A prompt change with no version bump would keep serving stale cached scores.
    assert PROMPT_VERSION >= 6
