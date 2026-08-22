"""Security layer — path escape, command injection, secret exposure, write perms.

Layer Owner (see tests/doc/TEST_DEDUP_POLICY.md §2): symlink escape, command
injection and credential exposure. Expected values come from
`tests/doc/user-stories.md` + `tests/doc/testcases/security-testcases.md`, NOT
from the current implementation — several tests here assert a contract axt does
not satisfy yet and are meant to fail until it does.

OWASP tags are on each test's docstring; where no OWASP category genuinely
applies the docstring says so.
"""
from __future__ import annotations

import io
import json
import os
import stat
import subprocess
import sys
import tarfile
import threading
from pathlib import Path

import pytest

import axt
import axt.tui.tabs as tabs


posix_only = pytest.mark.skipif(sys.platform == "win32",
                                reason="symlink / POSIX permission semantics")


# ─── helpers ─────────────────────────────────────────────────────────────────


def _make_stdscr(rows: int = 40, cols: int = 160):
    """Fake curses screen recording every addnstr call (mirrors test_tui.py)."""
    from unittest.mock import MagicMock
    scr = MagicMock()
    scr.getmaxyx.return_value = (rows, cols)
    scr.calls = []
    scr.addnstr.side_effect = lambda *a: scr.calls.append(a)
    return scr


def _flat(scr) -> str:
    return "".join(c[2] for c in scr.calls if len(c) >= 3 and isinstance(c[2], str))


def _tree(root: Path) -> set:
    """Every path under `root` including broken symlinks (rglob skips those)."""
    out = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for n in list(dirnames) + list(filenames):
            out.add(os.path.join(dirpath, n))
    return out


def _isolate_home(tmp_path: Path, monkeypatch) -> Path:
    """Point every axt path constant at a throwaway HOME under tmp_path."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("axt.HOME", home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr("axt.PATHS", axt.Paths(
        claude_dir=home / ".claude",
        claude_config=home / ".claude.json",
        settings=home / ".claude" / "settings.json",
        known_marketplaces=home / ".claude" / "plugins" / "known_marketplaces.json",
        installed_plugins=home / ".claude" / "plugins" / "installed_plugins.json",
        marketplaces=home / ".claude" / "plugins" / "marketplaces",
        skills=home / ".claude" / "skills",
        projects=home / ".claude" / "projects",
        vault=home / ".axt" / "vault",
        vault_skills=home / ".axt" / "vault" / "skills",
        vault_commands=home / ".axt" / "vault" / "commands",
        vault_agents=home / ".axt" / "vault" / "agents",
    ))
    monkeypatch.setattr("axt.AXT_CONFIG_DIR", tmp_path / "axtcfg")
    monkeypatch.setattr("axt.AXT_CONFIG_PATH", tmp_path / "axtcfg" / "config.json")
    monkeypatch.setattr("axt.CACHE_DIR_FOR_USAGE", tmp_path / "axtcfg" / "cache")
    return home


class _RunSpy:
    """Records subprocess.run invocations without executing anything."""

    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = ""):
        self.calls: list[tuple[tuple, dict]] = []
        self._stdout, self._rc, self._stderr = stdout, returncode, stderr

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return subprocess.CompletedProcess(
            args[0] if args else kwargs.get("args"), self._rc, self._stdout, self._stderr)


def _skill_dir(path: Path, *, name: str = "s", version: str = "1.0.0") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: d\nversion: {version}\n---\nbody\n")
    return path


# ─── SC-SEC-001 — link creation path escape ──────────────────────────────────


@posix_only
def test_skill_link_rejects_parent_traversal_name(tmp_path, monkeypatch, capsys):
    """`skill link -n "../../pwn"` must not plant a symlink outside ~/.claude/skills.

    Prevents: a crafted `-n` value turning `axt skill link` into an arbitrary
    symlink-drop primitive anywhere the user can write (US-SYS08 AC1).
    OWASP: A01:2021 Broken Access Control (CWE-22 path traversal).
    """
    # TC-SEC-001
    home = _isolate_home(tmp_path, monkeypatch)
    (home / ".claude" / "skills").mkdir(parents=True, exist_ok=True)
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.chdir(proj)
    src = _skill_dir(tmp_path / "src-skill")

    before = _tree(tmp_path)
    rc = axt.main(["skill", "link", str(src), "-n", "../../pwn"])
    after = _tree(tmp_path)
    err = capsys.readouterr().err

    assert not os.path.lexists(home / "pwn"), "escaped the skills dir into HOME"
    assert after - before == set(), f"unexpected filesystem writes: {sorted(after - before)}"
    assert rc == 1
    assert "✗" in err


@posix_only
def test_skill_link_rejects_absolute_name(tmp_path, monkeypatch, capsys):
    """An absolute `-n` name must not reset the anchor out of the skills dir.

    Prevents: `Path(skills_dir) / "/abs"` evaluating to `/abs` in Python, so a
    boundary check that only looks for `..` still lets the link land anywhere
    (US-SYS08 AC2). OWASP: A01:2021 (CWE-22).
    """
    # TC-SEC-002
    home = _isolate_home(tmp_path, monkeypatch)
    skills = home / ".claude" / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    src = _skill_dir(tmp_path / "src-skill")
    # PID-suffixed so a parallel run of this suite cannot collide on /tmp.
    victim = Path(f"/tmp/axt-abs-pwn-{os.getpid()}")

    try:
        rc = axt.main(["skill", "link", str(src), "-n", str(victim)])
        capsys.readouterr()
        created = os.path.lexists(victim)
        assert not created, f"absolute -n escaped to {victim}"
        assert list(skills.iterdir()) == []
        assert rc == 1
    finally:
        if os.path.lexists(victim):
            victim.unlink()


@posix_only
def test_link_to_project_rejects_escaping_item_name(tmp_path, monkeypatch):
    """`link_to_project` must refuse a vault item whose name escapes .claude/<sub>.

    Prevents: a poisoned vault entry (or a hand-edited profile) writing symlinks
    outside the project's `.claude` tree — and, worse, that name being recorded
    in `.axt-profile.json` so every later `project sync` replays the escape
    (US-SYS08 AC1). OWASP: A01:2021 (CWE-22).
    """
    # TC-SEC-003
    _isolate_home(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    (proj / ".claude" / "skills").mkdir(parents=True)
    (proj / "sibling").mkdir()          # in-project escape target
    (tmp_path / "sibling").mkdir()      # out-of-project escape target
    monkeypatch.chdir(proj)
    vault_skill = _skill_dir(tmp_path / "vault" / "skills" / "real")

    item = axt.VaultItem(name="../../sibling/pwn", type="skill",
                         path=str(vault_skill), description="")
    with pytest.raises(ValueError):
        axt.link_to_project(proj, item)

    assert not os.path.lexists(proj / "sibling" / "pwn")
    assert not os.path.lexists(tmp_path / "sibling" / "pwn")
    # A failed link must not be recorded — otherwise `project sync` retries it.
    assert not (proj / ".axt-profile.json").exists()


# ─── SC-SEC-002 — unlink path escape ─────────────────────────────────────────


@posix_only
def test_vault_unlink_global_does_not_delete_home_dotfile(tmp_path, monkeypatch, capsys):
    """`vault unlink-global skill "../../.zshrc"` must not remove a HOME dotfile link.

    Prevents: the unlink path resolving `~/.claude/skills/../../.zshrc` to
    `~/.zshrc` and deleting a dotfile-manager symlink the user depends on
    (US-SYS08 AC1). OWASP: A01:2021 (CWE-22).
    """
    # TC-SEC-004
    home = _isolate_home(tmp_path, monkeypatch)
    (home / ".claude" / "skills").mkdir(parents=True, exist_ok=True)
    dotfiles = tmp_path / "dotfiles"
    dotfiles.mkdir()
    real_rc = dotfiles / "zshrc"
    real_rc.write_text("export PATH=/usr/bin\n")
    link = home / ".zshrc"
    os.symlink(real_rc, link)
    assert link.is_symlink()

    rc = axt.main(["vault", "unlink-global", "skill", "../../.zshrc"])
    out = capsys.readouterr().out

    assert link.is_symlink(), "the HOME dotfile symlink was deleted"
    assert os.path.realpath(link) == os.path.realpath(real_rc)
    assert "✓ Unlinked" not in out
    assert rc == 1


@posix_only
def test_vault_unlink_global_unknown_name_exits_1(tmp_path, monkeypatch, capsys):
    """`vault unlink-global` on a name absent from the vault must exit 1.

    Prevents: the unlink command silently succeeding on any string the user
    types while its `link-global` twin already exits 1 for the same lookup
    failure — an asymmetry that hides typos and makes the escape in TC-SEC-004
    reachable (US-VLT05 AC3). OWASP: A01:2021.
    """
    # TC-SEC-005
    home = _isolate_home(tmp_path, monkeypatch)
    (home / ".claude" / "skills").mkdir(parents=True, exist_ok=True)
    (home / ".axt" / "vault" / "skills").mkdir(parents=True)

    rc = axt.main(["vault", "unlink-global", "skill", "never-existed"])
    cap = capsys.readouterr()

    assert "✓" not in cap.out
    assert "not found" in (cap.out + cap.err).lower()
    assert rc == 1


@posix_only
def test_project_remove_does_not_delete_link_outside_claude_dir(tmp_path, monkeypatch, capsys):
    """`project remove skill "../../../victim"` must not unlink outside .claude/skills.

    Prevents: the project-scope unlink following `..` segments out of the
    project tree and destroying an unrelated symlink (US-SYS08 AC1).
    OWASP: A01:2021 (CWE-22).
    """
    # TC-SEC-006
    _isolate_home(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    (proj / ".claude" / "skills").mkdir(parents=True)
    monkeypatch.chdir(proj)
    real = tmp_path / "real"
    real.mkdir()
    victim = tmp_path / "victim"
    os.symlink(real, victim)

    rc = axt.main(["project", "remove", "skill", "../../../victim"])
    capsys.readouterr()

    assert victim.is_symlink(), "a symlink outside .claude/skills was removed"
    assert not (proj / ".axt-profile.json").exists()
    assert rc == 1


@posix_only
def test_skill_unlink_rejects_escaping_name(tmp_path, monkeypatch, capsys):
    """`skill unlink "../../outside-link"` must exit 1 and keep the outside link.

    Prevents: `axt skill unlink` deleting any symlink reachable by relative
    traversal from ~/.claude/skills. The message must name the boundary
    violation, not "is not a symlink" — a wrong diagnosis sends the user
    looking in the wrong place (US-SYS08 AC1). OWASP: A01:2021 (CWE-22).
    """
    # TC-SEC-007
    # The TC doc pairs `-n "../outside-link"` with a link at `home/outside-link`;
    # one `..` only reaches `home/.claude`. Two are used so the escape target
    # matches the documented location (HOME).
    home = _isolate_home(tmp_path, monkeypatch)
    (home / ".claude" / "skills").mkdir(parents=True, exist_ok=True)
    real = tmp_path / "real"
    real.mkdir()
    outside = home / "outside-link"
    os.symlink(real, outside)

    rc = axt.main(["skill", "unlink", "../../outside-link"])
    err = capsys.readouterr().err

    assert outside.is_symlink(), "a symlink in HOME was removed by `skill unlink`"
    assert rc == 1
    assert "not a symlink" not in err.lower(), (
        "boundary violation misreported as a type error: " + err.strip())


# ─── SC-SEC-003 — destructive delete scope ───────────────────────────────────


def test_remove_marketplace_spares_sibling_directory(tmp_path):
    """A sibling of the marketplaces dir must survive `remove_marketplace`.

    Prevents: ownership being decided by `str.startswith`, which makes
    `.../marketplaces-backup` look like a child of `.../marketplaces` and
    rmtree the user's backup (US-SYS08 AC4). OWASP: A01:2021.
    """
    # TC-SEC-009
    plugins = tmp_path / "plugins"
    mks = plugins / "marketplaces"
    mks.mkdir(parents=True)
    sib = plugins / "marketplaces-backup"
    sib.mkdir()
    (sib / "keepme.txt").write_text("user data")
    km = tmp_path / "km.json"
    km.write_text(json.dumps({
        "bad": {
            "source": {"source": "github", "repo": "x/y"},
            "installLocation": str(sib),
            "lastUpdated": "",
        },
        "other": {
            "source": {"source": "directory", "path": "/elsewhere"},
            "installLocation": "/elsewhere",
            "lastUpdated": "",
        },
    }))

    axt.remove_marketplace(km, mks, "bad")

    assert sib.exists(), "sibling directory of marketplaces/ was deleted"
    assert (sib / "keepme.txt").read_text() == "user data"
    assert set(json.loads(km.read_text())) == {"other"}


# ─── SC-SEC-004 — symlink-following delete ───────────────────────────────────


@posix_only
def test_unlink_from_global_does_not_recurse_through_symlinked_agents_dir(tmp_path, monkeypatch):
    """With ~/.claude/agents a symlink, unlink must not delete real files inside it.

    Prevents: a refactor swapping the `is_symlink()` guard for `exists()`, which
    would silently delete real content in whatever tree ~/.claude/agents points
    at (US-SYS08 AC3). OWASP: A01:2021 (CWE-59 link following).
    """
    # TC-SEC-013
    home = _isolate_home(tmp_path, monkeypatch)
    external = tmp_path / "external-agents"
    external.mkdir()
    (external / "keep.md").write_text("keep")
    (external / "x.md").write_text("agent x")
    agents_link = home / ".claude" / "agents"
    os.symlink(external, agents_link)

    vault_x = home / ".axt" / "vault" / "agents" / "x.md"
    vault_x.parent.mkdir(parents=True)
    vault_x.write_text("vault copy")

    axt.unlink_from_global(home / ".claude",
                           axt.VaultItem(name="x.md", type="agent",
                                         path=str(vault_x), description=""))

    assert (external / "keep.md").read_text() == "keep"
    assert (external / "x.md").exists(), "a real file behind the symlinked dir was deleted"
    assert agents_link.is_symlink(), "~/.claude/agents itself was removed"


# ─── SC-SEC-005 — external command argument injection ────────────────────────


def test_marketplace_name_with_shell_metacharacters_is_never_shell_evaluated(tmp_path, monkeypatch):
    """Shell metacharacters in a marketplace name reach git as one argv element.

    Prevents: a refactor building the git command line as an f-string with
    `shell=True`, which turns a registry name into arbitrary command execution
    (US-SYS06 AC1). OWASP: A03:2021 Injection (CWE-78).
    """
    # TC-SEC-014
    sentinel = tmp_path / "pwned"
    mks = tmp_path / "marketplaces"
    mks.mkdir()
    km = tmp_path / "km.json"
    name = f"evil; touch {sentinel}"

    spy = _RunSpy(stdout="deadbee\n")
    monkeypatch.setattr("axt.core.subprocess.run", spy)

    axt.add_marketplace(km, mks, name, axt.MarketplaceSource(kind="github", repo="o/r"))
    # The spy never really clones, so stand the git repo up by hand; sync then
    # takes the git branch instead of the network tarball branch.
    install = Path(json.loads(km.read_text())[name]["installLocation"])
    (install / ".git").mkdir(parents=True)
    axt.sync_marketplace(km, name)

    assert not sentinel.exists(), "the marketplace name was executed by a shell"
    assert spy.calls, "no git invocation was recorded — the test proved nothing"
    for args, kwargs in spy.calls:
        assert isinstance(args[0], list), f"argv is not a list: {args[0]!r}"
        assert kwargs.get("shell") is not True
    argv_elements = [e for args, _ in spy.calls for e in args[0]]
    assert any(name in e for e in argv_elements), (
        "the dangerous name was split across argv elements instead of staying whole")


def test_install_location_with_command_substitution_passes_through_verbatim(tmp_path, monkeypatch):
    """`$(...)` inside an install path is handed to git unescaped and unexecuted.

    Prevents: shelling out for `git rev-parse`, where a registry-controlled path
    would be command-substituted (US-SYS06 AC1). OWASP: A03:2021 (CWE-78).
    """
    # TC-SEC-015
    sentinel = tmp_path / "pwned-substitution"
    install = tmp_path / f"$(touch {sentinel})"
    (install / ".git").mkdir(parents=True)
    km = tmp_path / "km.json"
    km.write_text(json.dumps({
        "sub": {
            "source": {"source": "github", "repo": "o/r"},
            "installLocation": str(install),
            "lastUpdated": "",
        },
    }))

    spy = _RunSpy(stdout="cafe123\n")
    monkeypatch.setattr("axt.core.subprocess.run", spy)

    version = axt.get_local_version(km, "sub")

    assert not sentinel.exists(), "command substitution in the path was evaluated"
    assert version == "cafe123"
    argv = spy.calls[0][0][0]
    assert argv[:3] == ["git", "-C", str(install)]
    assert f"$(touch {sentinel})" in argv[2], "the path was escaped/mangled before argv"


# ─── SC-SEC-006 — `sh -c` hook preview isolation ─────────────────────────────


def _seed_hook_settings(path: Path, command: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "hooks": {
            "SessionStart": [
                {"hooks": [{"type": "command", "command": command}]},
            ],
        },
    }))


def test_hook_listing_and_render_never_shell_out(tmp_path, monkeypatch, capsys):
    """Listing or drawing hooks must not execute the hook command.

    Prevents: remote code execution from merely opening a repo — a cloned
    project's `.claude/settings.json` carries someone else's hook commands, and
    viewing them must stay inert (US-HK04 AC1).
    OWASP: A03:2021 in part — the design allows shell execution on explicit
    preview only; the risk is that path firing without user intent.
    """
    # TC-SEC-016
    home = _isolate_home(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    proj.mkdir()
    # Relative sentinel: the hook command has to stay short enough to survive
    # the Detail column's width clipping, or the "was it shown?" control
    # assertion below can never hold.
    sentinel = proj / "axt-hook-ran"
    _seed_hook_settings(home / ".claude" / "settings.json", "touch axt-hook-ran")
    monkeypatch.chdir(proj)

    spy = _RunSpy()
    monkeypatch.setattr("axt.core.subprocess.run", spy)

    rc = axt.main(["hook", "list"])
    out = capsys.readouterr().out

    state = axt.TuiState()
    state.ext_sub_tab = "hooks"
    tabs._ensure_subtab_loaded(state, "hooks")
    scr = _make_stdscr(rows=30, cols=140)
    axt.render_extensions_tab(scr, state, 2, 26, 140)
    axt.handle_extensions_input(state, ord("\t"))   # focus detail panel
    axt.render_extensions_tab(scr, state, 2, 26, 140)

    assert spy.calls == [], f"a subprocess was spawned while listing hooks: {spy.calls}"
    assert not sentinel.exists()
    assert rc == 0
    assert "touch axt-hook-ran" in out + _flat(scr), (
        "the hook command was not shown at all — the no-exec assertion is vacuous")


def test_hook_preview_key_runs_sh_c_exactly_once(tmp_path, monkeypatch):
    """`v` runs the hook through `sh -c` once, bounded, with HOOK_EVENT added.

    Prevents: preview losing its timeout (an interactive hook would hang the
    TUI forever), clobbering the inherited environment, or firing more than
    once per keypress (US-HK04 AC1, US-SYS06 AC3).
    OWASP: A03:2021 in part — this is the one intentionally shell-executing
    path, so its blast radius must stay pinned.
    """
    # TC-SEC-017
    home = _isolate_home(tmp_path, monkeypatch)
    monkeypatch.setenv("AXT_SEC_ENV_MARKER", "inherited")
    hook = axt.HookInfo(event="SessionStart", matcher="*", source="user",
                        source_path=str(home / ".claude" / "settings.json"),
                        type="command", command="echo hi")

    spy = _RunSpy(stdout="hello-out\n", stderr="hello-err\n", returncode=3)
    monkeypatch.setattr("axt.core.subprocess.run", spy)
    shown: list[str] = []
    monkeypatch.setattr("axt.tui.tabs.preview_modal",
                        lambda scr, text, **kw: shown.append(text))

    state = axt.TuiState()
    state.ext_sub_tab = "hooks"
    state.ext_cache["hooks"] = [hook]
    state.ext_selected["hooks"] = 0
    state.stdscr_callbacks = {"stdscr": _make_stdscr()}

    axt.handle_extensions_input(state, ord("v"))

    assert len(spy.calls) == 1, f"expected one shell invocation, got {len(spy.calls)}"
    args, kwargs = spy.calls[0]
    assert args[0] == ["sh", "-c", "echo hi"]
    assert kwargs.get("capture_output") is True
    assert kwargs.get("text") is True
    assert kwargs.get("timeout") and kwargs["timeout"] > 0
    env = kwargs.get("env") or {}
    assert env.get("HOOK_EVENT") == "SessionStart"
    assert env.get("AXT_SEC_ENV_MARKER") == "inherited", "inherited environment was dropped"
    assert len(shown) == 1
    assert "hello-out" in shown[0] and "hello-err" in shown[0] and "3" in shown[0]


# ─── SC-SEC-007 — untrusted archive extraction ───────────────────────────────


def _tar_with(members) -> io.BytesIO:
    """members: list of (name, "file"|"sym", linkname)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, kind, linkname in members:
            ti = tarfile.TarInfo(name)
            if kind == "file":
                payload = b"x"
                ti.size = len(payload)
                tf.addfile(ti, io.BytesIO(payload))
            else:
                ti.type = tarfile.SYMTYPE
                ti.linkname = linkname
                tf.addfile(ti)
    buf.seek(0)
    return buf


def _extract_branches(members, dest_root: Path):
    """Run `_safe_tar_extractall` under both guard branches.

    Python 3.12+ delegates to `tarfile.data_filter`; 3.9-3.11 runs axt's own
    validation loop. Forcing `data_filter = None` exercises the legacy loop on
    any interpreter, so both code paths are covered by one test run.
    Yields (branch_name, dest, raised_exception_or_None).
    """
    for branch in ("modern", "legacy"):
        if branch == "modern" and getattr(tarfile, "data_filter", None) is None:
            continue
        dest = dest_root / branch
        dest.mkdir(parents=True)
        saved = getattr(tarfile, "data_filter", None)
        if branch == "legacy":
            tarfile.data_filter = None
        try:
            raised = None
            try:
                with tarfile.open(fileobj=_tar_with(members), mode="r:gz") as tf:
                    axt._safe_tar_extractall(tf, dest)
            except Exception as exc:  # noqa: BLE001 — the assertion inspects it
                raised = exc
        finally:
            if branch == "legacy":
                if saved is None:
                    delattr(tarfile, "data_filter")
                else:
                    tarfile.data_filter = saved
        yield branch, dest, raised


def test_tar_traversal_member_is_rejected_on_both_guard_branches(tmp_path):
    """A `../escape.txt` member is refused whichever tar guard is active.

    Prevents: a marketplace tarball writing outside its install dir. The two
    guard branches diverge by interpreter version, so a fix applied to only one
    leaves half the userbase exposed (US-MKT01).
    OWASP: A08:2021 Software and Data Integrity Failures (CWE-22 / CVE-2007-4559).
    """
    # TC-SEC-019
    ran = 0
    for branch, dest, raised in _extract_branches([("../escape.txt", "file", None)],
                                                  tmp_path / "t19"):
        ran += 1
        assert not (dest.parent / "escape.txt").exists(), f"[{branch}] wrote outside dest"
        assert isinstance(raised, RuntimeError), f"[{branch}] expected RuntimeError, got {raised!r}"
        assert "unsafe" in str(raised).lower()
    assert ran >= 1


def test_tar_absolute_member_is_rejected_on_both_guard_branches(tmp_path):
    """An absolute member name is refused whichever tar guard is active.

    Prevents: an absolute path in a tarball landing at the filesystem root.
    Both branches must reach the same verdict, so a marketplace does not install
    on one interpreter and fail on another (US-MKT01).
    OWASP: A08:2021 (CWE-22).
    """
    # TC-SEC-020
    victim = Path(f"/tmp/axt-tar-abs-{os.getpid()}.txt")
    try:
        ran = 0
        for branch, dest, raised in _extract_branches([(str(victim), "file", None)],
                                                      tmp_path / "t20"):
            ran += 1
            assert not victim.exists(), f"[{branch}] absolute member escaped to {victim}"
            assert isinstance(raised, RuntimeError), (
                f"[{branch}] expected RuntimeError for an absolute member, got {raised!r}")
        assert ran >= 1
    finally:
        if victim.exists():
            victim.unlink()


def test_tar_symlink_pointing_outside_is_rejected_on_both_guard_branches(tmp_path):
    """A symlink member whose target escapes `dest` is refused on both branches.

    Prevents: a two-stage attack — extraction looks safe, then later code that
    writes through the planted link overwrites arbitrary files. A path-only
    check never sees it because the member's own name is innocent (US-MKT01).
    OWASP: A08:2021 (CWE-22 / CWE-59).
    """
    # TC-SEC-021
    ran = 0
    for branch, dest, raised in _extract_branches([("link.txt", "sym", "../../outside")],
                                                  tmp_path / "t21"):
        ran += 1
        assert not os.path.lexists(dest.parent.parent / "outside")
        assert list(dest.iterdir()) == [], f"[{branch}] the link member was extracted"
        assert isinstance(raised, RuntimeError), f"[{branch}] expected RuntimeError, got {raised!r}"
        assert "unsafe" in str(raised).lower()
    assert ran >= 1


# ─── SC-SEC-008 — adversarial JSON ───────────────────────────────────────────


def test_deeply_nested_settings_json_falls_back_to_empty_map(tmp_path):
    """20,000-deep nesting in settings.json must yield {} rather than blow the stack.

    Prevents: a hostile (or merely generated) settings file taking the whole CLI
    down with a RecursionError that no caller catches (US-SYS05 AC1).
    OWASP: A08:2021 in part — untrusted structured data driving a crash.
    """
    # TC-SEC-022
    settings = tmp_path / "settings.json"
    # sys.setrecursionlimit is deliberately NOT touched: leaking global
    # interpreter state into sibling tests is worse than the bug under test.
    settings.write_text("[" * 20_000 + "]" * 20_000)

    assert axt.read_enabled_plugins(settings) == {}


def test_partially_corrupt_settings_bucket_falls_back_and_write_preserves_other_keys(tmp_path):
    """`enabledPlugins` as a list reads as {} and a later write keeps other keys.

    Prevents: real-world partial corruption (the wrong type under a known key)
    breaking every subsequent settings write, or the repair blowing away
    unrelated user configuration (US-SYS05 AC1).
    OWASP: A08:2021 in part.
    """
    # TC-SEC-023
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"enabledPlugins": ["alpha", "beta"], "otherKey": 1}))

    assert axt.read_enabled_plugins(settings) == {}

    axt.set_plugin_enabled(settings, "alpha", True)
    data = json.loads(settings.read_text())
    assert data["enabledPlugins"] == {"alpha": True}
    assert data["otherKey"] == 1, "an unrelated settings key was lost repairing the bucket"


def test_large_non_json_marketplace_registry_yields_empty_list(tmp_path):
    """A 5MB non-JSON known_marketplaces.json lists as [] instead of raising.

    Prevents: a truncated/garbage registry crashing the TUI, whose sub-tab
    loader does not wrap `list_marketplaces` (US-SYS05 AC1).
    OWASP: A08:2021 in part.
    """
    # TC-SEC-024
    import time
    km = tmp_path / "known_marketplaces.json"
    km.write_text("lorem ipsum " * 450_000)   # ~5.4MB
    assert km.stat().st_size > 5_000_000

    t0 = time.perf_counter()
    result = axt.list_marketplaces(km)
    elapsed = time.perf_counter() - t0

    assert result == []
    # A parse failure must bail immediately, not scan the whole buffer twice.
    assert elapsed < 5.0, f"took {elapsed:.2f}s"


# ─── SC-SEC-009 — MCP credential exposure ────────────────────────────────────


TOKEN = "ghp_LIVEKEY0000000000000000000000000000"


def _seed_mcp_config(tmp_path: Path, monkeypatch) -> Path:
    home = _isolate_home(tmp_path, monkeypatch)
    (home / ".claude.json").write_text(json.dumps({
        "mcpServers": {
            "gh": {
                "command": "node",
                "args": ["s.js"],
                "env": {"GITHUB_TOKEN": TOKEN, "DEBUG": "1"},
            },
        },
    }))
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    monkeypatch.chdir(proj)
    return home


def test_mcp_list_never_prints_env_values(tmp_path, monkeypatch, capsys):
    """`axt mcp list` must not print MCP env values.

    Prevents: a live API token scrolling past during a screen share or landing
    in a pasted bug report (US-MCP05 AC1).
    OWASP: A02:2021 Cryptographic Failures (sensitive data exposure).
    """
    # TC-SEC-025
    _seed_mcp_config(tmp_path, monkeypatch)
    rc = axt.main(["mcp", "list"])
    out = capsys.readouterr().out

    assert rc == 0
    assert TOKEN not in out
    assert "gh" in out, "the server row vanished — the no-token assertion is vacuous"


def test_mcp_info_masks_env_values(tmp_path, monkeypatch, capsys):
    """`axt mcp info` must mask env values while still naming the keys.

    Prevents: the detail command dumping `json.dumps(env)` verbatim. Key names
    must survive so the user can still tell what is configured (US-MCP05 AC2).
    OWASP: A02:2021.
    """
    # TC-SEC-026
    _seed_mcp_config(tmp_path, monkeypatch)
    rc = axt.main(["mcp", "info", "gh"])
    out = capsys.readouterr().out

    assert rc == 0
    assert TOKEN not in out, "the raw token was printed by `mcp info`"
    assert "GITHUB_TOKEN" in out, "the env key name must stay visible for diagnosis"


def test_tui_mcp_detail_panel_masks_env_values(tmp_path, monkeypatch):
    """The TUI MCP detail panel must mask env values too.

    Prevents: fixing only the CLI while the TUI keeps leaking — and the TUI is
    what is on screen during a demo or a pairing session (US-MCP05 AC3).
    OWASP: A02:2021.
    """
    # TC-SEC-027
    _seed_mcp_config(tmp_path, monkeypatch)
    state = axt.TuiState()
    state.ext_sub_tab = "mcp"
    tabs._ensure_subtab_loaded(state, "mcp")
    servers = state.ext_cache["mcp"]
    state.ext_cache["mcp"] = [s for s in servers if s.name == "gh"]
    assert state.ext_cache["mcp"], "fixture server missing — nothing would be rendered"
    state.ext_selected["mcp"] = 0

    scr = _make_stdscr(rows=40, cols=160)
    axt.render_extensions_tab(scr, state, 2, 36, 160)
    flat = _flat(scr)

    assert TOKEN not in flat, "the raw token was drawn into the detail panel"
    assert "GITHUB_TOKEN" in flat, "the env key name must stay visible for diagnosis"


# ─── SC-SEC-010 — atomic write permissions & concurrency ─────────────────────


@posix_only
def test_write_json_atomic_preserves_restrictive_file_mode(tmp_path):
    """Rewriting a 0600 file must leave it 0600, and its .bak no wider.

    Prevents: the temp-file + os.replace dance widening a credential file to the
    default umask (0644), and the best-effort `.bak` copy becoming a
    world-readable second copy of the same secret (US-SYS04 AC1).
    OWASP: A05:2021 Security Misconfiguration.
    """
    # TC-SEC-028
    target = tmp_path / "claude.json"
    target.write_text(json.dumps({"oauthAccount": {"accessToken": "old"}}))
    os.chmod(target, 0o600)

    axt.write_json_atomic(target, {"oauthAccount": {"accessToken": "secret"}})

    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600, f"permissions widened to {oct(mode)}"
    bak = target.with_suffix(".json.bak")
    if bak.exists():
        bak_mode = stat.S_IMODE(bak.stat().st_mode)
        assert bak_mode & 0o077 == 0, (
            f"backup is wider than the original ({oct(bak_mode)}) — it becomes the leak")


def test_concurrent_write_json_atomic_never_leaves_a_mixed_file(tmp_path):
    """Two threads writing the same path leave one whole payload, never a blend.

    Prevents: axt's pre-replace work (mkdir + `.bak` copy + temp create) racing
    between the TUI's three daemon writers. `os.replace` atomicity is an OS
    guarantee; the ordering around it is axt's (US-SYS04 AC3).
    OWASP: not applicable — concurrency integrity is not an OWASP category.
    """
    # TC-SEC-029
    target = tmp_path / "cache.json"
    payloads = {"A": {"who": "A", "pad": "a" * 10},
                "B": {"who": "B", "pad": "b" * 20_000}}
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def writer(which: str) -> None:
        try:
            barrier.wait(timeout=5)
            axt.write_json_atomic(target, payloads[which])
        except BaseException as exc:  # noqa: BLE001 — surfaced by the assertion below
            errors.append(exc)

    for _ in range(50):
        barrier.reset()
        threads = [threading.Thread(target=writer, args=(w,)) for w in ("A", "B")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
            assert not t.is_alive(), "writer thread hung"
        data = json.loads(target.read_text())
        expected = len(payloads[data["who"]]["pad"])
        assert len(data["pad"]) == expected, (
            f"payloads blended: who={data['who']} pad_len={len(data['pad'])}")

    assert errors == []
    assert list(tmp_path.glob(".tmp-*.json")) == [], "temp files were left behind"
