"""Stage 2 自有 Fixture 的确定性临时 Git 仓库构建器。

本模块只做三件事：

1. 校验 ``tests/fixtures/stage2_sample_repo/`` 的清单与字节哈希；
2. 把通过校验的字节复制到调用方指定的空目录；
3. 用真实 Git 命令初始化 ``main``、提交并读取 ``HEAD``。

确定性措施：固定文件字节、``core.autocrlf=false``、``core.fileMode=false``、
空钩子模板、固定 author/committer 身份与时间、固定提交信息、固定 SHA-1
对象格式、禁用全局/系统 Git 配置。重复构建必须得到相同 commit SHA。

本模块不联网、不执行 Fixture 测试、不写入报告，也不把宿主路径写入返回值。
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from code_review.tools.trusted_fixture import (
    FIXTURE_MANIFEST_FILENAME,
    TrustedFixtureError,
    verify_trusted_fixture,
)

__all__ = [
    "STAGE2_FIXTURE_NAME",
    "STAGE2_FIXTURE_ROOT",
    "Stage2FixtureBuild",
    "Stage2FixtureBuildError",
    "build_stage2_fixture_repository",
]

STAGE2_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "stage2_sample_repo"
)
STAGE2_FIXTURE_NAME = "stage2_sample_repo_v1"

_FIXTURE_VERSION = "1.0.0"
_COMMIT_MESSAGE = "stage2 sample fixture"
_AUTHOR_NAME = "Stage 2 Fixture Builder"
_AUTHOR_EMAIL = "stage2-fixture@example.invalid"
_FIXED_COMMIT_TIME = "2026-01-01T00:00:00+0000"
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# 只继承 Git 在 Windows/POSIX 上启动所需的系统变量；其余全部固定或清除，
# 避免宿主机的 GIT_DIR、GIT_CONFIG_*、用户配置影响提交对象。
_ENV_KEYS = (
    "PATH",
    "PATHEXT",
    "SystemRoot",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "TMPDIR",
    "USERPROFILE",
    "HOME",
    "HOMEDRIVE",
    "HOMEPATH",
    "LOCALAPPDATA",
    "APPDATA",
    "PROGRAMDATA",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
)


class Stage2FixtureBuildError(RuntimeError):
    """Fixture 复制、校验或真实 Git 提交失败。"""


@dataclass(frozen=True)
class Stage2FixtureBuild:
    """一次成功构建的 Stage 2 Fixture 元数据。

    ``workspace_path`` 是包含 ``.git`` 的临时 Git 仓库，只供审查流程使用；
    不得写入报告。对外可见的标识是 fixture 名称、版本、清单哈希和 commit SHA。
    """

    workspace_path: Path
    fixture_root: Path
    fixture_name: str
    fixture_version: str
    commit_sha: str
    commit_message: str
    commit_time: str
    author_name: str
    author_email: str
    git_version: str
    fixture_manifest_sha256: str
    file_hashes: Mapping[str, str]

    @property
    def file_count(self) -> int:
        return len(self.file_hashes)


def build_stage2_fixture_repository(
    destination: Path | str,
    *,
    fixture_root: Path | str | None = None,
    fixture_name: str = STAGE2_FIXTURE_NAME,
    git_executable: str = "git",
    timeout_seconds: float = 120.0,
) -> Stage2FixtureBuild:
    """在 ``destination`` 构建真实临时 Git 仓库并返回真实 commit SHA。

    ``destination`` 必须是不存在或空的目录。构建失败时删除本次创建的目录，
    不触碰调用方已有文件。
    """

    if not isinstance(fixture_name, str) or not fixture_name:
        raise Stage2FixtureBuildError("fixture name is invalid")
    if not isinstance(git_executable, str) or not git_executable.strip():
        raise Stage2FixtureBuildError("git executable is invalid")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or timeout_seconds <= 0
    ):
        raise Stage2FixtureBuildError("timeout must be positive")

    source_root = (
        Path(fixture_root).expanduser()
        if fixture_root is not None
        else STAGE2_FIXTURE_ROOT
    )
    try:
        verified = verify_trusted_fixture(
            source_root, expected_name=fixture_name
        )
    except TrustedFixtureError as exc:
        raise Stage2FixtureBuildError(
            "stage 2 fixture is not approved or failed integrity verification"
        ) from exc
    if verified.version != _FIXTURE_VERSION:
        raise Stage2FixtureBuildError(
            "stage 2 fixture version does not match the builder contract"
        )

    destination_path = Path(destination).expanduser()
    created = False
    try:
        if destination_path.exists():
            if not destination_path.is_dir() or any(destination_path.iterdir()):
                raise Stage2FixtureBuildError(
                    "fixture destination must be absent or an empty directory"
                )
        else:
            destination_path.mkdir(parents=True)
            created = True

        _copy_verified_files(verified.root, destination_path, verified.file_hashes)
        _copy_manifest(
            verified.manifest_path,
            destination_path / FIXTURE_MANIFEST_FILENAME,
        )

        # 复制后、git init 前再次走完整清单校验，证明工作树与批准内容一致。
        try:
            rebuilt = verify_trusted_fixture(
                destination_path, expected_name=fixture_name
            )
        except TrustedFixtureError as exc:
            raise Stage2FixtureBuildError(
                "copied fixture failed integrity verification"
            ) from exc
        if rebuilt.manifest_sha256 != verified.manifest_sha256:
            raise Stage2FixtureBuildError(
                "copied fixture manifest hash changed unexpectedly"
            )

        git_version = _git_version(git_executable, timeout_seconds)
        _git_init(destination_path, git_executable, timeout_seconds)
        _git_commit(
            destination_path,
            git_executable=git_executable,
            timeout_seconds=timeout_seconds,
        )

        commit_sha = _rev_parse_head(
            destination_path, git_executable, timeout_seconds
        )
        if not _COMMIT_SHA_RE.fullmatch(commit_sha):
            raise Stage2FixtureBuildError(
                "git did not return a full 40-character commit SHA"
            )
        branch = _current_branch(
            destination_path, git_executable, timeout_seconds
        )
        if branch != "main":
            raise Stage2FixtureBuildError(
                "fixture repository must be committed on branch main"
            )
        _require_clean_status(
            destination_path, git_executable, timeout_seconds
        )
        _verify_committed_bytes(
            destination_path,
            expected=verified.file_hashes,
            manifest_sha256=verified.manifest_sha256,
        )
    except Stage2FixtureBuildError:
        if created:
            shutil.rmtree(destination_path, ignore_errors=True)
        raise
    except Exception as exc:
        if created:
            shutil.rmtree(destination_path, ignore_errors=True)
        raise Stage2FixtureBuildError(
            "stage 2 fixture repository could not be built"
        ) from exc

    return Stage2FixtureBuild(
        workspace_path=destination_path.resolve(),
        fixture_root=verified.root,
        fixture_name=verified.name,
        fixture_version=verified.version,
        commit_sha=commit_sha,
        commit_message=_COMMIT_MESSAGE,
        commit_time=_FIXED_COMMIT_TIME,
        author_name=_AUTHOR_NAME,
        author_email=_AUTHOR_EMAIL,
        git_version=git_version,
        fixture_manifest_sha256=verified.manifest_sha256,
        file_hashes=MappingProxyType(dict(verified.file_hashes)),
    )


def _copy_verified_files(
    source_root: Path,
    destination_root: Path,
    file_hashes: Mapping[str, str],
) -> None:
    for relative in sorted(file_hashes):
        source = source_root.joinpath(*relative.split("/"))
        target = destination_root.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def _copy_manifest(source: Path, target: Path) -> None:
    target.write_bytes(source.read_bytes())


def _git_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in _ENV_KEYS and value
    }
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": _AUTHOR_NAME,
            "GIT_AUTHOR_EMAIL": _AUTHOR_EMAIL,
            "GIT_COMMITTER_NAME": _AUTHOR_NAME,
            "GIT_COMMITTER_EMAIL": _AUTHOR_EMAIL,
            "GIT_AUTHOR_DATE": _FIXED_COMMIT_TIME,
            "GIT_COMMITTER_DATE": _FIXED_COMMIT_TIME,
            "LC_ALL": "C",
            "LANG": "C",
            "TZ": "UTC",
        }
    )
    return environment


def _run_git(
    arguments: list[str],
    *,
    cwd: Path,
    git_executable: str,
    timeout_seconds: float,
) -> str:
    command = [git_executable, *arguments]
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            env=_git_environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise Stage2FixtureBuildError(
            f"git command could not start: {arguments[0]}"
        ) from exc
    if completed.returncode != 0:
        raise Stage2FixtureBuildError(
            f"git command failed with exit code {completed.returncode}: "
            f"{arguments[0]}"
        )
    return completed.stdout


def _git_version(git_executable: str, timeout_seconds: float) -> str:
    output = _run_git(
        ["--version"],
        cwd=Path.cwd(),
        git_executable=git_executable,
        timeout_seconds=timeout_seconds,
    ).strip()
    if not output.startswith("git version "):
        raise Stage2FixtureBuildError("git version output is not recognized")
    return output


def _git_init(
    repository: Path,
    git_executable: str,
    timeout_seconds: float,
) -> None:
    with tempfile.TemporaryDirectory(
        prefix="stage2-git-template-"
    ) as template_name:
        _run_git(
            [
                "-c",
                "init.defaultBranch=main",
                "init",
                "--quiet",
                "--initial-branch=main",
                "--object-format=sha1",
                f"--template={template_name}",
            ],
            cwd=repository,
            git_executable=git_executable,
            timeout_seconds=timeout_seconds,
        )


def _git_commit(
    repository: Path,
    *,
    git_executable: str,
    timeout_seconds: float,
) -> None:
    common = [
        "-c",
        f"user.name={_AUTHOR_NAME}",
        "-c",
        f"user.email={_AUTHOR_EMAIL}",
        "-c",
        "commit.gpgsign=false",
        "-c",
        "core.autocrlf=false",
        "-c",
        "core.fileMode=false",
        "-c",
        "core.safecrlf=false",
        "-c",
        "core.quotepath=false",
        "-c",
        "i18n.commitEncoding=UTF-8",
        "-c",
        "i18n.logOutputEncoding=UTF-8",
    ]
    _run_git(
        [*common, "add", "--all"],
        cwd=repository,
        git_executable=git_executable,
        timeout_seconds=timeout_seconds,
    )
    _run_git(
        [*common, "commit", "--quiet", "--no-verify", "-m", _COMMIT_MESSAGE],
        cwd=repository,
        git_executable=git_executable,
        timeout_seconds=timeout_seconds,
    )


def _rev_parse_head(
    repository: Path,
    git_executable: str,
    timeout_seconds: float,
) -> str:
    return _run_git(
        ["rev-parse", "--verify", "HEAD^{commit}"],
        cwd=repository,
        git_executable=git_executable,
        timeout_seconds=timeout_seconds,
    ).strip()


def _current_branch(
    repository: Path,
    git_executable: str,
    timeout_seconds: float,
) -> str:
    return _run_git(
        ["rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repository,
        git_executable=git_executable,
        timeout_seconds=timeout_seconds,
    ).strip()


def _require_clean_status(
    repository: Path,
    git_executable: str,
    timeout_seconds: float,
) -> None:
    status = _run_git(
        ["status", "--porcelain"],
        cwd=repository,
        git_executable=git_executable,
        timeout_seconds=timeout_seconds,
    )
    if status.strip():
        raise Stage2FixtureBuildError(
            "fixture repository has uncommitted changes after the commit"
        )


def _verify_committed_bytes(
    repository: Path,
    *,
    expected: Mapping[str, str],
    manifest_sha256: str,
) -> None:
    actual: dict[str, str] = {}
    for path in sorted(repository.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(repository)
        if ".git" in relative.parts:
            continue
        relative_posix = relative.as_posix()
        try:
            actual[relative_posix] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
        except OSError as exc:
            raise Stage2FixtureBuildError(
                "fixture file could not be hashed after the commit"
            ) from exc
    expected_files = dict(expected)
    expected_files[FIXTURE_MANIFEST_FILENAME] = manifest_sha256
    if actual != expected_files:
        raise Stage2FixtureBuildError(
            "fixture working tree does not match the approved manifest "
            "after the commit"
        )
