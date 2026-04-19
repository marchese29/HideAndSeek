"""Raw ASGI middleware for structured request/response access logging."""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

SKIP_PATHS = {'/healthz'}
MAX_BODY_LOG_BYTES = 1024
REDACTED_HEADERS = {'authorization', 'cookie'}

logger: structlog.stdlib.BoundLogger = structlog.get_logger('hideandseek.access')


class AccessLogMiddleware:
    """ASGI middleware that logs every request/response via structlog.

    Uses raw ASGI (not Starlette's BaseHTTPMiddleware) for better
    performance and compatibility with streaming responses.
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

        # Capture request body
        request_body = b''
        body_complete = False

        async def receive_wrapper() -> dict[str, Any]:
            nonlocal request_body, body_complete
            message = await receive()
            if message.get('type') == 'http.request' and not body_complete:
                chunk = message.get('body', b'')
                request_body += chunk
                if not message.get('more_body', False):
                    body_complete = True
            return message

        # Capture response status and body size
        status_code = 0
        response_body_size = 0

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status_code, response_body_size
            if message['type'] == 'http.response.start':
                status_code = message.get('status', 0)
                # Inject X-Request-ID header
                response_headers: list[tuple[bytes, bytes]] = list(message.get('headers', []))
                response_headers.append((b'x-request-id', request_id.encode()))
                message = {**message, 'headers': response_headers}
            elif message['type'] == 'http.response.body':
                response_body_size += len(message.get('body', b''))
            await send(message)

        start = time.monotonic()

        try:
            await self.app(scope, receive_wrapper, send_wrapper)
        finally:
            duration_ms = round((time.monotonic() - start) * 1000, 2)

            # Truncate request body for logging
            body_str = ''
            if request_body:
                body_preview = request_body[:MAX_BODY_LOG_BYTES]
                body_str = body_preview.decode('utf-8', errors='replace')
                if len(request_body) > MAX_BODY_LOG_BYTES:
                    body_str += f'... ({len(request_body)} bytes total)'

            log_kwargs: dict[str, Any] = {
                'query': query_string,
                'headers': headers,
                'status': status_code,
                'duration_ms': duration_ms,
                'response_size': response_body_size,
            }
            if body_str:
                log_kwargs['request_body'] = body_str

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
