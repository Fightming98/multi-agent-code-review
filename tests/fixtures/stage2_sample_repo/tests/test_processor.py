"""Processor tests for the Stage 2 sample fixture."""

from sample_app.processor import classify_record, find_duplicates, read_records


def test_classify_record_handles_missing_record():
    assert classify_record(None) == "missing"


def test_find_duplicates_returns_repeated_values():
    assert find_duplicates(["a", "b", "a", "c", "b"]) == ["a", "b"]


def test_read_records_skips_blank_lines(tmp_path):
    path = tmp_path / "records.txt"
    path.write_text("one\n\ntwo\n", encoding="utf-8")
    assert read_records(path) == ["one", "two"]
