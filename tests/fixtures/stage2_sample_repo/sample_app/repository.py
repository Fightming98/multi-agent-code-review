"""User repository helpers with an intentionally unsafe query (GT-2)."""


class UserRepository:
    """Minimal repository facade used by the sample tests."""

    def __init__(self, connection):
        self._connection = connection

    def find_user(self, name: str):
        """Look up a user by name.

        GT-2: the concatenated SQL statement is detected by Bandit B608.
        """
        query = "SELECT id, name FROM users WHERE name = '" + name + "'"
        return self._connection.execute(query)

    def list_users(self):
        """Return every user row."""
        return self._connection.execute("SELECT id, name FROM users")
