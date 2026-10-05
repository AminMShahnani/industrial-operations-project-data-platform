from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestBodyLimit:
    """Bound actual streamed bytes before JSON parsing, including chunked requests."""

    def __init__(self, app: ASGIApp, maximum: int = 8 * 1024 * 1024) -> None:
        self.app, self.maximum = app, maximum

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        messages: list[Message] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.maximum:
                response = JSONResponse(
                    {
                        "type": "about:blank",
                        "title": "Request too large",
                        "status": 413,
                        "code": "request_too_large",
                        "request_id": scope.get("state", {}).get("request_id", "unknown"),
                    },
                    status_code=413,
                    media_type="application/problem+json",
                )
                await response(scope, receive, send)
                return
            messages.append(message)
            if not message.get("more_body", False):
                break
        iterator = iter(messages)

        async def buffered() -> Message:
            item = next(iterator, None)
            return item if item is not None else await receive()

        await self.app(scope, buffered, send)
