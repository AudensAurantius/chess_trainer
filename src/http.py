from . import get_logger
from typing import Mapping, Iterable
import json
from requests import Response
from ndjson import Decoder

logger = get_logger(__name__)


def _handle_response(response, url) -> Mapping | Iterable | Response:
    if not response.ok:
        logger.warning(
            "HTTP call to URL %s returned status code %s",
            url,
            response.status_code,
        )
        return response
    content_type = response.headers.get("Content-Type")
    logger.info("HTTP call to URL %s returned successfully", url)
    if content_type == "application/json":
        return json.loads(response.content)
    elif content_type == "application/x-ndjson":
        return response.json(cls=Decoder)
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
