from __future__ import annotations

import hashlib
import hmac
import time
from collections import defaultdict
from urllib.parse import parse_qsl


class AppProxyError(ValueError):
    pass


def canonicalize_query_string(raw_query: str) -> tuple[str, str | None]:
    values: dict[str, list[str]] = defaultdict(list)
    signature: str | None = None
    for key, value in parse_qsl(raw_query, keep_blank_values=True):
        if key == "signature":
            signature = value
            continue
        values[key].append(value)
    message = "".join(f"{key}={','.join(values[key])}" for key in sorted(values))
    return message, signature


def verify_app_proxy(
    raw_query: str,
    secret: str,
    allowed_shop: str,
    max_age_seconds: int = 300,
    now: int | None = None,
) -> dict[str, str]:
    pairs = parse_qsl(raw_query, keep_blank_values=True)
    params: dict[str, str] = {}
    for key, value in pairs:
        if key not in params:
            params[key] = value

    message, supplied_signature = canonicalize_query_string(raw_query)
    if not supplied_signature:
        raise AppProxyError("Missing signature")
    calculated = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
    if not hmac.compare_digest(supplied_signature, calculated.hexdigest()):
        raise AppProxyError("Invalid signature")
    if params.get("shop", "").lower() != allowed_shop.lower():
        raise AppProxyError("Unexpected shop")
    try:
        timestamp = int(params.get("timestamp", "0"))
    except ValueError as exc:
        raise AppProxyError("Invalid timestamp") from exc
    current = int(time.time()) if now is None else now
    if timestamp > current + 30 or current - timestamp > max_age_seconds:
        raise AppProxyError("Expired proxy request")
    return params
