from typing import Any

from psycopg import sql


class Cursor:
    def __init__(self, rows: Any):
        self.rows = rows

    async def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, *results, commit_error=None):
        self.results = list(results)
        self.queries = []
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self.commit_error = commit_error

    async def execute(self, query, params=None):
        self.queries.append(
            (query.as_string() if isinstance(query, sql.Composable) else query, params)
        )
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return Cursor(result)

    async def __aenter__(self):
        return self

    async def __aexit__(self, kind, value, tb):
        self.closed = True
        self.rolled_back = kind is not None
        if kind is None:
            if self.commit_error:
                raise self.commit_error
            self.committed = True
