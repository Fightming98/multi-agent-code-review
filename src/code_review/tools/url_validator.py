"""GitHub 仓库 URL、分支名与 Commit SHA 的安全校验。

只允许 HTTPS + github.com + 标准 ``/owner/repo`` 形式。该校验是仓库获取
链路的第一道安全边界：任何不满足约束的输入都不得进入 Git 子进程。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

GITHUB_HOST = "github.com"
GITHUB_PORT = 443
MAX_URL_LENGTH = 2048
MAX_BRANCH_LENGTH = 255

_COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_CONTROL_OR_SPACE_RE = re.compile(r"[\x00-\x20\x7f]")
_FORBIDDEN_BRANCH_CHARS = frozenset("~^:?*[\\")


class URLValidationError(ValueError):
    """GitHub URL、分支名或 Commit SHA 不满足安全约束。"""


@dataclass(frozen=True)
class GitHubRepository:
    """校验后的 GitHub 仓库标识。"""

    owner: str
    name: str

    @property
    def canonical_url(self) -> str:
        """返回不含凭据、端口、查询串与片段的规范 URL。"""

        return f"https://{GITHUB_HOST}/{self.owner}/{self.name}"

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


def validate_github_url(raw_url: str) -> GitHubRepository:
    """校验并规范化 GitHub 仓库 URL。

    仅接受 ``https://github.com/<owner>/<repo>``（可带 ``.git`` 后缀或尾部斜杠）。
    本地路径、其他协议、其他域名/端口、凭据、查询串、片段、额外路径段、
    URL 编码与路径穿越一律拒绝。
    """

    if not isinstance(raw_url, str):
        raise URLValidationError("repository URL must be a string")

    url = raw_url.strip()
    if not url:
        raise URLValidationError("repository URL must not be empty")
    if len(url) > MAX_URL_LENGTH:
        raise URLValidationError(f"repository URL exceeds {MAX_URL_LENGTH} characters")
    if _CONTROL_OR_SPACE_RE.search(url):
        raise URLValidationError("repository URL contains whitespace or control characters")
    if "\\" in url:
        raise URLValidationError("repository URL must not contain backslashes")
    if "%" in url:
        raise URLValidationError("repository URL must not contain percent-encoding")

    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise URLValidationError("repository URL is malformed") from exc

    if parsed.scheme.lower() != "https":
        raise URLValidationError("only the https scheme is allowed")
    if parsed.username is not None or parsed.password is not None:
        raise URLValidationError("repository URL must not contain credentials")
    if hostname is None or hostname.lower() != GITHUB_HOST:
        raise URLValidationError(f"only the {GITHUB_HOST} host is allowed")
    if parsed.netloc.endswith(":"):
        raise URLValidationError("repository URL has an empty port")
    if port is not None and port != GITHUB_PORT:
        raise URLValidationError(f"only port {GITHUB_PORT} is allowed")
    if parsed.query:
        raise URLValidationError("repository URL must not contain a query string")
    if parsed.fragment:
        raise URLValidationError("repository URL must not contain a fragment")

    path = parsed.path
    if not path.startswith("/"):
        raise URLValidationError("repository URL path must be absolute")

    segments = path.split("/")[1:]
    if segments and segments[-1] == "":
        segments.pop()
    if len(segments) != 2 or any(segment == "" for segment in segments):
        raise URLValidationError("repository URL must be /owner/repo")

    owner, repo = segments

    if not _OWNER_RE.fullmatch(owner):
        raise URLValidationError("invalid GitHub owner name")

    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    if not repo or repo in {".", ".."} or ".." in repo or set(repo) <= {"."}:
        raise URLValidationError("invalid GitHub repository name")
    if repo.lower().endswith(".git"):
        raise URLValidationError("invalid GitHub repository name")
    if not _REPO_RE.fullmatch(repo):
        raise URLValidationError("invalid GitHub repository name")

    return GitHubRepository(owner=owner, name=repo)


def validate_branch_name(branch: str) -> str:
    """校验分支名，拒绝可能被 Git 解释为选项或非法引用的输入。"""

    if not isinstance(branch, str):
        raise URLValidationError("branch name must be a string")

    if branch != branch.strip():
        raise URLValidationError(
            "branch name must not have leading or trailing whitespace"
        )
    candidate = branch
    if not candidate:
        raise URLValidationError("branch name must not be empty")
    if len(candidate) > MAX_BRANCH_LENGTH:
        raise URLValidationError(
            f"branch name exceeds {MAX_BRANCH_LENGTH} characters"
        )
    if _CONTROL_OR_SPACE_RE.search(candidate):
        raise URLValidationError("branch name contains whitespace or control characters")
    if any(char in _FORBIDDEN_BRANCH_CHARS for char in candidate):
        raise URLValidationError("branch name contains a forbidden character")
    if ".." in candidate or "@{" in candidate or "//" in candidate:
        raise URLValidationError("branch name contains a forbidden sequence")
    if candidate.startswith(("-", "/", ".")) or candidate.endswith(("/", ".")):
        raise URLValidationError("branch name has an invalid prefix or suffix")
    if candidate.lower().endswith(".lock"):
        raise URLValidationError("branch name must not end with .lock")
    if candidate == "@" or candidate.upper() == "HEAD":
        raise URLValidationError("branch name is reserved")

    for component in candidate.split("/"):
        if not component or component in {".", ".."}:
            raise URLValidationError("branch name contains an invalid path component")
        if (
            component.startswith(".")
            or component.endswith(".")
            or component.lower().endswith(".lock")
        ):
            raise URLValidationError("branch name contains an invalid path component")

    return candidate


def normalize_commit_sha(commit_sha: str) -> str:
    """校验并规范化 40 位完整 Commit SHA。"""

    if not isinstance(commit_sha, str):
        raise URLValidationError("commit SHA must be a string")

    candidate = commit_sha.strip()
    if not _COMMIT_SHA_RE.fullmatch(candidate):
        raise URLValidationError("commit SHA must be exactly 40 hexadecimal characters")
    return candidate.lower()


def is_full_commit_sha(value: str) -> bool:
    """判断字符串是否为 40 位十六进制 Commit SHA。"""

    return isinstance(value, str) and bool(_COMMIT_SHA_RE.fullmatch(value.strip()))
