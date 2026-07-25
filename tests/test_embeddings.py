"""Embedding layer: cosine math and the safe no-op-when-unconfigured contract."""

import pytest

from jobhunter import embeddings
from jobhunter.config import Settings


@pytest.mark.parametrize(
    "a, b, expected",
    [
        ([1.0, 0.0], [1.0, 0.0], 1.0),        # identical
        ([1.0, 0.0], [0.0, 1.0], 0.0),        # orthogonal
        ([1.0, 0.0], [-1.0, 0.0], -1.0),      # opposite
        ([], [1.0], 0.0),                      # empty
        ([0.0, 0.0], [1.0, 1.0], 0.0),        # degenerate
        ([1.0], [1.0, 2.0], 0.0),             # length mismatch
    ],
)
def test_cosine(a, b, expected):
    assert embeddings.cosine(a, b) == pytest.approx(expected)


def test_unconfigured_is_a_safe_noop():
    s = Settings()  # no embedding_base_url / key
    assert embeddings.is_configured(s) is False
    assert embeddings.embed(["anything"], s) == []
    assert embeddings.embed_one("x", s) == []


def test_configured_flag_needs_both_url_and_key():
    assert embeddings.is_configured(Settings(embedding_base_url="https://x")) is False
    assert embeddings.is_configured(Settings(embedding_api_key="k")) is False
    assert embeddings.is_configured(
        Settings(embedding_base_url="https://x", embedding_api_key="k")) is True


def test_local_backend_needs_no_key():
    # "local"/"fastembed" runs on-device — configured without any key.
    for val in ("local", "fastembed", "LOCAL"):
        s = Settings(embedding_base_url=val)
        assert embeddings._is_local(s) is True
        assert embeddings.is_configured(s) is True
    assert embeddings._is_local(Settings(embedding_base_url="https://x")) is False
