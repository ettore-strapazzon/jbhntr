"""Tests for pipeline helpers."""

from jobhunter.config import Materials, Profile, Settings
from jobhunter.matcher import Matcher
from jobhunter.models import JobPosting
from jobhunter.pipeline import _interleave_by_source


def test_score_counts_jobs_it_could_not_judge(monkeypatch, caplog):
    """A run cut short by API errors must not look like 'found nothing'."""
    import jobhunter.llm as llm

    calls = {"n": 0}

    class Client:
        def json(self, **kw):
            calls["n"] += 1
            if calls["n"] % 2:
                raise RuntimeError("402 insufficient credits")
            return {"tier": 3, "tier_label": "Possible", "score": 50,
                    "reasons": "ok", "tags": []}

    monkeypatch.setattr(llm, "get_client", lambda s: Client())
    m = Matcher(Settings())
    jobs = [JobPosting(source="x", title=f"j{i}") for i in range(4)]
    with caplog.at_level("WARNING"):
        out = m.score(jobs, Profile(raw={}), Materials())

    assert len(out) == 2
    assert m.failures == 2
    assert "INCOMPLETE" in caplog.text


def _jobs(source, n):
    return [JobPosting(source=source, title=f"{source}-{i}") for i in range(n)]


def test_interleave_spreads_sources_across_the_prefix():
    """A small --limit must not sample only the first source."""
    jobs = _jobs("adzuna", 5) + _jobs("linkedin", 5) + _jobs("arbeitnow", 5)
    out = _interleave_by_source(jobs)
    # The first 3 must cover all 3 sources, not 3x adzuna.
    assert {j.source for j in out[:3]} == {"adzuna", "linkedin", "arbeitnow"}


def test_interleave_keeps_every_job():
    jobs = _jobs("a", 3) + _jobs("b", 7) + _jobs("c", 1)
    out = _interleave_by_source(jobs)
    assert len(out) == 11
    assert {j.title for j in out} == {j.title for j in jobs}


def test_interleave_handles_uneven_sources():
    """A source running out early must not stall or drop the rest."""
    jobs = _jobs("big", 6) + _jobs("small", 1)
    out = _interleave_by_source(jobs)
    assert len(out) == 7
    assert out[0].source == "big"
    assert out[1].source == "small"
    assert all(j.source == "big" for j in out[2:])


def test_interleave_single_source_is_unchanged():
    jobs = _jobs("only", 4)
    assert [j.title for j in _interleave_by_source(jobs)] == [j.title for j in jobs]


def test_interleave_empty():
    assert _interleave_by_source([]) == []


# R3-29: in-stage heartbeat. The engine reports (done, total) to an optional
# `progress` callback on the CALLER's thread; a failing callback never kills
# the stage (the shell decides what a callback failure means).
def _ok_client(monkeypatch):
    import jobhunter.llm as llm

    class Client:
        def json(self, **kw):
            return {"tier": 3, "tier_label": "Possible", "score": 50,
                    "reasons": "ok", "tags": []}

    monkeypatch.setattr(llm, "get_client", lambda s: Client())


def test_score_reports_progress_on_the_callers_thread(monkeypatch):
    import threading
    _ok_client(monkeypatch)
    seen, threads = [], set()

    def progress(done, total):
        seen.append((done, total))
        threads.add(threading.get_ident())

    jobs = [JobPosting(source="x", title=f"j{i}") for i in range(5)]
    out = Matcher(Settings()).score(jobs, Profile(raw={}), Materials(), progress=progress)
    assert len(out) == 5
    assert seen == [(i, 5) for i in range(1, 6)]
    assert threads == {threading.get_ident()}     # the shell's DB session is not thread-safe


def test_score_survives_a_failing_progress_callback(monkeypatch):
    _ok_client(monkeypatch)

    def progress(done, total):
        raise RuntimeError("db hiccup")

    jobs = [JobPosting(source="x", title=f"j{i}") for i in range(3)]
    out = Matcher(Settings()).score(jobs, Profile(raw={}), Materials(), progress=progress)
    assert len(out) == 3


def test_collect_all_reports_progress_between_and_inside_sources(monkeypatch):
    import threading

    from jobhunter import sources

    def agg(profile, settings):
        return [JobPosting(source="a", title="t")]

    def ats_fetch(profile, settings, progress=None):
        for i in range(1, 4):                 # a long single source still beats
            progress(i, 3)
        return [JobPosting(source="ats", title="u")]

    monkeypatch.setattr(sources, "AGGREGATORS", {"a1": agg, "a2": agg})
    monkeypatch.setattr(sources.ats, "fetch", ats_fetch)
    monkeypatch.setattr(sources, "load_companies", lambda: [{"name": "x"}])
    monkeypatch.setattr(sources.keyed, "configured", lambda s: False)
    beats, threads = [], set()

    def progress(done, total):
        beats.append((done, total))
        threads.add(threading.get_ident())

    prof = Profile(raw={"sources": {"aggregators": ["a1", "a2"]}})
    jobs = sources.collect_all(prof, Settings(), progress=progress)
    assert len(jobs) == 3
    assert len(beats) >= 5                    # 2 aggregators + 3 inside ATS
    assert threads == {threading.get_ident()}


def test_collect_all_survives_a_failing_progress_callback(monkeypatch):
    from jobhunter import sources

    monkeypatch.setattr(sources, "AGGREGATORS",
                        {"a1": lambda p, s: [JobPosting(source="a", title="t")]})
    monkeypatch.setattr(sources, "load_companies", lambda: [])
    monkeypatch.setattr(sources.keyed, "configured", lambda s: False)

    def progress(done, total):
        raise RuntimeError("db hiccup")

    prof = Profile(raw={"sources": {"aggregators": ["a1"]}})
    assert len(sources.collect_all(prof, Settings(), progress=progress)) == 1


# R3-30: cancellation hook. The long stages take an optional `should_stop()`; once
# it says True the engine stops at the next job/source and returns what it has
# (the caller discards it). It is checked on the caller's thread, and a failing
# `should_stop` never stops a healthy stage. Raising instead would be swallowed by
# `collect_all`'s per-source catch-all, so the hook is a return value, not an error.
def _gated_calls(first_free):
    """A thread-safe call counter whose calls after the first `first_free` block
    until `release()` — so the work in flight when the caller says stop is exactly
    known, with no timing luck. `release()` opens the gate shortly after (on a timer),
    i.e. after the engine has had time to cancel the queue."""
    import threading
    lock, gate, calls = threading.Lock(), threading.Event(), {"n": 0}

    def call():
        with lock:
            calls["n"] += 1
            n = calls["n"]
        if n > first_free:
            gate.wait(5)

    def release():
        if not gate.is_set():
            threading.Timer(0.2, gate.set).start()
    return calls, call, release


def test_score_stops_early_when_asked(monkeypatch):
    import jobhunter.llm as llm
    from jobhunter.matcher import SCORE_WORKERS
    calls, call, release = _gated_calls(3)

    class Client:
        def json(self, **kw):
            call()
            return {"tier": 3, "tier_label": "Possible", "score": 50,
                    "reasons": "ok", "tags": []}

    monkeypatch.setattr(llm, "get_client", lambda s: Client())
    seen = []

    def should_stop():
        if len(seen) >= 3:
            release()
            return True
        return False

    jobs = [JobPosting(source="x", title=f"j{i}") for i in range(60)]
    out = Matcher(Settings()).score(jobs, Profile(raw={}), Materials(),
                                    progress=lambda d, t: seen.append(d),
                                    should_stop=should_stop)
    assert len(out) == 3                            # partial results, not all 60
    assert calls["n"] <= 3 + SCORE_WORKERS          # only the in-flight jobs ran


def test_score_ignores_a_failing_should_stop(monkeypatch):
    _ok_client(monkeypatch)

    def should_stop():
        raise RuntimeError("db hiccup")

    jobs = [JobPosting(source="x", title=f"j{i}") for i in range(4)]
    out = Matcher(Settings()).score(jobs, Profile(raw={}), Materials(),
                                    should_stop=should_stop)
    assert len(out) == 4


def test_collect_all_stops_between_sources(monkeypatch):
    from jobhunter import sources
    called = []

    def agg(name):
        def fetch(profile, settings):
            called.append(name)
            return [JobPosting(source=name, title="t")]
        return fetch

    monkeypatch.setattr(sources, "AGGREGATORS", {n: agg(n) for n in ("a1", "a2", "a3")})
    monkeypatch.setattr(sources, "load_companies", lambda: [])
    monkeypatch.setattr(sources.keyed, "configured", lambda s: False)
    prof = Profile(raw={"sources": {"aggregators": ["a1", "a2", "a3"]}})
    jobs = sources.collect_all(prof, Settings(), should_stop=lambda: bool(called))
    assert called == ["a1"] and len(jobs) == 1


def test_collect_all_hands_should_stop_to_the_ats_long_tail(monkeypatch):
    from jobhunter import sources
    got = {}

    def ats_fetch(profile, settings, progress=None, should_stop=None):
        got["stop"] = should_stop
        return []

    monkeypatch.setattr(sources, "AGGREGATORS", {})
    monkeypatch.setattr(sources.ats, "fetch", ats_fetch)
    monkeypatch.setattr(sources, "load_companies", lambda: [{"name": "x"}])
    monkeypatch.setattr(sources.keyed, "configured", lambda s: False)
    flag = {"v": False}
    sources.collect_all(Profile(raw={}), Settings(), should_stop=lambda: flag["v"])
    assert got["stop"] is not None and got["stop"]() is False
    flag["v"] = True
    assert got["stop"]() is True


def test_ats_fetch_stops_early_when_asked(monkeypatch):
    from jobhunter.sources import ats
    calls, call, release = _gated_calls(2)

    def fake(name, token):
        call()
        return [JobPosting(source=f"ats:fake:{token}", title="t")]

    monkeypatch.setattr(ats, "FETCHERS", {"fake": fake})
    monkeypatch.setattr(ats, "load_companies",
                        lambda: [{"name": f"c{i}", "ats": "fake", "token": f"c{i}"}
                                 for i in range(80)])
    done = []

    def should_stop():
        if len(done) >= 2:
            release()
            return True
        return False

    jobs = ats.fetch(Profile(raw={}), Settings(), progress=lambda d, t: done.append(d),
                     should_stop=should_stop)
    assert len(jobs) == 2
    assert calls["n"] <= 2 + ats.MAX_WORKERS        # only the in-flight companies ran


# R3-31: the batched AI triage (live-fetch fallback, >40 jobs) runs its batches
# SERIALLY — ceil(N/25) calls of up to ~90-185 s each in the worst case — so it
# takes the same optional `progress` / `should_stop` keywords as scoring.
def _triage_client(monkeypatch, calls):
    import jobhunter.llm as llm

    class Client:
        def json(self, **kw):
            calls.append(kw["user"].count("\n"))           # one call per batch
            return {"verdicts": []}                        # unrated -> kept

    monkeypatch.setattr(llm, "get_client", lambda s: Client())


def test_triage_reports_progress_per_batch_on_the_callers_thread(monkeypatch):
    import threading

    from jobhunter.matcher import TRIAGE_BATCH
    calls, seen, threads = [], [], set()
    _triage_client(monkeypatch, calls)

    def progress(done, total):
        seen.append((done, total))
        threads.add(threading.get_ident())

    jobs = [JobPosting(source="x", title=f"j{i}") for i in range(2 * TRIAGE_BATCH + 10)]
    out = Matcher(Settings()).triage(jobs, Profile(raw={}), progress=progress)
    n = len(jobs)
    assert len(out) == n and len(calls) == 3
    assert seen == [(TRIAGE_BATCH, n), (2 * TRIAGE_BATCH, n), (n, n)]
    assert threads == {threading.get_ident()}


def test_triage_stops_between_batches_when_asked(monkeypatch):
    from jobhunter.matcher import TRIAGE_BATCH
    calls, seen = [], []
    _triage_client(monkeypatch, calls)
    jobs = [JobPosting(source="x", title=f"j{i}") for i in range(10 * TRIAGE_BATCH)]
    out = Matcher(Settings()).triage(jobs, Profile(raw={}),
                                     progress=lambda d, t: seen.append(d),
                                     should_stop=lambda: len(seen) >= 2)
    assert len(calls) == 2                       # not all 10 paid batches
    assert len(out) == 2 * TRIAGE_BATCH          # partial (the caller discards it)


def test_triage_survives_a_failing_progress_or_should_stop(monkeypatch):
    from jobhunter.matcher import TRIAGE_BATCH
    calls = []
    _triage_client(monkeypatch, calls)

    def boom(*a):
        raise RuntimeError("db hiccup")

    jobs = [JobPosting(source="x", title=f"j{i}") for i in range(3 * TRIAGE_BATCH)]
    out = Matcher(Settings()).triage(jobs, Profile(raw={}), progress=boom, should_stop=boom)
    assert len(out) == len(jobs) and len(calls) == 3
