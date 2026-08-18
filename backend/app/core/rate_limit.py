from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response


# Machine-to-machine endpoints a fleet system drives, not a person.
# A real AVL feed pushes far harder than any human browsing the app, and the
# per-IP budget here would throttle it into uselessness -- vehicle positions
# would arrive in bursts and then stop, which looks exactly like a broken feed.
# Exempt from the budget, not from authentication: /avl/ingest requires a
# shared secret in X-AVL-Key and rejects everything without it.
EXEMPT_PATH_PREFIXES = ("/avl/ingest",)


class RateLimitMiddleware:
    def __init__(self, app, max_requests_per_minute: int = 120, trust_proxy_headers: bool = False) -> None:
        self.app = app
        self.max_requests = max_requests_per_minute
        self.trust_proxy_headers = trust_proxy_headers
        self.window_seconds = 60
        self.requests: dict[str, deque[float]] = defaultdict(deque)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Skip rate limiting for CORS preflight requests
        if scope["method"] == "OPTIONS":
            await self.app(scope, receive, send)
            return

        if scope.get("path", "").startswith(EXEMPT_PATH_PREFIXES):
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        if self.trust_proxy_headers and "x-forwarded-for" in request.headers:
            client = request.headers["x-forwarded-for"].split(",")[0].strip()
        else:
            client = request.client.host if request.client else "anonymous"
        now = time.time()
        # Evict stale IP deques periodically to avoid unbounded memory usage
        if len(self.requests) > 500:
            stale = [ip for ip, deq in self.requests.items() if not deq or deq[-1] <= now - self.window_seconds]
            for ip in stale:
                del self.requests[ip]

        bucket = self.requests[client]
        while bucket and bucket[0] <= now - self.window_seconds:
            bucket.popleft()
        if len(bucket) >= self.max_requests:
            response = JSONResponse(
                {"detail": "Rate limit exceeded. Please retry in a moment."},
                status_code=429,
            )
            await response(scope, receive, send)
            return
        bucket.append(now)
        await self.app(scope, receive, send)
