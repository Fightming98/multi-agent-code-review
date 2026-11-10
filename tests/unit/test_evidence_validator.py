"""确定性代码证据校验的单元测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.code_review.services.evidence_validator import (
    CodeEvidenceValidator,
    EvidenceValidationConfigurationError,
)

MODULE_TEXT = (
    "alpha\n"
    "beta\n"
    "gamma\n"
    "delta\n"
    "epsilon\n"
)


def make_workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    module = workspace / "pkg" / "mod.py"
    module.parent.mkdir(parents=True)
    module.write_text(MODULE_TEXT, encoding="utf-8")
    return workspace, module


def validator(workspace: Path) -> CodeEvidenceValidator:
    return CodeEvidenceValidator(workspace, ["pkg/mod.py"])


def test_exact_evidence_is_accepted(tmp_path: Path) -> None:
    workspace, _ = make_workspace(tmp_path)

    result = validator(workspace).validate("pkg/mod.py", 2, 2, "beta")

    assert result.ok is True
    assert result.file_path == "pkg/mod.py"
    assert result.start_line == 2
    assert result.end_line == 2
    assert result.excerpt == "beta"
    assert result.line_adjusted is False
    assert result.reason is None


def test_multiline_evidence_is_accepted(tmp_path: Path) -> None:
    workspace, _ = make_workspace(tmp_path)

    result = validator(workspace).validate(
        "pkg/mod.py",
        2,
        3,
        "beta\ngamma",
    )

    assert result.ok is True
    assert result.excerpt == "beta\ngamma"
    assert result.line_adjusted is False


def test_whitespace_is_normalized_before_matching(tmp_path: Path) -> None:
    workspace, _ = make_workspace(tmp_path)

    result = validator(workspace).validate(
        "pkg/mod.py",
        2,
        3,
        "  beta   gamma  ",
    )

    assert result.ok is True


def test_nearby_unique_evidence_adjusts_line_number(tmp_path: Path) -> None:
    workspace, _ = make_workspace(tmp_path)

    result = validator(workspace).validate("pkg/mod.py", 4, 4, "beta")

    assert result.ok is True
    assert result.start_line == 2
    assert result.end_line == 2
    assert result.line_adjusted is True


def test_missing_evidence_is_rejected(tmp_path: Path) -> None:
    workspace, _ = make_workspace(tmp_path)

    result = validator(workspace).validate("pkg/mod.py", 2, 2, "zeta")

    assert result.ok is False
    assert "not found" in (result.reason or "")


def test_ambiguous_nearby_evidence_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    module = workspace / "pkg" / "mod.py"
    module.parent.mkdir(parents=True)
    module.write_text("alpha\nbeta\ngamma\nbeta\n", encoding="utf-8")

    result = validator(workspace).validate("pkg/mod.py", 1, 1, "beta")

    assert result.ok is False
    assert "ambiguous" in (result.reason or "")


def test_evidence_that_is_longer_than_file_is_rejected(tmp_path: Path) -> None:
    workspace, _ = make_workspace(tmp_path)

    result = validator(workspace).validate(
        "pkg/mod.py",
        2,
        2,
        "\n".join(["line"] * 20),
    )

    assert result.ok is False


def test_path_not_in_allowed_set_is_rejected(tmp_path: Path) -> None:
    workspace, _ = make_workspace(tmp_path)
    other = workspace / "pkg" / "other.py"
    other.write_text("other = 1\n", encoding="utf-8")

    result = validator(workspace).validate("pkg/other.py", 1, 1, "other")

    assert result.ok is False
    assert "analyzed file set" in (result.reason or "")


@pytest.mark.parametrize(
    "file_path",
    [
        "../outside.py",
        "pkg/../mod.py",
        "./pkg/mod.py",
        "pkg\\mod.py",
        "C:/workspace/pkg/mod.py",
        "/pkg/mod.py",
    ],
)
def test_unsafe_or_noncanonical_paths_are_rejected(
    tmp_path: Path,
    file_path: str,
) -> None:
    workspace, _ = make_workspace(tmp_path)

    result = validator(workspace).validate(file_path, 1, 1, "alpha")

    assert result.ok is False
    assert "POSIX path" in (result.reason or "")


def test_empty_path_is_rejected(tmp_path: Path) -> None:
    workspace, _ = make_workspace(tmp_path)

    result = validator(workspace).validate("", 1, 1, "alpha")

    assert result.ok is False
    assert "non-empty string" in (result.reason or "")


@pytest.mark.parametrize(
    ("start_line", "end_line", "evidence"),
    [
        (1, 1, ""),
        (0, 1, "alpha"),
        (2, 1, "alpha"),
        (99, 99, "alpha"),
        (2, 99, "beta"),
    ],
)
def test_invalid_ranges_or_empty_evidence_are_rejected(
    tmp_path: Path,
    start_line: int,
    end_line: int,
    evidence: str,
) -> None:
    workspace, _ = make_workspace(tmp_path)

    result = validator(workspace).validate(
        "pkg/mod.py",
        start_line,
        end_line,
        evidence,
    )

    assert result.ok is False


def test_oversized_file_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    module = workspace / "pkg" / "mod.py"
    module.parent.mkdir(parents=True)
    module.write_text("alpha = 1\nbeta = 2\n", encoding="utf-8")

    result = CodeEvidenceValidator(
        workspace,
        ["pkg/mod.py"],
        max_file_bytes=8,
    ).validate("pkg/mod.py", 1, 1, "alpha")

    assert result.ok is False
    assert "size limit" in (result.reason or "")


def test_sensitive_file_is_not_in_allowed_set(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "mod.py").write_text("value = 1\n", encoding="utf-8")
    (workspace / ".env").write_text("API_KEY=secret-value\n", encoding="utf-8")

    guard = CodeEvidenceValidator(workspace, ["mod.py", ".env"])

    assert guard.allowed_files == frozenset({"mod.py"})
    result = guard.validate(".env", 1, 1, "API_KEY=secret-value")
    assert result.ok is False
    assert "analyzed file set" in (result.reason or "")


def test_validate_location_without_evidence(tmp_path: Path) -> None:
    workspace, _ = make_workspace(tmp_path)

    result = validator(workspace).validate_location("pkg/mod.py", 2, 3)

    assert result.ok is True
    assert result.start_line == 2
    assert result.end_line == 3
    assert result.excerpt == "beta\ngamma"


def test_validate_location_for_whole_file(tmp_path: Path) -> None:
    workspace, _ = make_workspace(tmp_path)

    result = validator(workspace).validate_location("pkg/mod.py", None, None)

    assert result.ok is True
    assert result.file_path == "pkg/mod.py"
    assert result.start_line is None
    assert result.excerpt is None


def test_read_excerpt_includes_context_and_redacts(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    module = workspace / "pkg" / "mod.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        "before\n"
        'password = "super-secret-value"\n'
        "after\n",
        encoding="utf-8",
    )

    excerpt = validator(workspace).read_excerpt("pkg/mod.py", 2, 2)

    assert excerpt is not None
    assert "before" in excerpt
    assert "after" in excerpt
    assert "super-secret-value" not in excerpt
    assert "[REDACTED]" in excerpt


def test_read_excerpt_returns_none_for_invalid_location(tmp_path: Path) -> None:
    workspace, _ = make_workspace(tmp_path)

    assert validator(workspace).read_excerpt("pkg/mod.py", None, None) is None
    assert validator(workspace).read_excerpt("pkg/mod.py", 99, 99) is None


def test_missing_workspace_is_a_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(EvidenceValidationConfigurationError):
        CodeEvidenceValidator(tmp_path / "missing", [])


def test_missing_allowed_file_is_a_configuration_error(tmp_path: Path) -> None:
    workspace, _ = make_workspace(tmp_path)

    with pytest.raises(EvidenceValidationConfigurationError):
        CodeEvidenceValidator(workspace, ["pkg/missing.py"])


def test_directory_allowed_file_is_a_configuration_error(tmp_path: Path) -> None:
    workspace, _ = make_workspace(tmp_path)

    with pytest.raises(EvidenceValidationConfigurationError):
        CodeEvidenceValidator(workspace, ["pkg"])


def test_escape_through_allowed_file_is_a_configuration_error(
    tmp_path: Path,
) -> None:
    workspace, _ = make_workspace(tmp_path)
    (tmp_path / "outside.py").write_text("outside = 1\n", encoding="utf-8")

    with pytest.raises(EvidenceValidationConfigurationError):
        CodeEvidenceValidator(workspace, ["../outside.py"])
