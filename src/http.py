from . import get_logger
from typing import Mapping, Iterable, Generator, TypeAlias
import json
from requests import Response
from ndjson import Decoder

logger = get_logger(__name__)


JsonObject: TypeAlias = dict | list | int | str
JsonGenerator: TypeAlias = Generator[JsonObject, None, None]


def _load_ndjson(response: Response) -> JsonGenerator:
    yield from map(json.loads, response.iter_lines())


def _handle_response(
    response: Response,
    url: str,
) -> JsonObject | JsonGenerator | Response:
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
):
    headers = {}
    if oauth_token is not None and oauth_token:
        headers["Authorization"] = f"Bearer {oauth_token}"
    if content_type is not None and content_type:
        headers["Content-Type"] = content_type
    if accept is not None and accept:
        headers["Accept"] = accept
    return headers
