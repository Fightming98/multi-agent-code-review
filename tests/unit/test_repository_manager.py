"""Repository Manager 的单元测试：URL 前置校验、Clone 安全选项、
Commit SHA 固定、资源限制与工作区清理。

全部使用 FakeGitClient 或本地子进程，不访问网络、不 Clone 真实仓库。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from config.settings import Settings
from src.code_review.tools.repository_manager import (
    CloneError,
    CommitResolutionError,
    GitClient,
    GitNotFoundError,
    GitResult,
    GitTimeoutError,
    RepositoryError,
    RepositoryManager,
    ResourceLimitExceededError,
)
from src.code_review.tools.url_validator import URLValidationError

FULL_SHA = "9fceb02d0ae598e95dc970b74767f19372d61af8"
OTHER_SHA = "1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d"
REPOSITORY_URL = "https://github.com/pallets/itsdangerous"
CANONICAL_URL = "https://github.com/pallets/itsdangerous"


class FakeGitClient:
    """在本地文件系统上模拟 Git 行为的最小客户端。"""

    def __init__(self, *, branch: str = "main", tip_sha: str = FULL_SHA) -> None:
        self.branch = branch
        self.tip_sha = tip_sha
        self.head_sha = tip_sha
        self.calls: list[list[str]] = []
        self.clone_returncode = 0
        self.clone_stderr = "fatal: simulated clone failure"
        self.clone_files: dict[str, bytes] = {"example.py": b"print('hi')\n"}
        self.after_checkout_sha: str | None = None
        self.version_string = "git version 2.45.0"

    def version(self) -> str:
        return self.version_string

    def run(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        timeout: float = 300,
        size_guard: object | None = None,
        isolated_config: Path | None = None,
    ) -> GitResult:
        recorded = list(args)
        self.calls.append(recorded)

        if recorded[0] == "clone":
            return self._run_clone(recorded)

        assert recorded[0] == "-C"
        workspace = Path(recorded[1])
        assert workspace.is_dir()
        git_args = recorded[2:]

        if git_args == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return GitResult(0, f"{self.branch}\n", "")
        if git_args == ["symbolic-ref", "--short", "HEAD"]:
            return GitResult(0, f"{self.branch}\n", "")
        if git_args == ["rev-parse", "--verify", "HEAD^{commit}"]:
            return GitResult(0, f"{self.head_sha}\n", "")
        if git_args[0] == "fetch":
            return GitResult(0, "", "")
        if git_args[0] == "checkout":
            target = git_args[-1]
            self.head_sha = self.after_checkout_sha or target
            return GitResult(0, "", "")
        raise AssertionError(f"unexpected git command: {git_args}")

    def _run_clone(self, args: list[str]) -> GitResult:
        if self.clone_returncode != 0:
            return GitResult(self.clone_returncode, "", self.clone_stderr)
        destination = Path(args[-1])
        destination.mkdir(parents=True, exist_ok=True)
        for relative, content in self.clone_files.items():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        self.head_sha = self.tip_sha
        return GitResult(0, "", "")

    def clone_call(self) -> list[str]:
        for call in self.calls:
            if call[0] == "clone":
                return call
        raise AssertionError("no clone call recorded")

    def git_calls(self) -> list[list[str]]:
        return [call[2:] for call in self.calls if call[0] == "-C"]


def make_manager(
    tmp_path: Path,
    fake: FakeGitClient | None = None,
    **overrides: object,
) -> tuple[RepositoryManager, FakeGitClient]:
    values: dict[str, object] = {
        "workspace_root": str(tmp_path / "workspaces"),
        "git_clone_timeout_seconds": 30,
        "git_command_timeout_seconds": 30,
    }
    values.update(overrides)
    settings = Settings(_env_file=None, **values)
    client = fake if fake is not None else FakeGitClient()
    return RepositoryManager(settings, git_client=client), client


def test_invalid_url_is_rejected_before_git(tmp_path: Path) -> None:
    manager, fake = make_manager(tmp_path)

    with pytest.raises(URLValidationError):
        manager.clone("http://github.com/pallets/itsdangerous")

    assert fake.calls == []


def test_invalid_branch_is_rejected_before_git(tmp_path: Path) -> None:
    manager, fake = make_manager(tmp_path)

    with pytest.raises(URLValidationError):
        manager.clone(REPOSITORY_URL, branch="-upload-pack=evil")

    assert fake.calls == []


def test_invalid_sha_is_rejected_before_git(tmp_path: Path) -> None:
    manager, fake = make_manager(tmp_path)

    with pytest.raises(URLValidationError):
        manager.clone(REPOSITORY_URL, commit_sha=FULL_SHA[:7])

    assert fake.calls == []


def test_successful_clone_returns_pinned_snapshot(tmp_path: Path) -> None:
    fake = FakeGitClient()
    manager, _ = make_manager(tmp_path, fake)

    snapshot = manager.clone(REPOSITORY_URL)

    assert snapshot.owner == "pallets"
    assert snapshot.name == "itsdangerous"
    assert snapshot.full_name == "pallets/itsdangerous"
    assert snapshot.repository_url == CANONICAL_URL
    assert snapshot.branch == "main"
    assert snapshot.commit_sha == FULL_SHA
    assert snapshot.workspace_path.is_dir()
    assert snapshot.workspace_path.parent == Path(
        manager.settings.workspace_root
    ).expanduser().resolve()
    assert snapshot.file_count == 1
    assert snapshot.size_bytes > 0
    assert snapshot.git_version == "git version 2.45.0"
    assert snapshot.cloned_at.tzinfo is not None

    manager.cleanup(snapshot)


def test_clone_command_uses_security_options(tmp_path: Path) -> None:
    fake = FakeGitClient()
    manager, _ = make_manager(tmp_path, fake)

    snapshot = manager.clone(REPOSITORY_URL)

    args = fake.clone_call()
    joined = " ".join(args)
    assert "clone" in args
    assert "--no-checkout" in args
    assert "--depth=1" in args
    assert "--single-branch" in args
    assert "--no-recurse-submodules" in args
    assert "http.followRedirects=false" in joined
    assert "http.sslVerify=true" in joined
    assert "core.symlinks=false" in joined
    assert "core.fsmonitor=false" in joined
    assert "submodule.recurse=false" in joined
    assert "credential.helper=" in joined
    assert "protocol.file.allow=never" in joined
    assert args[-3:] == ["--", CANONICAL_URL, str(snapshot.workspace_path)]

    manager.cleanup(snapshot)


def test_branch_is_passed_to_clone(tmp_path: Path) -> None:
    fake = FakeGitClient(branch="feature/add-url-validation")
    manager, _ = make_manager(tmp_path, fake)

    snapshot = manager.clone(REPOSITORY_URL, branch="feature/add-url-validation")

    args = fake.clone_call()
    index = args.index("--branch")
    assert args[index + 1] == "feature/add-url-validation"
    assert snapshot.branch == "feature/add-url-validation"

    manager.cleanup(snapshot)


def test_requested_sha_is_fetched_and_checked_out(tmp_path: Path) -> None:
    fake = FakeGitClient(tip_sha=FULL_SHA)
    manager, _ = make_manager(tmp_path, fake)

    snapshot = manager.clone(REPOSITORY_URL, commit_sha=OTHER_SHA.upper())

    calls = fake.git_calls()
    assert ["fetch", "--quiet", "--depth=1", "origin", OTHER_SHA] in calls
    assert ["checkout", "--quiet", "--detach", OTHER_SHA] in calls
    assert snapshot.commit_sha == OTHER_SHA

    manager.cleanup(snapshot)


def test_commit_mismatch_raises_and_cleans_workspace(tmp_path: Path) -> None:
    fake = FakeGitClient(tip_sha=FULL_SHA)
    fake.after_checkout_sha = FULL_SHA
    manager, _ = make_manager(tmp_path, fake)

    with pytest.raises(CommitResolutionError):
        manager.clone(REPOSITORY_URL, commit_sha=OTHER_SHA)

    assert list((tmp_path / "workspaces").iterdir()) == []


def test_clone_failure_raises_and_cleans_workspace(tmp_path: Path) -> None:
    fake = FakeGitClient()
    fake.clone_returncode = 128
    manager, _ = make_manager(tmp_path, fake)

    with pytest.raises(CloneError) as excinfo:
        manager.clone(REPOSITORY_URL)

    assert "git clone failed" in str(excinfo.value)
    assert list((tmp_path / "workspaces").iterdir()) == []


def test_timeout_propagates_and_cleans_workspace(tmp_path: Path) -> None:
    class TimeoutGitClient(FakeGitClient):
        def run(self, args: list[str], **kwargs: object) -> GitResult:
            raise GitTimeoutError("git command timed out")

    manager, _ = make_manager(tmp_path, TimeoutGitClient())

    with pytest.raises(GitTimeoutError):
        manager.clone(REPOSITORY_URL)

    assert list((tmp_path / "workspaces").iterdir()) == []


def test_keep_workspace_on_failure(tmp_path: Path) -> None:
    fake = FakeGitClient()
    fake.clone_returncode = 128
    manager, _ = make_manager(tmp_path, fake, keep_workspace_on_failure=True)

    with pytest.raises(CloneError):
        manager.clone(REPOSITORY_URL)

    workspaces = [path for path in (tmp_path / "workspaces").iterdir() if path.is_dir()]
    assert len(workspaces) == 1

    manager.cleanup_all()
    assert list((tmp_path / "workspaces").iterdir()) == []


def test_repository_size_limit_is_enforced(tmp_path: Path) -> None:
    fake = FakeGitClient()
    fake.clone_files = {"big.bin": b"x" * (1024 * 1024 + 1)}
    manager, _ = make_manager(tmp_path, fake, max_repository_size_mb=1)

    with pytest.raises(ResourceLimitExceededError):
        manager.clone(REPOSITORY_URL)

    assert list((tmp_path / "workspaces").iterdir()) == []


def test_file_count_limit_is_enforced(tmp_path: Path) -> None:
    fake = FakeGitClient()
    fake.clone_files = {
        "a.py": b"",
        "b.py": b"",
        "c.py": b"",
    }
    manager, _ = make_manager(tmp_path, fake, max_file_count=2)

    with pytest.raises(ResourceLimitExceededError):
        manager.clone(REPOSITORY_URL)


def test_file_count_ignores_git_directory(tmp_path: Path) -> None:
    fake = FakeGitClient()
    fake.clone_files = {
        ".git/config": b"",
        ".git/objects/aa/bb": b"",
        "a.py": b"",
        "b.py": b"",
    }
    manager, _ = make_manager(tmp_path, fake, max_file_count=2)

    snapshot = manager.clone(REPOSITORY_URL)

    assert snapshot.file_count == 2
    manager.cleanup(snapshot)


def test_oversized_files_are_detected_and_recorded(tmp_path: Path) -> None:
    fake = FakeGitClient()
    fake.clone_files = {
        "big.bin": b"x" * (1024 * 1024 + 1),
        "small.py": b"",
    }
    manager, _ = make_manager(tmp_path, fake, max_single_file_size_mb=1)

    snapshot = manager.clone(REPOSITORY_URL)

    assert snapshot.oversized_files == ("big.bin",)
    assert snapshot.file_count == 2
    manager.cleanup(snapshot)


def test_destination_outside_workspace_root_is_rejected(tmp_path: Path) -> None:
    manager, fake = make_manager(tmp_path)

    with pytest.raises(RepositoryError):
        manager.clone(REPOSITORY_URL, destination=tmp_path / "outside")

    assert fake.calls == []


def test_destination_must_be_empty(tmp_path: Path) -> None:
    manager, _ = make_manager(tmp_path)
    destination = tmp_path / "workspaces" / "existing"
    destination.mkdir(parents=True)
    (destination / "stale.txt").write_text("stale", encoding="utf-8")

    with pytest.raises(RepositoryError):
        manager.clone(REPOSITORY_URL, destination=destination)


def test_empty_destination_is_accepted(tmp_path: Path) -> None:
    manager, _ = make_manager(tmp_path)
    destination = tmp_path / "workspaces" / "fresh"

    snapshot = manager.clone(REPOSITORY_URL, destination=destination)

    assert snapshot.workspace_path == destination.resolve()
    manager.cleanup(snapshot)
    assert not destination.exists()


def test_cleanup_rejects_unmanaged_workspace(tmp_path: Path) -> None:
    manager, _ = make_manager(tmp_path)
    outsider = tmp_path / "not-managed"
    outsider.mkdir()

    with pytest.raises(RepositoryError):
        manager.cleanup(outsider)

    assert outsider.exists()


def test_context_manager_cleans_workspaces(tmp_path: Path) -> None:
    fake = FakeGitClient()
    settings = Settings(
        _env_file=None,
        workspace_root=str(tmp_path / "workspaces"),
    )
    with RepositoryManager(settings, git_client=fake) as manager:
        snapshot = manager.clone(REPOSITORY_URL)
        assert snapshot.workspace_path.exists()

    assert list((tmp_path / "workspaces").iterdir()) == []


def test_isolated_config_is_removed(tmp_path: Path) -> None:
    manager, _ = make_manager(tmp_path)

    snapshot = manager.clone(REPOSITORY_URL)

    leftovers = list((tmp_path / "workspaces").glob("code_review_gitconfig_*"))
    assert leftovers == []

    manager.cleanup(snapshot)


def test_workspace_root_must_be_directory(tmp_path: Path) -> None:
    path = tmp_path / "root-file"
    path.write_text("not a directory", encoding="utf-8")
    settings = Settings(_env_file=None, workspace_root=str(path))

    with pytest.raises(RepositoryError):
        RepositoryManager(settings, git_client=FakeGitClient())


def test_git_client_invocation_is_shell_free(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class DummyProcess:
        returncode = 0

        def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
            return b"git version 2.45.0\n", b""

        def poll(self) -> int:
            return 0

        def wait(self, timeout: float | None = None) -> int:
            return 0

    def fake_popen(command: list[str], **kwargs: object) -> DummyProcess:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return DummyProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setenv("LLM_API_KEY", "should-not-leak")

    result = GitClient("git").run(["--version"], timeout=5)

    assert result.returncode == 0
    assert result.stdout.startswith("git version")
    assert captured["command"] == ["git", "--version"]
    kwargs = captured["kwargs"]
    assert kwargs["shell"] is False
    assert kwargs["stdin"] == subprocess.DEVNULL
    env = kwargs["env"]
    assert isinstance(env, dict)
    assert "LLM_API_KEY" not in env
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_ALLOW_PROTOCOL"] == "https"


def test_git_client_missing_executable_raises() -> None:
    client = GitClient("definitely-not-a-real-git-binary-xyz")

    with pytest.raises(GitNotFoundError):
        client.run(["--version"], timeout=5)


def test_git_client_timeout_terminates_process() -> None:
    client = GitClient(executable=sys.executable, poll_interval=0.05)
    started = time.monotonic()

    with pytest.raises(GitTimeoutError):
        client.run(["-c", "import time; time.sleep(30)"], timeout=0.2)

    assert time.monotonic() - started < 10


def test_git_client_size_guard_terminates_process() -> None:
    client = GitClient(executable=sys.executable, poll_interval=0.05)

    def guard() -> None:
        raise ResourceLimitExceededError("simulated size limit")

    with pytest.raises(ResourceLimitExceededError):
        client.run(
            ["-c", "import time; time.sleep(30)"],
            timeout=30,
            size_guard=guard,
        )
