"""可信 Fixture 的确定性测试。"""

import pytest
from calc import add, divide


def test_add() -> None:
    assert add(2, 3) == 5


def test_divide() -> None:
    assert divide(6, 3) == 2


def test_divide_by_zero() -> None:
    with pytest.raises(ValueError):
        divide(1, 0)


@pytest.mark.skip(reason="可信 Fixture 的固定跳过用例")
def test_skipped() -> None:
    assert True
