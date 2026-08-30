from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any


class CursorError(ValueError):
    pass


@dataclass(slots=True)
class CursorCodec:
    secret: str
    ttl_seconds: int = 1800

    def encode(self, payload: dict[str, Any]) -> str:
        now = int(time.time())
        body = {**payload, "iat": now, "exp": now + self.ttl_seconds}
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(self.secret.encode("utf-8"), raw, hashlib.sha256).digest()
        return self._b64encode(raw) + "." + self._b64encode(signature)

    def decode(self, token: str, expected: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            body_part, signature_part = token.split(".", 1)
            raw = self._b64decode(body_part)
            signature = self._b64decode(signature_part)
        except (ValueError, TypeError) as exc:
            raise CursorError("Malformed cursor") from exc
        expected_signature = hmac.new(self.secret.encode("utf-8"), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected_signature):
            raise CursorError("Invalid cursor signature")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CursorError("Invalid cursor payload") from exc
        if int(payload.get("exp", 0)) < int(time.time()):
            raise CursorError("Expired cursor")
        if expected:
            for key, value in expected.items():
                if payload.get(key) != value:
                    raise CursorError(f"Cursor does not belong to this {key}")
        return payload

    @staticmethod
    def query_hash(query: str) -> str:
        return hashlib.sha256(query.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _b64encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    @staticmethod
    def _b64decode(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
