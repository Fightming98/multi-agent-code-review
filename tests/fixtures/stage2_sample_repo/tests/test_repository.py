"""Repository tests for the Stage 2 sample fixture."""

from sample_app.repository import UserRepository


class FakeConnection:
    """Record statements and return one deterministic row."""

    def __init__(self):
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)
        return [{"id": 1, "name": "ada"}]


def test_find_user_builds_query():
    connection = FakeConnection()
    repository = UserRepository(connection)
    assert repository.find_user("ada") == [{"id": 1, "name": "ada"}]


def test_list_users_returns_rows():
    connection = FakeConnection()
    repository = UserRepository(connection)
    assert repository.list_users() == [{"id": 1, "name": "ada"}]
