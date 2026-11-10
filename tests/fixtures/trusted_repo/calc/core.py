"""可信 Fixture 的示例计算模块。"""


def add(a: int, b: int) -> int:
    """返回两个整数之和。"""

    return a + b


def divide(a: float, b: float) -> float:
    """返回两个数之商；除数为零时抛出 ValueError。"""

    if b == 0:
        raise ValueError("division by zero")
    return a / b


def multiply(a: int, b: int) -> int:
    """返回两个整数之积；Fixture 测试故意不覆盖本函数。"""

    return a * b
