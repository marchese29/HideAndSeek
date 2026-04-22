"""Raw ASGI middleware for structured request/response access logging."""

from __future__ import annotations

import re
import time
import uuid
from typing import Any

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

SKIP_PATHS = {'/healthz'}
MAX_REQUEST_BODY_LOG_BYTES = 1024
MAX_RESPONSE_BODY_LOG_BYTES = 5 * 1024
REDACTED_HEADERS = {'authorization', 'cookie', 'x-player-secret'}
SSE_CONTENT_TYPE_PREFIX = b'text/event-stream'

# Redact values for any JSON string field whose key contains "secret" or "token"
# (case-insensitive). Catches `player_secret`, `device_token`, etc. by default so
# new sensitive fields don't need a path-by-path allowlist.
_SENSITIVE_JSON_VALUE = re.compile(
    r'("[^"]*(?:secret|token)[^"]*"\s*:\s*)"[^"]*"',
    re.IGNORECASE,
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger('hideandseek.access')


class _RequestCapture:
    """Per-request state buffer for request body, response body, and status.

    Exposes `receive` and `send` methods that wrap the ASGI callables; the
    middleware hands these to the app, and the capture object accumulates
    state the finally-block will later format into the log line.
    """

    def __init__(self, receive: Any, send: Any, request_id: str) -> None:
        self._receive = receive
        self._send = send
        self._request_id = request_id

        self.request_body = bytearray()
        self.response_body = bytearray()
        self.status_code = 0
        self.response_body_size = 0
        self.capture_response_body = True

        self._request_body_complete = False

    async def receive(self) -> dict[str, Any]:
        message = await self._receive()
        if message.get('type') == 'http.request' and not self._request_body_complete:
            chunk = message.get('body', b'')
            self._append_capped(self.request_body, chunk, MAX_REQUEST_BODY_LOG_BYTES)
            if not message.get('more_body', False):
                self._request_body_complete = True
        return message

    async def send(self, message: dict[str, Any]) -> None:
        if message['type'] == 'http.response.start':
            self.status_code = message.get('status', 0)
            headers: list[tuple[bytes, bytes]] = list(message.get('headers', []))
            for name, value in headers:
                if name.lower() == b'content-type':
                    if value.lower().startswith(SSE_CONTENT_TYPE_PREFIX):
                        self.capture_response_body = False
                    break
            headers.append((b'x-request-id', self._request_id.encode()))
            message = {**message, 'headers': headers}
        elif message['type'] == 'http.response.body':
            chunk = message.get('body', b'')
            self.response_body_size += len(chunk)
            if self.capture_response_body:
                self._append_capped(self.response_body, chunk, MAX_RESPONSE_BODY_LOG_BYTES)
        await self._send(message)

    @staticmethod
    def _append_capped(buffer: bytearray, chunk: bytes, cap: int) -> None:
        if len(buffer) >= cap:
            return
        buffer.extend(chunk[: cap - len(buffer)])


class AccessLogMiddleware:
    """ASGI middleware that logs every request/response via structlog.

    Uses raw ASGI (not Starlette's BaseHTTPMiddleware) for better performance
    and compatibility with streaming responses.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        path = scope.get('path', '')
        if path in SKIP_PATHS:
            await self.app(scope, receive, send)
            return

        clear_contextvars()

        request_id = str(uuid.uuid4())
        method = scope.get('method', '')
        query_string = scope.get('query_string', b'').decode('utf-8', errors='replace')
        headers = _parse_headers(scope.get('headers', []))

        bind_contextvars(request_id=request_id, method=method, path=path)

        capture = _RequestCapture(receive, send, request_id)
        start = time.monotonic()

        try:
            await self.app(scope, capture.receive, capture.send)
        finally:
            duration_ms = round((time.monotonic() - start) * 1000, 2)

            log_kwargs: dict[str, Any] = {
                'query': query_string,
                'headers': headers,
                'status': capture.status_code,
                'duration_ms': duration_ms,
                'response_size': capture.response_body_size,
            }

            request_body = _format_body(bytes(capture.request_body), MAX_REQUEST_BODY_LOG_BYTES)
            if request_body:
                log_kwargs['request_body'] = request_body

            if capture.capture_response_body:
                response_body = _format_body(
                    bytes(capture.response_body),
                    MAX_RESPONSE_BODY_LOG_BYTES,
                    capture.response_body_size,
                )
                if response_body:
                    log_kwargs['response_body'] = response_body

            logger.info('request', **log_kwargs)


def _parse_headers(raw_headers: list[tuple[bytes, bytes]]) -> dict[str, str]:
    """Parse ASGI headers into a dict, redacting sensitive values."""
    result: dict[str, str] = {}
    for name_bytes, value_bytes in raw_headers:
        name = name_bytes.decode('latin-1').lower()
        if name in REDACTED_HEADERS:
            result[name] = '[REDACTED]'
        else:
            result[name] = value_bytes.decode('latin-1')
    return result


def _format_body(body: bytes, cap: int, total_size: int | None = None) -> str:
    """Decode + redact a captured body for logging.

    `total_size` is the full byte count when the body was truncated during
    capture (response path). When omitted, `len(body)` is used (request path).
    """
    if not body:
        return ''
    text = body.decode('utf-8', errors='replace')
    text = _SENSITIVE_JSON_VALUE.sub(r'\1"[REDACTED]"', text)
    full = total_size if total_size is not None else len(body)
    if full > cap:
        text += f'... ({full} bytes total)'
    return text
