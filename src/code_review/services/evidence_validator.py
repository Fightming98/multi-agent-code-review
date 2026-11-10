"""确定性代码证据校验。

LLM 的 Finding 提案不能直接成为正式 Finding。本模块只使用工作区中的真实
文件和允许分析的 Python 文件集合，校验路径、行号与代码片段：

- 路径必须是仓库相对 POSIX 路径，且位于允许分析的文件集合内；
- 路径不得通过符号链接或 junction 逃逸工作区；
- 行号必须在文件范围内；
- 证据片段必须能在指定行附近唯一定位；只有唯一邻近匹配才允许修正行号。

校验失败只返回安全的原因字符串，不包含宿主机绝对路径或文件内容。
"""

from __future__ import annotations

import tokenize
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from code_review.tools.file_filters import FileFilterPolicy

from .redaction import redact_sensitive_text

_EVIDENCE_SEARCH_RADIUS = 3
_MAX_EXCERPT_CHARS = 4_000
_MAX_REASON_CHARS = 300


class EvidenceValidationConfigurationError(ValueError):
    """允许分析的文件集合不合法。"""


@dataclass(frozen=True)
class EvidenceValidation:
    """一次证据校验的结果。"""

    ok: bool
    reason: str | None = None
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    excerpt: str | None = None
    line_adjusted: bool = False


class CodeEvidenceValidator:
    """在固定工作区内校验 LLM 提案的代码位置与片段。"""

    def __init__(
        self,
        workspace_path: Path,
        allowed_files: Iterable[str],
        *,
        max_file_bytes: int = 2 * 1024 * 1024,
        max_excerpt_chars: int = _MAX_EXCERPT_CHARS,
    ) -> None:
        candidate = Path(workspace_path).expanduser()
        try:
            self.workspace = candidate.resolve(strict=True)
        except OSError as exc:
            raise EvidenceValidationConfigurationError(
                "evidence workspace does not exist"
            ) from exc
        if not self.workspace.is_dir():
            raise EvidenceValidationConfigurationError(
                "evidence workspace is not a directory"
            )
        self.max_file_bytes = max(max_file_bytes, 1)
        self.max_excerpt_chars = max(max_excerpt_chars, 1)
        filter_policy = FileFilterPolicy()
        normalized_files = (
            self._normalize_allowed_file(path) for path in allowed_files
        )
        self.allowed_files = frozenset(
            path
            for path in normalized_files
            if not filter_policy.is_sensitive_path(path)
        )

    def validate(
        self,
        file_path: str,
        start_line: int,
        end_line: int | None,
        evidence: str,
    ) -> EvidenceValidation:
        """校验一个代码位置与证据片段。"""

        if not isinstance(file_path, str) or not file_path:
            return self._reject("file_path must be a non-empty string")
        if (
            not isinstance(start_line, int)
            or isinstance(start_line, bool)
            or start_line < 1
        ):
            return self._reject("start_line must be a positive integer")
        if end_line is None:
            end_line = start_line
        if (
            not isinstance(end_line, int)
            or isinstance(end_line, bool)
            or end_line < start_line
        ):
            return self._reject("end_line must be greater than or equal to start_line")
        if not isinstance(evidence, str) or not evidence.strip():
            return self._reject("evidence must be a non-empty string")

        normalized_path = self._normalize_path(file_path)
        if normalized_path is None:
            return self._reject("file_path must be a repo-relative POSIX path")
        if normalized_path not in self.allowed_files:
            return self._reject(
                "file_path is not in the analyzed file set"
            )

        read = self._read_lines(normalized_path)
        if isinstance(read, EvidenceValidation):
            return read
        lines = read
        if start_line > len(lines):
            return self._reject("start_line exceeds the file line count")
        if end_line > len(lines):
            return self._reject("end_line exceeds the file line count")

        normalized_evidence = _normalize_text(evidence)
        if not normalized_evidence:
            return self._reject("evidence must contain visible characters")

        specified_excerpt = "\n".join(lines[start_line - 1 : end_line])
        if normalized_evidence in _normalize_text(specified_excerpt):
            return self._accept(
                normalized_path,
                start_line,
                end_line,
                specified_excerpt,
                adjusted=False,
            )

        evidence_line_count = max(1, len(evidence.splitlines()))
        if evidence_line_count > len(lines):
            return self._reject("evidence is longer than the file")
        lower = max(1, start_line - _EVIDENCE_SEARCH_RADIUS)
        upper = min(
            len(lines) - evidence_line_count + 1,
            start_line + _EVIDENCE_SEARCH_RADIUS,
        )
        matches: list[tuple[int, int]] = []
        for candidate_start in range(lower, upper + 1):
            candidate_end = candidate_start + evidence_line_count - 1
            block = "\n".join(lines[candidate_start - 1 : candidate_end])
            if normalized_evidence in _normalize_text(block):
                matches.append((candidate_start, candidate_end))

        if len(matches) == 1:
            adjusted_start, adjusted_end = matches[0]
            return self._accept(
                normalized_path,
                adjusted_start,
                adjusted_end,
                "\n".join(lines[adjusted_start - 1 : adjusted_end]),
                adjusted=True,
            )
        if not matches:
            return self._reject(
                "evidence snippet was not found near the specified line"
            )
        return self._reject(
            "evidence snippet is ambiguous near the specified line"
        )

    def validate_location(
        self,
        file_path: str,
        start_line: int | None,
        end_line: int | None,
    ) -> EvidenceValidation:
        """只校验文件与行号范围，不要求代码片段。"""

        if start_line is None:
            if end_line is not None:
                return self._reject("end_line requires start_line")
            normalized_path = self._normalize_path(file_path)
            if normalized_path is None:
                return self._reject("file_path must be a repo-relative POSIX path")
            if normalized_path not in self.allowed_files:
                return self._reject("file_path is not in the analyzed file set")
            read = self._read_lines(normalized_path)
            if isinstance(read, EvidenceValidation):
                return read
            return EvidenceValidation(
                ok=True,
                file_path=normalized_path,
                excerpt=None,
            )

        if (
            not isinstance(start_line, int)
            or isinstance(start_line, bool)
            or start_line < 1
        ):
            return self._reject("start_line must be a positive integer")
        if end_line is None:
            end_line = start_line
        if (
            not isinstance(end_line, int)
            or isinstance(end_line, bool)
            or end_line < start_line
        ):
            return self._reject("end_line must be greater than or equal to start_line")
        normalized_path = self._normalize_path(file_path)
        if normalized_path is None:
            return self._reject("file_path must be a repo-relative POSIX path")
        if normalized_path not in self.allowed_files:
            return self._reject("file_path is not in the analyzed file set")
        read = self._read_lines(normalized_path)
        if isinstance(read, EvidenceValidation):
            return read
        lines = read
        if end_line > len(lines):
            return self._reject("end_line exceeds the file line count")
        return EvidenceValidation(
            ok=True,
            file_path=normalized_path,
            start_line=start_line,
            end_line=end_line,
            excerpt="\n".join(lines[start_line - 1 : end_line]),
        )

    def read_excerpt(
        self,
        file_path: str,
        start_line: int | None,
        end_line: int | None,
        *,
        context_lines: int = 2,
        max_chars: int = 1_200,
    ) -> str | None:
        """读取 Finding 附近的代码片段，供 LLM 输入使用。

        任何校验失败都返回 ``None``；调用方不得因为读取失败而中断聚合。
        """

        if start_line is None:
            return None
        location = self.validate_location(file_path, start_line, end_line)
        if not location.ok or location.file_path is None:
            return None
        read = self._read_lines(location.file_path)
        if isinstance(read, EvidenceValidation):
            return None
        lines = read
        start = max(1, start_line - max(context_lines, 0))
        end = min(len(lines), (end_line or start_line) + max(context_lines, 0))
        excerpt = "\n".join(lines[start - 1 : end])
        return redact_sensitive_text(excerpt, max_chars=max_chars)

    def _normalize_allowed_file(self, value: str) -> str:
        normalized = self._normalize_path(value)
        if normalized is None:
            raise EvidenceValidationConfigurationError(
                "allowed file path must be a repo-relative POSIX path"
            )
        try:
            candidate = self.workspace.joinpath(*PurePosixPath(normalized).parts)
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise EvidenceValidationConfigurationError(
                "allowed file is missing"
            ) from exc
        if not resolved.is_relative_to(self.workspace):
            raise EvidenceValidationConfigurationError(
                "allowed file resolves outside the workspace"
            )
        if _is_link(candidate) or _is_link(resolved):
            raise EvidenceValidationConfigurationError(
                "allowed file must not be a link"
            )
        if not resolved.is_file():
            raise EvidenceValidationConfigurationError(
                "allowed file is not a regular file"
            )
        return normalized

    def _read_lines(self, relative_path: str) -> list[str] | EvidenceValidation:
        candidate = self.workspace.joinpath(*PurePosixPath(relative_path).parts)
        if _is_link(candidate):
            return self._reject("file_path must not be a symbolic link")
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            return self._reject("file_path does not exist")
        if not resolved.is_relative_to(self.workspace):
            return self._reject("file_path resolves outside the workspace")
        if not resolved.is_file():
            return self._reject("file_path is not a regular file")
        try:
            if resolved.stat().st_size > self.max_file_bytes:
                return self._reject("file exceeds the analysis size limit")
            with tokenize.open(resolved) as handle:
                text = handle.read(self.max_file_bytes + 1)
        except (OSError, SyntaxError, UnicodeDecodeError):
            return self._reject("file could not be read as Python source")
        if len(text) > self.max_file_bytes:
            return self._reject("file exceeds the analysis size limit")
        return text.splitlines()

    @staticmethod
    def _normalize_path(value: object) -> str | None:
        if not isinstance(value, str) or not value:
            return None
        if len(value) > 512:
            return None
        if "\\" in value or "\x00" in value or ":" in value:
            return None
        pure = PurePosixPath(value)
        if (
            not pure.parts
            or pure.is_absolute()
            or ".." in pure.parts
            or "." in pure.parts
        ):
            return None
        if pure.as_posix() != value:
            return None
        return value

    def _accept(
        self,
        file_path: str,
        start_line: int,
        end_line: int,
        excerpt: str,
        *,
        adjusted: bool,
    ) -> EvidenceValidation:
        return EvidenceValidation(
            ok=True,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            excerpt=redact_sensitive_text(
                excerpt,
                max_chars=self.max_excerpt_chars,
            ),
            line_adjusted=adjusted,
        )

    @staticmethod
    def _reject(reason: str) -> EvidenceValidation:
        return EvidenceValidation(
            ok=False,
            reason=redact_sensitive_text(reason, max_chars=_MAX_REASON_CHARS),
        )


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()
