"""R3-34 — team runner in the repo: git sync (rebase -> merge -> park), parked-branch merging, wrapper fallback.

Every test uses throwaway git repos in tmp_path (a bare origin that rejects non-fast-forward pushes + clones) and a stub
`claude` (CLAUDE_BIN). Nothing touches the real runtime dir, crontab or the network (app URL points at a closed port).
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parent.parent / "ops" / "team"
RUNNER = OPS / "run_cycle.sh"
WRAPPER = OPS / "run_wrapper.sh"

pytestmark = pytest.mark.skipif(
    not all(shutil.which(t) for t in ("bash", "git", "flock", "timeout")),
    reason="needs bash, git, flock, timeout",
)


def git(cwd, *args, check=True):
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    for k, v in {
        "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }.items():
        monkeypatch.setenv(k, v)
    for k in ("JBHNTR_REPO", "JBHNTR_APP_URL", "JBHNTR_ADMIN_TOKEN", "JBHNTR_BRANCH", "RUN_CYCLE_LIB"):
        monkeypatch.delenv(k, raising=False)

    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    git(origin, "config", "receive.denyNonFastForwards", "true")  # any force-push would be rejected
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", str(origin), str(seed)], check=True, capture_output=True)
    (seed / "a.txt").write_text("1\n2\n3\n")
    (seed / "b.txt").write_text("x\n")
    shutil.copytree(OPS / "prompts", seed / "ops" / "team" / "prompts")  # the runner reads these + bridge.py from HEAD
    shutil.copy(OPS / "bridge.py", seed / "ops" / "team" / "bridge.py")
    git(seed, "add", "-A")
    git(seed, "commit", "-qm", "seed")
    git(seed, "push", "-q", "origin", "HEAD:main")

    repo, other = tmp_path / "repo", tmp_path / "other"
    for c in (repo, other):
        subprocess.run(["git", "clone", "-q", str(origin), str(c)], check=True, capture_output=True)

    team = tmp_path / "team"
    team.mkdir()
    (team / "env").write_text(f"export JBHNTR_REPO={repo}\nexport JBHNTR_APP_URL=http://127.0.0.1:9\n")
    monkeypatch.setenv("JBHNTR_TEAM", str(team))

    stub = tmp_path / "claude"
    # Records the env the agent sees; optional STUB_ACTION runs inside the repo (simulates the agent's commits).
    stub.write_text('#!/usr/bin/env bash\necho "PARKED=${PARKED_BRANCHES:-}" > "$JBHNTR_TEAM/agent.env"\n'
                    'printf %s "$2" > "$JBHNTR_TEAM/prompt.txt"; echo "TOKEN=${JBHNTR_ADMIN_TOKEN:-}" > "$JBHNTR_TEAM/token.env"\n'
                    'eval "${STUB_ACTION:-}"\necho "thinking"\necho "BOARDROOM: all done"\n')
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("CLAUDE_BIN", str(stub))
    return {"origin": origin, "repo": repo, "other": other, "team": team}


def commit(clone, path, text, msg):
    (Path(clone) / path).write_text(text)
    git(clone, "add", "-A")
    git(clone, "commit", "-qm", msg)
    return git(clone, "rev-parse", "HEAD")


def push(clone):
    git(clone, "push", "-q", "origin", "HEAD:main")
    return git(clone, "rev-parse", "HEAD")


def run(*args, script=RUNNER, **extra):
    e = {**os.environ, **extra}
    return subprocess.run(["bash", str(script), *args], env=e, capture_output=True, text=True, timeout=60)


def origin_main(env):
    return git(env["origin"], "rev-parse", "main")


def remote_branches(env):
    return git(env["origin"], "for-each-ref", "--format=%(refname:short)", "refs/heads/").split()


def test_scripts_parse_and_never_force_push():
    for s in (RUNNER, WRAPPER):
        assert subprocess.run(["bash", "-n", str(s)]).returncode == 0
        src = s.read_text()
        assert "--force" not in src and "push -f" not in src and "push -qf" not in src


def test_clean_rebase(env):
    commit(env["repo"], "b.txt", "local\n", "local change")
    commit(env["other"], "a.txt", "1\n2\nTHEIRS\n", "their change")
    theirs = push(env["other"])
    r = run("cycle")
    assert r.returncode == 0, r.stderr
    git(env["origin"], "merge-base", "--is-ancestor", theirs, "main")
    assert git(env["origin"], "rev-list", "--merges", "--count", "main") == "0"  # linear
    assert git(env["origin"], "show", "main:b.txt") == "local"
    assert git(env["origin"], "show", "main:a.txt").endswith("THEIRS")
    assert "all done" in (env["team"] / "cycle.log").read_text()


def test_merge_fallback_when_rebase_conflicts(env):
    # local: change line 2 then change it back -> replaying commit 1 conflicts, but the net diff merges cleanly
    commit(env["repo"], "a.txt", "1\nLOCAL\n3\n", "local edit")
    commit(env["repo"], "a.txt", "1\n2\n3\n", "local revert")
    commit(env["repo"], "b.txt", "kept\n", "local keep")
    commit(env["other"], "a.txt", "1\nTHEIRS\n3\n", "their edit")
    theirs = push(env["other"])
    assert run("cycle").returncode == 0
    git(env["origin"], "merge-base", "--is-ancestor", theirs, "main")
    assert int(git(env["origin"], "rev-list", "--merges", "--count", "main")) >= 1
    assert git(env["origin"], "show", "main:a.txt") == "1\nTHEIRS\n3"
    assert git(env["origin"], "show", "main:b.txt") == "kept"
    assert remote_branches(env) == ["main"]


def test_true_conflict_parks_without_force_push(env):
    mine = commit(env["repo"], "a.txt", "1\nMINE\n3\n", "my edit")
    commit(env["other"], "a.txt", "1\nTHEIRS\n3\n", "their edit")
    theirs = push(env["other"])
    assert run("cycle").returncode == 0
    parked = f"conflict/cycle-{git(env['repo'], 'rev-parse', '--short', mine)}"
    assert parked in remote_branches(env)
    assert git(env["origin"], "rev-parse", parked) == mine  # my work is kept on origin
    assert origin_main(env) == theirs  # main untouched: not overwritten by a force-push
    assert git(env["repo"], "rev-parse", "HEAD") == theirs  # local tree follows origin again
    assert f"PARKED=origin/{parked}" in (env["team"] / "agent.env").read_text()  # still conflicts -> agent told
    assert "CONFLICT" in (env["team"] / "cycle.log").read_text()


def test_clean_parked_branch_merged_and_deleted_next_run(env):
    # a parked branch from an earlier run that now merges cleanly, plus one that still conflicts
    o = env["other"]
    git(o, "checkout", "-qb", "p1")
    clean = commit(o, "c.txt", "parked work\n", "parked clean")
    git(o, "push", "-q", "origin", "HEAD:refs/heads/conflict/chat-aaa1111")
    git(o, "checkout", "-q", "main")
    git(o, "checkout", "-qb", "p2")
    commit(o, "a.txt", "1\nPARKED\n3\n", "parked conflicting")
    git(o, "push", "-q", "origin", "HEAD:refs/heads/conflict/chat-bbb2222")
    git(o, "checkout", "-q", "main")
    commit(o, "a.txt", "1\nMAIN\n3\n", "main moved")
    push(o)

    assert run("cycle").returncode == 0
    git(env["origin"], "merge-base", "--is-ancestor", clean, "main")
    assert git(env["origin"], "show", "main:c.txt") == "parked work"
    assert remote_branches(env) == ["conflict/chat-bbb2222", "main"]  # clean one deleted once on main
    assert (env["team"] / "agent.env").read_text().strip() == "PARKED=origin/conflict/chat-bbb2222"

    # the agent merges the conflicting one by hand -> the runner pushes it and deletes the branch
    action = ("git merge -q origin/conflict/chat-bbb2222 >/dev/null 2>&1; printf '1\\nMAIN\\nPARKED\\n3\\n' > a.txt; "
              "git add a.txt; git commit -qm 'merge parked by hand'")
    assert run("cycle", STUB_ACTION=action).returncode == 0
    assert git(env["origin"], "show", "main:a.txt") == "1\nMAIN\nPARKED\n3"
    assert remote_branches(env) == ["main"]


def test_boardroom_reply_tail():
    def reply(mode, out):
        cmd = f'MODE={mode}; source <(sed -n "/^boardroom_reply()/,/^}}/p" {RUNNER}); boardroom_reply "$1"'
        return subprocess.run(["bash", "-c", cmd, "_", out], capture_output=True, text=True).stdout

    assert reply("cycle", "a\nBOARDROOM: first\nb\nBOARDROOM: last line\nmore\n\n") == "last line\nmore"
    assert reply("cycle", "a\nfinal words\n\n") == "final words"
    assert reply("chat", "Hi Founder,\n\nall good.\n") == "Hi Founder,\nall good."


def test_unknown_mode_is_rejected(env):
    assert run("bogus").returncode == 2


def _wrapper_case(env, body):
    (env["repo"] / "ops" / "team").mkdir(parents=True, exist_ok=True)
    if body is None:
        git(env["repo"], "rm", "-q", "ops/team/run_cycle.sh")
        git(env["repo"], "commit", "-qm", "remove runner")
    else:
        commit(env["repo"], "ops/team/run_cycle.sh", body, "runner")
    return run("cycle", script=WRAPPER)


def test_wrapper_runs_head_copy_then_falls_back(env):
    good, out = env["team"] / "run_cycle.good.sh", env["team"] / "ran"
    r = _wrapper_case(env, f'echo "head $1" > {out}\n')
    assert r.returncode == 0 and out.read_text() == "head cycle\n"
    assert "head" in good.read_text()  # good copy refreshed from HEAD

    # working-tree edits are ignored: only the committed copy runs
    (env["repo"] / "ops/team/run_cycle.sh").write_text(f'echo "dirty" > {out}\n')
    assert run("cycle", script=WRAPPER).returncode == 0 and out.read_text() == "head cycle\n"
    git(env["repo"], "checkout", "-q", "--", "ops/team/run_cycle.sh")

    out.unlink()
    r = _wrapper_case(env, "if then fi (\n")  # broken syntax -> last good copy
    assert r.returncode == 0 and out.read_text() == "head cycle\n"
    assert "missing or invalid" in (env["team"] / "cycle.log").read_text()

    out.unlink()
    r = _wrapper_case(env, None)  # missing from HEAD -> last good copy
    assert r.returncode == 0 and out.read_text() == "head cycle\n"

    good.unlink()
    assert run("cycle", script=WRAPPER).returncode == 1  # nothing to run
    assert "no runner available" in (env["team"] / "cycle.log").read_text()


# --- R3-35 / R3-37: Boardroom via bridge.py, prompts from the committed tree ---

def test_prompt_files_exist_and_carry_the_rules():
    for mode in ("cycle", "chat", "morning"):
        text = (OPS / "prompts" / f"{mode}.md").read_text()
        assert "BOARDROOM:" in text
        assert "curl" not in text or "never call the Boardroom with curl" in text
    cycle = (OPS / "prompts" / "cycle.md").read_text()
    for rule in ("SKIPPED:", "10 full cycles", "keeping BOTH sides", "planning cycle", "origin/conflict/*",
                 "bridge.py log", "started", "--detail-file", "python -m pytest -q .", "web/app/static/app.js",
                 "No outward acts", "env file"):
        assert rule in cycle, rule
    chat = (OPS / "prompts" / "chat.md").read_text()
    for rule in ("LINE-LEVEL", "CYCLE_RUNNING=1", "header status word", "DECISIONS.md", "ONE commit", "origin/conflict/*"):
        assert rule in chat, rule
    assert "Monday" in (OPS.parent.parent / "company" / "agents" / "SKILLS.md").read_text()


def test_runner_uses_committed_prompt_and_posts_via_bridge(env):
    from tests.test_team_bridge import TOKEN, FakeBoardroom
    fake = FakeBoardroom()
    try:
        (env["team"] / "env").write_text(f"export JBHNTR_REPO={env['repo']}\nexport JBHNTR_APP_URL={fake.url}\n"
                                         f"export JBHNTR_ADMIN_TOKEN={TOKEN}\n")
        (env["repo"] / "ops/team/prompts/cycle.md").write_text("DIRTY working tree prompt\n")  # must be ignored
        assert run("cycle").returncode == 0
        prompt = (env["team"] / "prompt.txt").read_text()
        assert "BOARDROOM:" in prompt and "DIRTY" not in prompt
        assert f"Working dir: {env['repo']}" in prompt and "PARKED_BRANCHES: none" in prompt
        assert (env["team"] / "token.env").read_text().strip() == "TOKEN="  # agent never sees the token
        replies = [r["json"]["body"] for r in fake.requests if r["path"] == "/boardroom/reply"]
        assert replies == ["all done"]

        # a gate skip posts nothing to the chat
        git(env["repo"], "checkout", "-q", "--", "ops/team/prompts/cycle.md")
        assert run("cycle", STUB_ACTION='echo "SKIPPED: nothing unblocked"; exit 0').returncode == 0
        assert [r for r in fake.requests if r["path"] == "/boardroom/reply"] == [fake.requests[0]]
        assert "SKIPPED: nothing unblocked" in (env["team"] / "cycle.log").read_text()
    finally:
        fake.close()


def test_chat_mode_pulls_inbox_into_prompt(env):
    from tests.test_team_bridge import TOKEN, FakeBoardroom
    fake = FakeBoardroom(inbox=[{"id": 3, "body": "what shipped?", "created_at": None}])
    try:
        (env["team"] / "env").write_text(f"export JBHNTR_REPO={env['repo']}\nexport JBHNTR_APP_URL={fake.url}\n"
                                         f"export JBHNTR_ADMIN_TOKEN={TOKEN}\n")
        assert run("chat").returncode == 0
        prompt = (env["team"] / "prompt.txt").read_text()
        assert "replying in real time" in prompt and "what shipped?" in prompt
        assert [r["path"] for r in fake.requests] == ["/boardroom/peek", "/boardroom/pull", "/boardroom/reply"]
        assert fake.requests[-1]["json"]["body"] == "all done"
        n = len(fake.requests)
        assert run("chat").returncode == 0 and len(fake.requests) == n + 1  # empty inbox: peek only, no Claude
    finally:
        fake.close()


# --- R3-36: chat answers from its own clone while a cycle holds run.lock ---

def test_chat_runs_in_own_clone_while_cycle_holds_run_lock(env):
    import fcntl
    from tests.test_team_bridge import TOKEN, FakeBoardroom
    fake = FakeBoardroom(inbox=[{"id": 1, "body": "decide X", "created_at": None}])
    team, chat_wt = env["team"], env["team"] / "chat-wt"
    act = ('echo "CR=$CYCLE_RUNNING PWD=$PWD" > "$JBHNTR_TEAM/chat.env"; '
           'printf "decided\\n" > d.txt; git add d.txt; git commit -qm "chat: decision"')
    try:
        (team / "env").write_text(f"export JBHNTR_REPO={env['repo']}\nexport JBHNTR_APP_URL={fake.url}\n"
                                  f"export JBHNTR_ADMIN_TOKEN={TOKEN}\n")
        main_head = git(env["repo"], "rev-parse", "HEAD")
        with open(team / "run.lock", "w") as lock:  # the fake cycle
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert run("chat", STUB_ACTION=act).returncode == 0
            assert run("cycle").returncode == 0 and "[cycle] busy, skip" in (team / "cycle.log").read_text()
        assert (team / "chat.env").read_text().strip() == f"CR=1 PWD={chat_wt}"  # agent saw the running cycle
        assert "CYCLE_RUNNING: 1" in (team / "prompt.txt").read_text()
        assert f"Working dir: {chat_wt}" in (team / "prompt.txt").read_text()
        assert git(env["origin"], "show", "main:d.txt") == "decided"  # chat commit synced to origin
        assert git(env["repo"], "rev-parse", "HEAD") == main_head  # main clone untouched
        assert [r["json"]["body"] for r in fake.requests if r["path"] == "/boardroom/reply"] == ["all done"]

        # no cycle running -> CYCLE_RUNNING=0; a chat commit that truly conflicts is parked like any other mode
        fake.inbox = [{"id": 2, "body": "change a", "created_at": None}]
        git(env["other"], "pull", "-q", "--ff-only", "origin", "main")
        commit(env["other"], "a.txt", "1\nTHEIRS\n3\n", "their edit")  # pushed while the chat agent works
        act2 = ('echo "CR=$CYCLE_RUNNING" > "$JBHNTR_TEAM/chat.env"; printf "1\\nMINE\\n3\\n" > a.txt; '
                f'git commit -qam "chat: edit a"; git -C {env["other"]} push -q origin HEAD:main')
        theirs = git(env["other"], "rev-parse", "HEAD")
        r = run("chat", STUB_ACTION=act2)
        assert r.returncode == 0
        assert (team / "chat.env").read_text().strip() == "CR=0"
        assert origin_main(env) == theirs
        parked = [b for b in remote_branches(env) if b.startswith("conflict/chat-")]
        assert len(parked) == 1 and git(env["origin"], "show", f"{parked[0]}:a.txt") == "1\nMINE\n3"
    finally:
        fake.close()
