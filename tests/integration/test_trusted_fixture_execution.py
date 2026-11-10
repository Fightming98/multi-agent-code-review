"""可信 Fixture 的真实 Pytest / Coverage 执行集成测试。

这些测试不联网，只执行项目自维护、清单哈希固定的
``tests/fixtures/trusted_repo/``，或测试运行时临时构造并立即校验的 Fixture。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_review.tools.test_runner import (
    TestExecutionStatus as ExecutionStatus,
)
from code_review.tools.test_runner import (
    TestRunner as Runner,
)
from code_review.tools.trusted_fixture import (
    DEFAULT_TRUSTED_FIXTURE_ROOT,
    verify_trusted_fixture,
)
from config.settings import Settings
from tests.fixture_factory import make_trusted_fixture

TRUSTED_FIXTURE = "trusted_fixture_v1"


def test_real_trusted_fixture_executes_with_coverage() -> None:
    verified = verify_trusted_fixture(expected_name=TRUSTED_FIXTURE)
    assert verified.name == TRUSTED_FIXTURE
    assert verified.version == "1.0.0"

    result = Runner(Settings(_env_file=None)).execute(
        trusted_fixture=TRUSTED_FIXTURE
    )

    assert result.status is ExecutionStatus.EXECUTED
    assert result.summary.execution_status == "executed"
    assert result.summary.passed == 3
    assert result.summary.failed == 0
    assert result.summary.skipped == 1
    assert result.summary.coverage == pytest.approx(90.0, abs=0.01)
    assert result.summary.source == "pytest+coverage"
    assert result.summary.reason is None
    assert result.collected_tests == 4
    assert result.has_failed_tests is False
    assert result.read_only_verified is True
    assert result.modified_paths == ()
    assert result.exit_code == 0
    assert result.coverage_exit_code == 0
    assert result.pytest_version == "9.2.0"
    assert result.coverage_version == "7.17.2"
    assert result.error is None
    assert {
        item.file_path for item in result.coverage_files
    } == {"calc/__init__.py", "calc/core.py"}
    assert all(
        record.file_path is None
        or not Path(record.file_path).is_absolute()
        for record in result.test_records
    )

    # 存储的输出与失败信息不得泄露 Fixture、临时工作区或宿主目录。
    host_root = str(DEFAULT_TRUSTED_FIXTURE_ROOT.resolve())
    texts = [result.stdout, result.stderr]
    texts.extend(record.message or "" for record in result.test_records)
    for text in texts:
        assert host_root not in text
        assert str(Path.home()) not in text

    # 执行过程不得在 Fixture 内产生缓存或字节码。
    assert not any(DEFAULT_TRUSTED_FIXTURE_ROOT.rglob(".pytest_cache"))
    assert not any(DEFAULT_TRUSTED_FIXTURE_ROOT.rglob("__pycache__"))
    assert not any(DEFAULT_TRUSTED_FIXTURE_ROOT.rglob("*.pyc"))


def test_modified_fixture_never_executes(tmp_path: Path) -> None:
    root = make_trusted_fixture(
        tmp_path / "fixture",
        {
            "calc/__init__.py": "from .core import add\n",
            "calc/core.py": "def add(a, b):\n    return a + b\n",
            "tests/test_core.py": (
                "from calc import add\n\n"
                "def test_add():\n"
                "    assert add(1, 2) == 3\n"
            ),
        },
    )
    (root / "calc" / "core.py").write_bytes(b"tampered = True\n")

    result = Runner(
        Settings(_env_file=None),
        fixture_root=root,
        allow_custom_fixture_root=True,
    ).execute(trusted_fixture=TRUSTED_FIXTURE)

    assert result.status is ExecutionStatus.FAILED
    assert result.summary.execution_status == "not_executed"
    assert result.summary.passed is None
    assert result.summary.coverage is None
    assert result.read_only_verified is None
    assert result.error is not None
    assert result.error.error_type == "invalid_input"


def test_pytest_timeout_is_enforced(tmp_path: Path) -> None:
    root = make_trusted_fixture(
        tmp_path / "fixture",
        {
            "pkg/__init__.py": "",
            "pkg/core.py": "def identity(value):\n    return value\n",
            "tests/test_slow.py": (
                "import time\n\n"
                "def test_slow():\n"
                "    time.sleep(20)\n"
            ),
        },
    )

    result = Runner(
        Settings(_env_file=None, pytest_timeout_seconds=1),
        fixture_root=root,
        allow_custom_fixture_root=True,
    ).execute(trusted_fixture=TRUSTED_FIXTURE)

    assert result.status is ExecutionStatus.TIMEOUT
    assert result.summary.execution_status == "failed"
    assert result.read_only_verified is True
    assert result.error is not None
    assert result.error.error_type == "timeout"
    assert result.error.retryable is True


def test_workspace_mutation_is_detected(tmp_path: Path) -> None:
    root = make_trusted_fixture(
        tmp_path / "fixture",
        {
            "pkg/__init__.py": "",
            "pkg/core.py": "def identity(value):\n    return value\n",
            "tests/test_write.py": (
                "from pathlib import Path\n\n"
                "def test_writes_into_fixture():\n"
                "    Path(__file__).with_name('written.txt').write_text(\n"
                "        'mutation', encoding='utf-8'\n"
                "    )\n"
            ),
        },
    )

    result = Runner(
        Settings(_env_file=None),
        fixture_root=root,
        allow_custom_fixture_root=True,
    ).execute(trusted_fixture=TRUSTED_FIXTURE)

    assert result.status is ExecutionStatus.FAILED
    assert result.summary.execution_status == "failed"
    assert result.read_only_verified is False
    assert "tests/written.txt" in result.modified_paths
    assert result.error is not None
    assert result.error.error_type == "read_only_violation"
