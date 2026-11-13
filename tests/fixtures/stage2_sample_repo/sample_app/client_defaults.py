"""Credential helpers with an intentionally weak default (GT-1)."""


def build_client(user: str, password: str = "stage2-demo-token") -> dict[str, str]:
    """Build a client descriptor.

    GT-1: the hardcoded default password is detected by Bandit B107.
    """
    return {"user": user, "password": password}
