"""GitHub URL、分支名与 Commit SHA 安全校验测试。"""

from __future__ import annotations

import pytest

from src.code_review.tools.url_validator import (
    URLValidationError,
    is_full_commit_sha,
    normalize_commit_sha,
    validate_branch_name,
    validate_github_url,
)

FULL_SHA = "9fceb02d0ae598e95dc970b74767f19372d61af8"


@pytest.mark.parametrize(
    ("raw_url", "owner", "name", "canonical"),
    [
        (
            "https://github.com/pallets/itsdangerous",
            "pallets",
            "itsdangerous",
            "https://github.com/pallets/itsdangerous",
        ),
        (
            "https://github.com/pallets/itsdangerous.git",
            "pallets",
            "itsdangerous",
            "https://github.com/pallets/itsdangerous",
        ),
        (
            "https://github.com/pallets/itsdangerous/",
            "pallets",
            "itsdangerous",
            "https://github.com/pallets/itsdangerous",
        ),
        (
            "https://github.com/pallets/itsdangerous.git/",
            "pallets",
            "itsdangerous",
            "https://github.com/pallets/itsdangerous",
        ),
        (
            "https://github.com:443/pallets/itsdangerous",
            "pallets",
            "itsdangerous",
            "https://github.com/pallets/itsdangerous",
        ),
        (
            "https://GITHUB.COM/pallets/itsdangerous",
            "pallets",
            "itsdangerous",
            "https://github.com/pallets/itsdangerous",
        ),
        (
            "https://github.com/some-owner/repo.name",
            "some-owner",
            "repo.name",
            "https://github.com/some-owner/repo.name",
        ),
        (
            "https://github.com/some-owner/repo_name",
            "some-owner",
            "repo_name",
            "https://github.com/some-owner/repo_name",
        ),
        (
            "  https://github.com/pallets/itsdangerous  ",
            "pallets",
            "itsdangerous",
            "https://github.com/pallets/itsdangerous",
        ),
    ],
)
def test_valid_github_urls(raw_url: str, owner: str, name: str, canonical: str) -> None:
    repository = validate_github_url(raw_url)

    assert repository.owner == owner
    assert repository.name == name
    assert repository.canonical_url == canonical
    assert repository.full_name == f"{owner}/{name}"


@pytest.mark.parametrize(
    "raw_url",
    [
        "",
        "   ",
        "github.com/pallets/itsdangerous",
        "http://github.com/pallets/itsdangerous",
        "ftp://github.com/pallets/itsdangerous",
        "ssh://git@github.com/pallets/itsdangerous",
        "git://github.com/pallets/itsdangerous",
        "git@github.com:pallets/itsdangerous.git",
        "file:///C:/secret/repo",
        "file://github.com/pallets/itsdangerous",
        r"C:\secret\repo",
        r"\\server\share\repo",
        "/tmp/repo",
        "../repo",
        "https://user@github.com/pallets/itsdangerous",
        "https://user:pass@github.com/pallets/itsdangerous",
        "https://github.com.evil.com/pallets/itsdangerous",
        "https://evilgithub.com/pallets/itsdangerous",
        "https://github.com@evil.com/pallets/itsdangerous",
        "https://evil.com/github.com/pallets/itsdangerous",
        "https://140.82.112.3/pallets/itsdangerous",
        "https://github.com:8443/pallets/itsdangerous",
        "https://github.com:/pallets/itsdangerous",
        "https://github.com/pallets/itsdangerous?tab=readme",
        "https://github.com/pallets/itsdangerous#readme",
        "https://github.com/pallets",
        "https://github.com/",
        "https://github.com//pallets/itsdangerous",
        "https://github.com/pallets//itsdangerous",
        "https://github.com/pallets/itsdangerous/tree/main",
        "https://github.com/../pallets/itsdangerous",
        "https://github.com/pallets/..",
        "https://github.com/pallets/.",
        "https://github.com/pallets/.git",
        "https://github.com/pallets/repo.git.git",
        "https://github.com/pallets/a..b",
        "https://github.com/pallets/itsdangerous%2F..%2Fetc",
        "https://github.com/pallets/itsdangerous%00",
        "https://github.com/pallets/itsdangerous\\..\\etc",
        "https://github.com/pallets/its danger",
        "https://github.com/pallets/its\ndangerous",
        "https://github.com/pallets/its\x00dangerous",
        "https://github.com/-owner/repo",
        "https://github.com/owner-/repo",
        "https://github.com/some_owner/repo_name",
        "https://github.com/owner/repo;rm",
        "https://github.com/owner/repo|whoami",
        "https://github.com/owner/repo`whoami`",
        "https://github.com/" + "a" * 40 + "/repo",
        "https://github.com/owner/" + "a" * 101,
        "https://github.com/" + "a" * 2000 + "/repo",
    ],
)
def test_invalid_github_urls(raw_url: str) -> None:
    with pytest.raises(URLValidationError):
        validate_github_url(raw_url)


@pytest.mark.parametrize(
    "branch",
    [
        "main",
        "master",
        "feature/add-url-validation",
        "release/1.2",
        "fix_issue-123",
        "a" * 255,
    ],
)
def test_valid_branch_names(branch: str) -> None:
    assert validate_branch_name(branch) == branch


def test_branch_name_with_surrounding_whitespace_is_rejected() -> None:
    with pytest.raises(URLValidationError):
        validate_branch_name("  main  ")


@pytest.mark.parametrize(
    "branch",
    [
        "",
        "   ",
        "a" * 256,
        " feature/x",
        "feature x",
        "feature\tx",
        "feature\nx",
        "-upload-pack=evil",
        "--config=evil",
        "HEAD",
        "head",
        "@",
        ".hidden",
        "feature.",
        "feature..x",
        "feature@{x",
        "feature//x",
        "/feature",
        "feature/",
        "feature/.hidden",
        "feature/x.",
        "feature/x.lock",
        "feature.lock/x",
        "feature~x",
        "feature^x",
        "feature:x",
        "feature?x",
        "feature*x",
        "feature[x",
        r"feature\x",
    ],
)
def test_invalid_branch_names(branch: str) -> None:
    with pytest.raises(URLValidationError):
        validate_branch_name(branch)


@pytest.mark.parametrize("sha", [FULL_SHA, FULL_SHA.upper()])
def test_normalize_commit_sha(sha: str) -> None:
    assert normalize_commit_sha(sha) == FULL_SHA


@pytest.mark.parametrize(
    "sha",
    [
        "",
        "main",
        "HEAD",
        FULL_SHA[:7],
        FULL_SHA[:39],
        FULL_SHA + "0",
        "g" * 40,
    ],
)
def test_invalid_commit_sha(sha: str) -> None:
    with pytest.raises(URLValidationError):
        normalize_commit_sha(sha)


def test_commit_sha_is_stripped() -> None:
    assert normalize_commit_sha(f"  {FULL_SHA}  ") == FULL_SHA


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (FULL_SHA, True),
        (FULL_SHA.upper(), True),
        (FULL_SHA[:7], False),
        ("main", False),
        ("", False),
    ],
)
def test_is_full_commit_sha(value: str, expected: bool) -> None:
    assert is_full_commit_sha(value) is expected
