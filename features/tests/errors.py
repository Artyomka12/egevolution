"""Safe public errors for the tests feature, independent of Flask and SQLite."""
from copy import deepcopy


class TestsError(Exception):
    """A deliberately public message and explicitly selected response details.

    Callers must never pass exception text, SQL, paths, tokens or raw database
    rows as message/details. Technical exceptions belong in server handling.
    """

    def __init__(self, code, status, message, details=None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message
        self.details = deepcopy(details) if details is not None else {}
