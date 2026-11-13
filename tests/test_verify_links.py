"""_verify_links must always return (kept, unverified) — its caller unpacks two
values, so an early exit returning a bare list failed zero-result scans."""
from unittest import mock

from web.app.services import search_service


def test_empty_ranked_returns_pair():
    kept, unverified = search_service._verify_links(None, [])
    assert kept == [] and unverified == set()


def test_link_check_error_returns_pair_unchanged():
    class _J:
        url = "https://example.com/x"
        def dedup_key(self):
            return "k"
    ranked = [(_J(), None)]
    with mock.patch("httpx.Client", side_effect=RuntimeError("boom")):
        kept, unverified = search_service._verify_links(None, ranked)
    assert kept is ranked and unverified == set()
