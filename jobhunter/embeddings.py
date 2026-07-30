"""Provider-agnostic text embeddings for semantic ranking.

Calls any OpenAI-compatible `/embeddings` endpoint (OpenAI, Jina, Voyage,
DeepInfra, a local server…), selected purely by env — no code change to switch.
Unconfigured is a safe no-op: `is_configured()` is False and `embed()` returns
empty, so the corpus/search paths simply skip embedding until a backend is set.

Used to rank jobs against a candidate profile cheaply, replacing the LLM triage
stage (see docs/INGESTION_ENGINE.md step 3). Embeddings RANK, never hard-cut.
"""

from __future__ import annotations

import logging
import math
import time

from .config import Settings
from .sources.base import http_client

log = logging.getLogger("jobhunter.embeddings")

BATCH = 64          # texts per request
_MAX_CHARS = 8000   # trim very long inputs before sending
_RETRIES = 4        # per-batch retries on rate-limit / transient errors
_DELAY = 0.3        # polite pause between batches (free tiers rate-limit hard)


def _is_local(settings: Settings) -> bool:
    return settings.embedding_base_url.strip().lower() in ("local", "fastembed")


def is_configured(settings: Settings) -> bool:
    # Local needs no key; a hosted endpoint needs both a URL and a key.
    if _is_local(settings):
        return True
    return bool(settings.embedding_base_url and settings.embedding_api_key)


LOCAL_MODEL = "BAAI/bge-small-en-v1.5"   # small, fast on CPU, 384-dim


def model_name(settings: Settings) -> str:
    """The identifier stored alongside a vector so a model change re-embeds.

    For the local backend, a hosted model id like 'text-embedding-3-small' or
    'jina-embeddings-v3' isn't a fastembed model, so fall back to LOCAL_MODEL
    unless an HF-style id ('org/model') was set explicitly.
    """
    if _is_local(settings):
        m = settings.embedding_model or ""
        return m if "/" in m else LOCAL_MODEL
    return settings.embedding_model


_LOCAL_MODEL = None
_LOCAL_MODEL_NAME = None


def _local_model(name: str):
    """Lazily load + cache a fastembed model (first call downloads it once)."""
    global _LOCAL_MODEL, _LOCAL_MODEL_NAME
    if _LOCAL_MODEL is None or _LOCAL_MODEL_NAME != name:
        from fastembed import TextEmbedding
        _LOCAL_MODEL = TextEmbedding(model_name=name)
        _LOCAL_MODEL_NAME = name
    return _LOCAL_MODEL


_LOCAL_BATCH = 32   # keep the fastembed/onnxruntime working set small (cron memory)


def _embed_local(texts: list[str], settings: Settings) -> list[list[float]]:
    """On-device embeddings via fastembed — free, no quota, no network.

    Embed in small chunks rather than handing the whole list to onnxruntime at
    once: the model itself is a fixed cost, but a 1000-text call also holds every
    input string and its intermediate tensors in memory, which is enough to OOM a
    small cron container. Chunking bounds that to one batch at a time.
    """
    name = model_name(settings)
    try:
        model = _local_model(name)
        out: list[list[float]] = []
        for i in range(0, len(texts), _LOCAL_BATCH):
            chunk = [(t or "")[:_MAX_CHARS] or " " for t in texts[i : i + _LOCAL_BATCH]]
            out.extend(vec.tolist() for vec in model.embed(chunk))
        return out
    except Exception as exc:
        log.warning("Local embedding failed: %s", exc)
        return []


def embed(texts: list[str], settings: Settings) -> list[list[float]]:
    """Embed texts in order. Returns [] if unconfigured or on failure.

    On a partial/failed batch the whole call returns [] rather than a ragged
    list — callers treat "no embeddings" as "skip embedding", never as a
    silent mismatch between texts and vectors.
    """
    if not is_configured(settings) or not texts:
        return []
    if _is_local(settings):
        return _embed_local(texts, settings)
    url = settings.embedding_base_url.rstrip("/") + "/embeddings"
    headers = {"Authorization": f"Bearer {settings.embedding_api_key}"}
    out: list[list[float]] = []
    with http_client(timeout=60.0) as client:
        for i in range(0, len(texts), BATCH):
            batch = [(t or "")[:_MAX_CHARS] or " " for t in texts[i : i + BATCH]]
            vecs = _embed_batch(client, url, headers, settings.embedding_model, batch)
            if vecs is None:            # a batch failed after retries
                return []
            out.extend(vecs)
            if i + BATCH < len(texts):
                time.sleep(_DELAY)      # stay under free-tier rate limits
    return out


def _embed_batch(client, url, headers, model, batch) -> list[list[float]] | None:
    """One batch with retry/backoff on rate-limit or transient errors."""
    for attempt in range(_RETRIES):
        try:
            resp = client.post(url, headers=headers,
                               json={"model": model, "input": batch})
            if resp.status_code == 429:          # rate limited — back off and retry
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            data = resp.json().get("data", [])
            if len(data) != len(batch):
                log.warning("Embedding batch size mismatch")
                return None
            return [[float(x) for x in item["embedding"]]
                    for item in sorted(data, key=lambda d: d.get("index", 0))]
        except Exception as exc:
            if attempt == _RETRIES - 1:
                log.warning("Embedding batch failed after %d tries: %s", _RETRIES, exc)
                return None
            time.sleep(2 ** attempt)
    return None


def embed_one(text: str, settings: Settings) -> list[float]:
    vecs = embed([text], settings)
    return vecs[0] if vecs else []


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [-1, 1]; 0.0 if either vector is empty/degenerate."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
