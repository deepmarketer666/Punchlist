"""HTTP route blueprints."""

from flask import request

from ..validation import HttpError


def json_body() -> dict:
    """Returns the JSON object body, or raises a clean 400 for malformed input."""
    if not request.get_data(cache=True):
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise HttpError(400, "Request body must be valid JSON")
    if not isinstance(body, dict):
        raise HttpError(400, "Request body must be a JSON object")
    return body
