"""HTTP utilities for API communication."""

import json
from collections.abc import Generator
from typing import TypeAlias

from requests import Response

from . import get_logger

logger = get_logger(__name__)


JsonObject: TypeAlias = dict | list | int | str
JsonGenerator: TypeAlias = Generator[JsonObject, None, None]


def _load_ndjson(response: Response) -> JsonGenerator:
    """Parse a newline-delimited JSON response into individual objects.

    Args:
        response: HTTP response with NDJSON content.

    Yields:
        Parsed JSON objects from each line.
    """
    yield from map(json.loads, response.iter_lines())


def _handle_response(
    response: Response,
    url: str,
) -> JsonObject | JsonGenerator | Response:
    """Route an HTTP response to the appropriate parser by Content-Type.

    Args:
        response: HTTP response to handle.
        url: Request URL (for logging).

    Returns:
        Parsed JSON, an NDJSON generator, or the raw response.

    Raises:
        requests.HTTPError: If the response status code indicates an error.
    """
    response.raise_for_status()
    content_type = response.headers.get("Content-Type")
    logger.info("HTTP call to URL %s returned successfully", url)
    logger.debug("Handling HTTP response with content-type %s", content_type)
    if content_type == "application/json":
        return json.loads(response.content)
    elif content_type == "application/x-ndjson":
        return _load_ndjson(response)
    else:
        logger.warning("Unrecognized content type %r in HTTP response", content_type)
        return response


def _get_headers(
    oauth_token: str | bool | None = None,
    content_type: str | bool | None = None,
    accept: str | bool | None = None,
) -> dict[str, str]:
    """Build HTTP headers for a Lichess API request.

    Args:
        oauth_token: Bearer token string, or falsy to omit.
        content_type: Content-Type header value, or falsy to omit.
        accept: Accept header value, or falsy to omit.

    Returns:
        Header dictionary ready for ``requests``.
    """
    headers: dict[str, str] = {}
    if oauth_token is not None and oauth_token:
        headers["Authorization"] = f"Bearer {oauth_token}"
    if content_type is not None and content_type:
        headers["Content-Type"] = content_type
    if accept is not None and accept:
        headers["Accept"] = accept
    return headers
