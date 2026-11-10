"""GitHub 仓库获取、Commit SHA 固定与工作区资源限制。

所有 Git 调用都使用参数数组、``shell=False``、隔离的 Git 配置与受限环境；
只允许 HTTPS GitHub 地址，禁止子模块、重定向、符号链接与 Git Hook 影响。
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from config.settings import Settings

from .url_validator import (
    GitHubRepository,
    is_full_commit_sha,
    normalize_commit_sha,
    validate_branch_name,
    validate_github_url,
)

_MAX_GIT_OUTPUT_CHARS = 64 * 1024
_POLL_INTERVAL_SECONDS = 0.5


class RepositoryError(RuntimeError):
    """仓库获取链路的基础异常。"""


class GitNotFoundError(RepositoryError):
    """Git 可执行文件不存在。"""


class GitTimeoutError(RepositoryError):
    """Git 命令超过配置的超时时间。"""


class CloneError(RepositoryError):
    """Git Clone 失败。"""


class CommitResolutionError(RepositoryError):
    """Commit SHA 无法解析、获取或校验。"""


class ResourceLimitExceededError(RepositoryError):
    """仓库大小或文件数量超过配置上限。"""


@dataclass(frozen=True)
class GitResult:
    """一次 Git 子进程的执行结果。"""

    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class RepositorySnapshot:
    """一次成功获取并固定 Commit 的仓库快照。"""

    owner: str
    name: str
    repository_url: str
    branch: str
    commit_sha: str
    workspace_path: Path
    cloned_at: datetime
    size_bytes: int
    file_count: int
    git_version: str
    oversized_files: tuple[str, ...] = ()

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


class GitClient:
    """带超时、进程树终止与输出上限的 Git 子进程封装。"""

    def __init__(
        self,
        executable: str = "git",
        poll_interval: float = _POLL_INTERVAL_SECONDS,
    ) -> None:
        self.executable = executable
        self.poll_interval = poll_interval
        self._version: str | None = None

    def version(self) -> str:
        """返回 Git 版本字符串；结果在进程内缓存。"""

        if self._version is None:
            result = self.run(["--version"], timeout=30)
            if result.returncode != 0:
                raise RepositoryError("unable to determine git version")
            self._version = result.stdout.strip()
        return self._version

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        timeout: float = 300,
        size_guard: Callable[[], None] | None = None,
        isolated_config: Path | None = None,
    ) -> GitResult:
        """执行 Git 命令。

        ``size_guard`` 在每个轮询周期被调用；若其抛出异常，子进程树会被终止。
        超时同样会终止整个进程树，而不是只终止 Git 主进程。
        """

        command = [self.executable, *args]
        env = self._build_env(isolated_config)
        kwargs: dict[str, object] = {
            "cwd": str(cwd) if cwd is not None else None,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "shell": False,
            "env": env,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

        try:
            process = subprocess.Popen(command, **kwargs)  # type: ignore[arg-type]
        except FileNotFoundError as exc:
            raise GitNotFoundError(f"git executable not found: {self.executable}") from exc
        except OSError as exc:
            raise RepositoryError("unable to start git process") from exc

        deadline = time.monotonic() + max(timeout, 0.001)
        stdout_bytes: bytes | None = None
        stderr_bytes: bytes | None = None

        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._terminate_tree(process)
                    stdout_bytes, stderr_bytes = self._communicate_quietly(process)
                    raise GitTimeoutError(
                        f"git command timed out after {timeout:g} seconds"
                    )

                try:
                    stdout_bytes, stderr_bytes = process.communicate(
                        timeout=min(self.poll_interval, remaining)
                    )
                    break
                except subprocess.TimeoutExpired:
                    if size_guard is not None:
                        try:
                            size_guard()
                        except BaseException:
                            self._terminate_tree(process)
                            self._communicate_quietly(process)
                            raise
        finally:
            if process.poll() is None:
                self._terminate_tree(process)

        return GitResult(
            returncode=process.returncode if process.returncode is not None else -1,
            stdout=self._bounded(self._decode(stdout_bytes)),
            stderr=self._bounded(self._decode(stderr_bytes)),
        )

    def _build_env(self, isolated_config: Path | None) -> dict[str, str]:
        """构造最小化且禁用到外部 Git 配置的环境变量。"""

        env = {
            "PATH": os.environ.get("PATH", ""),
            "SystemRoot": os.environ.get("SystemRoot", ""),
            "COMSPEC": os.environ.get("COMSPEC", ""),
            "TEMP": os.environ.get("TEMP", ""),
            "TMP": os.environ.get("TMP", ""),
            "HOME": os.environ.get("HOME", ""),
            "USERPROFILE": os.environ.get("USERPROFILE", ""),
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": (
                str(isolated_config) if isolated_config is not None else os.devnull
            ),
            "GIT_ALLOW_PROTOCOL": "https",
            "GIT_PROTOCOL_FROM_USER": "0",
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_LFS_SKIP_SMUDGE": "1",
            "GIT_PAGER": "cat",
            "PAGER": "cat",
            "TERM": "dumb",
            "NO_COLOR": "1",
            "LC_ALL": "C",
        }
        return {key: value for key, value in env.items() if value != ""}

    @staticmethod
    def _decode(data: bytes | None) -> str:
        if not data:
            return ""
        return data.decode("utf-8", errors="replace")

    @staticmethod
    def _bounded(text: str) -> str:
        if len(text) <= _MAX_GIT_OUTPUT_CHARS:
            return text
        return text[:_MAX_GIT_OUTPUT_CHARS] + "\n...[output truncated]"

    @staticmethod
    def _communicate_quietly(process: subprocess.Popen[bytes]) -> tuple[bytes, bytes]:
        try:
            return process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                return process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                return b"", b""

    @staticmethod
    def _terminate_tree(process: subprocess.Popen[bytes]) -> None:
        """终止 Git 及其子进程，避免超时后残留后台进程。"""

        if process.poll() is not None:
            return

        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        else:
            try:
                os.killpg(os.getpgid(process.pid), 9)
            except (ProcessLookupError, PermissionError, OSError):
                pass

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


class RepositoryManager:
    """GitHub 仓库获取与工作区生命周期管理。"""

    def __init__(self, settings: Settings, git_client: GitClient | None = None) -> None:
        self.settings = settings
        self.git = git_client or GitClient(settings.git_executable)

        root = (
            Path(settings.workspace_root).expanduser()
            if settings.workspace_root
            else Path(tempfile.gettempdir())
        )
        self._workspace_root = root.resolve()
        if self._workspace_root.exists() and not self._workspace_root.is_dir():
            raise RepositoryError("workspace_root must be a directory")
        self._workspace_root.mkdir(parents=True, exist_ok=True)
        self._managed_workspaces: set[Path] = set()

    def clone(
        self,
        repository_url: str,
        *,
        branch: str | None = None,
        commit_sha: str | None = None,
        destination: Path | None = None,
    ) -> RepositorySnapshot:
        """Clone 仓库、固定 Commit SHA 并返回可清理的快照。"""

        repository = validate_github_url(repository_url)
        normalized_branch = validate_branch_name(branch) if branch is not None else None
        requested_sha = normalize_commit_sha(commit_sha) if commit_sha is not None else None

        config_path = self._create_isolated_config()
        try:
            workspace = self._create_workspace(destination)
        except BaseException:
            config_path.unlink(missing_ok=True)
            raise

        try:
            self._clone_repository(workspace, repository, normalized_branch, config_path)

            resolved_branch = normalized_branch or self._resolve_branch(
                workspace, config_path
            )
            tip_sha = self._resolve_head(workspace, config_path)
            target_sha = requested_sha or tip_sha

            if target_sha != tip_sha:
                self._fetch_commit(workspace, target_sha, config_path)

            self._checkout_detached(workspace, target_sha, config_path)
            final_sha = self._resolve_head(workspace, config_path)
            if final_sha != target_sha:
                raise CommitResolutionError(
                    "checked-out commit SHA does not match the requested SHA"
                )

            self._enforce_size_limit(workspace)
            file_count, oversized_files = self._inspect_working_tree(workspace)
            size_bytes = self._directory_size(workspace)

            snapshot = RepositorySnapshot(
                owner=repository.owner,
                name=repository.name,
                repository_url=repository.canonical_url,
                branch=resolved_branch,
                commit_sha=final_sha,
                workspace_path=workspace,
                cloned_at=datetime.now(UTC),
                size_bytes=size_bytes,
                file_count=file_count,
                git_version=self.git.version(),
                oversized_files=oversized_files,
            )
            self._managed_workspaces.add(workspace.resolve())
            return snapshot
        except BaseException:
            if self.settings.keep_workspace_on_failure:
                self._managed_workspaces.add(workspace.resolve())
            else:
                self._safe_remove(workspace)
            raise
        finally:
            config_path.unlink(missing_ok=True)

    def cleanup(self, workspace: RepositorySnapshot | Path) -> None:
        """清理本管理器创建的工作区；拒绝删除任意路径。"""

        path = workspace.workspace_path if isinstance(workspace, RepositorySnapshot) else workspace
        resolved = path.resolve()
        if resolved not in self._managed_workspaces:
            raise RepositoryError("refusing to clean an unmanaged workspace")
        self._safe_remove(resolved)
        self._managed_workspaces.discard(resolved)

    def cleanup_all(self) -> None:
        """清理当前管理器持有的全部工作区。"""

        for workspace in list(self._managed_workspaces):
            self._safe_remove(workspace)
            self._managed_workspaces.discard(workspace)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.cleanup_all()

    def _clone_repository(
        self,
        workspace: Path,
        repository: GitHubRepository,
        branch: str | None,
        config_path: Path,
    ) -> None:
        args = [
            "clone",
            "--quiet",
            "--no-checkout",
            "--depth=1",
            "--single-branch",
            "--no-recurse-submodules",
            "--config",
            "http.followRedirects=false",
            "--config",
            "http.sslVerify=true",
            "--config",
            "core.symlinks=false",
            "--config",
            "core.fsmonitor=false",
            "--config",
            "submodule.recurse=false",
            "--config",
            "credential.helper=",
            "--config",
            "protocol.file.allow=never",
            "--config",
            "gc.auto=0",
            "--config",
            "maintenance.auto=false",
            "--config",
            "advice.detachedHead=false",
        ]
        if branch is not None:
            args.extend(["--branch", branch])
        args.extend(["--", repository.canonical_url, str(workspace)])

        result = self.git.run(
            args,
            timeout=self.settings.git_clone_timeout_seconds,
            size_guard=lambda: self._enforce_size_limit(workspace),
            isolated_config=config_path,
        )
        if result.returncode != 0:
            raise CloneError(self._git_error("git clone", result))

    def _resolve_branch(self, workspace: Path, config_path: Path) -> str:
        result = self._run_git(workspace, ["rev-parse", "--abbrev-ref", "HEAD"], config_path)
        branch = result.stdout.strip()
        if result.returncode != 0 or not branch:
            raise CommitResolutionError(self._git_error("git rev-parse", result))
        if branch == "HEAD":
            result = self._run_git(workspace, ["symbolic-ref", "--short", "HEAD"], config_path)
            branch = result.stdout.strip()
            if result.returncode != 0 or not branch or branch == "HEAD":
                raise CommitResolutionError(self._git_error("git symbolic-ref", result))
        return validate_branch_name(branch)

    def _resolve_head(self, workspace: Path, config_path: Path) -> str:
        result = self._run_git(
            workspace, ["rev-parse", "--verify", "HEAD^{commit}"], config_path
        )
        sha = result.stdout.strip()
        if result.returncode != 0 or not is_full_commit_sha(sha):
            raise CommitResolutionError(self._git_error("git rev-parse HEAD", result))
        return sha.lower()

    def _fetch_commit(self, workspace: Path, sha: str, config_path: Path) -> None:
        result = self._run_git(
            workspace,
            ["fetch", "--quiet", "--depth=1", "origin", sha],
            config_path,
            size_guard=lambda: self._enforce_size_limit(workspace),
        )
        if result.returncode != 0:
            raise CommitResolutionError(self._git_error("git fetch", result))

    def _checkout_detached(self, workspace: Path, sha: str, config_path: Path) -> None:
        result = self._run_git(
            workspace,
            ["checkout", "--quiet", "--detach", sha],
            config_path,
            size_guard=lambda: self._enforce_size_limit(workspace),
        )
        if result.returncode != 0:
            raise CommitResolutionError(self._git_error("git checkout", result))

    def _run_git(
        self,
        workspace: Path,
        args: Sequence[str],
        config_path: Path,
        *,
        size_guard: Callable[[], None] | None = None,
    ) -> GitResult:
        return self.git.run(
            ["-C", str(workspace), *args],
            timeout=self.settings.git_command_timeout_seconds,
            size_guard=size_guard,
            isolated_config=config_path,
        )

    def _enforce_size_limit(self, workspace: Path) -> None:
        limit = self.settings.max_repository_size_mb * 1024 * 1024
        size = self._directory_size(workspace)
        if size > limit:
            raise ResourceLimitExceededError(
                f"repository size {size} bytes exceeds limit {limit} bytes"
            )

    def _inspect_working_tree(self, workspace: Path) -> tuple[int, tuple[str, ...]]:
        """统计文件数量并记录超过单文件大小上限的文件。

        单文件超限按 docs/acceptance.md §4.7 跳过而非拒绝整个仓库；
        这里只负责记录，实际跳过发生在阶段 1.2 的扫描过滤。
        """

        file_limit = self.settings.max_file_count
        size_limit = self.settings.max_single_file_size_mb * 1024 * 1024
        count = 0
        oversized: list[str] = []
        for root, dirs, files in os.walk(workspace, followlinks=False):
            if ".git" in dirs:
                dirs.remove(".git")
            for name in files:
                count += 1
                if count > file_limit:
                    raise ResourceLimitExceededError(
                        f"repository file count exceeds limit {file_limit}"
                    )
                path = Path(root, name)
                try:
                    size = os.lstat(path).st_size
                except OSError:
                    continue
                if size > size_limit:
                    oversized.append(path.relative_to(workspace).as_posix())
        return count, tuple(sorted(oversized))

    @staticmethod
    def _directory_size(path: Path) -> int:
        if not path.exists():
            return 0
        total = 0
        for root, _dirs, files in os.walk(path, followlinks=False):
            for name in files:
                try:
                    total += os.lstat(os.path.join(root, name)).st_size
                except OSError:
                    continue
        return total

    def _create_workspace(self, destination: Path | None) -> Path:
        if destination is None:
            return Path(
                tempfile.mkdtemp(prefix="code_review_repo_", dir=str(self._workspace_root))
            )

        resolved = destination.expanduser().resolve()
        if resolved == self._workspace_root or not resolved.is_relative_to(
            self._workspace_root
        ):
            raise RepositoryError("destination must be inside workspace_root")
        if resolved.exists():
            if not resolved.is_dir():
                raise RepositoryError("destination must be a directory")
            if any(resolved.iterdir()):
                raise RepositoryError("destination must be empty")
        else:
            resolved.mkdir(parents=True)
        return resolved

    def _create_isolated_config(self) -> Path:
        fd, name = tempfile.mkstemp(
            prefix="code_review_gitconfig_",
            suffix=".gitconfig",
            dir=str(self._workspace_root),
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("# isolated git config for code review\n")
        return Path(name)

    def _safe_remove(self, path: Path) -> None:
        resolved = path.resolve()
        if resolved == self._workspace_root or not resolved.is_relative_to(
            self._workspace_root
        ):
            return

        def _on_error(func: object, target: str, exc_info: object) -> None:
            try:
                os.chmod(target, stat.S_IWRITE)
            except OSError:
                pass
            try:
                func(target)  # type: ignore[operator]
            except OSError:
                pass

        try:
            shutil.rmtree(resolved, onerror=_on_error)
        except OSError:
            pass

    @staticmethod
    def _git_error(action: str, result: GitResult) -> str:
        detail = result.stderr.strip() or result.stdout.strip() or "no output"
        return f"{action} failed with exit code {result.returncode}: {detail}"
