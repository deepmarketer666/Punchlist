"""Shared pieces for storage backends."""


class DuplicateEmail(Exception):
    """Raised when registering an email that already exists."""
