from __future__ import annotations


class RepositoryError(RuntimeError):
    """Base class for persistence failures."""


class NotFoundError(RepositoryError):
    """A by-id lookup found no row."""


class ConcurrentEditError(RepositoryError):
    """append_journal saw expected_version != actual_version. Caller
    should reload the variant, replay any new journal entries the
    UI hasn't seen yet, and re-prompt the user.
    """

    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(
            f"variant version mismatch: expected={expected}, actual={actual}"
        )
        self.expected = expected
        self.actual = actual
