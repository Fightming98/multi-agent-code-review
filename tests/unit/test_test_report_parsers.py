"""Pytest JUnit 与 Coverage JSON 解析器的单元测试。"""

from __future__ import annotations

import json
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from code_review.tools.test_runner import (
    TestReportParseError as ReportParseError,
)
from code_review.tools.test_runner import (
    parse_coverage_json,
    parse_junit_xml,
)


def junit_document(body: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        "<testsuites><testsuite>"
        f"{body}"
        "</testsuite></testsuites>"
    ).encode()


def write_junit(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "junit.xml"
    path.write_bytes(junit_document(body))
    return path


def coverage_payload(
    fixture_root: Path,
    *,
    overall: float = 87.5,
    files: dict[str, object] | None = None,
) -> dict[str, object]:
    if files is None:
        files = {
            str(fixture_root / "calc" / "core.py"): {
                "summary": {
                    "percent_covered": 80.0,
                    "covered_lines": 8,
                    "num_statements": 10,
                },
                "missing_lines": [12, 13],
            },
            "calc/__init__.py": {
                "summary": {
                    "percent_covered": 100.0,
                    "covered_lines": 1,
                    "num_statements": 1,
                },
                "missing_lines": [],
            },
        }
    return {
        "meta": {"version": "7.17.2"},
        "totals": {"percent_covered": overall},
        "files": files,
    }


def write_coverage(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_parse_junit_maps_counts_and_records(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    (fixture_root / "tests").mkdir()
    (fixture_root / "tests" / "test_core.py").write_text(
        "x = 1\n",
        encoding="utf-8",
    )
    body = (
        '<testcase classname="tests.test_core" name="test_add" time="0.1" />'
        '<testcase classname="tests.test_core" name="test_fail" time="0.2">'
        f'<failure message="boom" type="AssertionError">{escape(str(fixture_root))}</failure>'
        "</testcase>"
        '<testcase classname="tests.test_core" name="test_skip">'
        '<skipped message="not today" />'
        "</testcase>"
        '<testcase classname="tests.test_core" name="test_error">'
        '<error message="error" />'
        "</testcase>"
    )

    report = parse_junit_xml(
        write_junit(tmp_path, body),
        fixture_root,
        max_bytes=1024 * 1024,
        max_records=10,
    )

    assert report.total == 4
    assert report.passed == 1
    assert report.failed == 1
    assert report.errors == 1
    assert report.skipped == 1
    assert report.failure_count == 2
    assert report.duration_seconds == pytest.approx(0.3)
    assert report.records_truncated is False
    assert len(report.records) == 4
    failed = next(record for record in report.records if record.outcome == "failed")
    assert failed.file_path == "tests/test_core.py"
    assert failed.message is not None
    assert "<fixture>" in failed.message
    assert str(fixture_root) not in failed.message


def test_parse_junit_without_cases_returns_empty_report(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()

    report = parse_junit_xml(
        write_junit(tmp_path, ""),
        fixture_root,
        max_bytes=1024 * 1024,
        max_records=10,
    )

    assert report.total == 0
    assert report.records == ()
    assert report.records_truncated is False


def test_parse_junit_caps_records_but_keeps_counts(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    body = "".join(
        f'<testcase classname="tests.test_core" name="test_{index}" />'
        for index in range(5)
    )

    report = parse_junit_xml(
        write_junit(tmp_path, body),
        fixture_root,
        max_bytes=1024 * 1024,
        max_records=2,
    )

    assert report.total == 5
    assert report.passed == 5
    assert len(report.records) == 2
    assert report.records_truncated is True


def test_parse_junit_rejects_invalid_xml(tmp_path: Path) -> None:
    path = tmp_path / "junit.xml"
    path.write_bytes(b"<testsuites>")

    with pytest.raises(ReportParseError, match="XML"):
        parse_junit_xml(
            path,
            tmp_path,
            max_bytes=1024,
            max_records=10,
        )


def test_parse_junit_rejects_doctype(tmp_path: Path) -> None:
    path = tmp_path / "junit.xml"
    path.write_bytes(
        b'<!DOCTYPE testsuites [<!ENTITY x "y">]><testsuites />'
    )

    with pytest.raises(ReportParseError, match="document type"):
        parse_junit_xml(
            path,
            tmp_path,
            max_bytes=1024,
            max_records=10,
        )


def test_parse_junit_rejects_doctype_after_large_prefix(tmp_path: Path) -> None:
    path = tmp_path / "junit.xml"
    path.write_bytes(
        b" " * 5000
        + b'<!DOCTYPE testsuites [<!ENTITY x "y">]><testsuites />'
    )

    with pytest.raises(ReportParseError, match="document type"):
        parse_junit_xml(
            path,
            tmp_path,
            max_bytes=64 * 1024,
            max_records=10,
        )


def test_parse_junit_rejects_oversized_report(tmp_path: Path) -> None:
    path = write_junit(
        tmp_path,
        '<testcase name="test_one" />' * 20,
    )

    with pytest.raises(ReportParseError, match="size"):
        parse_junit_xml(
            path,
            tmp_path,
            max_bytes=32,
            max_records=10,
        )


def test_parse_junit_rejects_file_outside_fixture(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("x = 1\n", encoding="utf-8")
    body = (
        '<testcase classname="tests.test_core" name="test_one" '
        f'file="{escape(str(outside))}" />'
    )

    with pytest.raises(ReportParseError, match="outside"):
        parse_junit_xml(
            write_junit(tmp_path, body),
            fixture_root,
            max_bytes=1024 * 1024,
            max_records=10,
        )


def test_parse_junit_rejects_wrong_root(tmp_path: Path) -> None:
    path = tmp_path / "junit.xml"
    path.write_bytes(b"<root />")

    with pytest.raises(ReportParseError, match="root"):
        parse_junit_xml(
            path,
            tmp_path,
            max_bytes=1024,
            max_records=10,
        )


def test_parse_coverage_maps_overall_and_files(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    (fixture_root / "calc").mkdir()
    (fixture_root / "calc" / "core.py").write_text("x = 1\n", encoding="utf-8")

    report = parse_coverage_json(
        write_coverage(tmp_path, coverage_payload(fixture_root)),
        fixture_root,
        max_bytes=1024 * 1024,
        max_files=100,
    )

    assert report.percent_covered == 87.5
    assert [item.file_path for item in report.files] == [
        "calc/__init__.py",
        "calc/core.py",
    ]
    assert report.files[1].percent_covered == 80.0
    assert report.files[1].missing_lines == (12, 13)
    assert report.files_truncated is False


def test_parse_coverage_accepts_empty_files(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()

    report = parse_coverage_json(
        write_coverage(
            tmp_path,
            coverage_payload(fixture_root, overall=0.0, files={}),
        ),
        fixture_root,
        max_bytes=1024 * 1024,
        max_files=100,
    )

    assert report.percent_covered == 0.0
    assert report.files == ()


def test_parse_coverage_caps_files(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    (fixture_root / "calc").mkdir()
    for index in range(3):
        (fixture_root / "calc" / f"module_{index}.py").write_text(
            "x = 1\n",
            encoding="utf-8",
        )
    files = {
        str(fixture_root / "calc" / f"module_{index}.py"): {
            "summary": {
                "percent_covered": 100.0,
                "covered_lines": 1,
                "num_statements": 1,
            },
            "missing_lines": [],
        }
        for index in range(3)
    }

    report = parse_coverage_json(
        write_coverage(tmp_path, coverage_payload(fixture_root, files=files)),
        fixture_root,
        max_bytes=1024 * 1024,
        max_files=2,
    )

    assert len(report.files) == 2
    assert report.files_truncated is True


def test_parse_coverage_rejects_missing_totals(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()

    with pytest.raises(ReportParseError, match="structure"):
        parse_coverage_json(
            write_coverage(tmp_path, {"files": {}}),
            fixture_root,
            max_bytes=1024,
            max_files=10,
        )


def test_parse_coverage_rejects_invalid_percentage(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()

    with pytest.raises(ReportParseError, match="coverage"):
        parse_coverage_json(
            write_coverage(tmp_path, coverage_payload(fixture_root, overall=101.0)),
            fixture_root,
            max_bytes=1024 * 1024,
            max_files=10,
        )


def test_parse_coverage_rejects_inconsistent_lines(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    files = {
        "calc/core.py": {
            "summary": {
                "percent_covered": 100.0,
                "covered_lines": 5,
                "num_statements": 3,
            },
            "missing_lines": [],
        }
    }

    with pytest.raises(ReportParseError, match="line counts"):
        parse_coverage_json(
            write_coverage(tmp_path, coverage_payload(fixture_root, files=files)),
            fixture_root,
            max_bytes=1024 * 1024,
            max_files=10,
        )


def test_parse_coverage_rejects_path_outside_fixture(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    files = {
        str(tmp_path / "outside.py"): {
            "summary": {
                "percent_covered": 100.0,
                "covered_lines": 1,
                "num_statements": 1,
            },
            "missing_lines": [],
        }
    }

    with pytest.raises(ReportParseError, match="outside"):
        parse_coverage_json(
            write_coverage(tmp_path, coverage_payload(fixture_root, files=files)),
            fixture_root,
            max_bytes=1024 * 1024,
            max_files=10,
        )


def test_parse_coverage_rejects_duplicate_keys(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    path = tmp_path / "coverage.json"
    path.write_bytes(
        b'{"totals": {"percent_covered": 1.0}, '
        b'"files": {"a.py": {}, "a.py": {}}}'
    )

    with pytest.raises(ReportParseError, match="duplicate"):
        parse_coverage_json(
            path,
            fixture_root,
            max_bytes=1024 * 1024,
            max_files=10,
        )


def test_parse_coverage_rejects_oversized_report(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    path = write_coverage(tmp_path, coverage_payload(fixture_root))

    with pytest.raises(ReportParseError, match="size"):
        parse_coverage_json(
            path,
            fixture_root,
            max_bytes=16,
            max_files=10,
        )
