from __future__ import annotations

"""Compatibility layer for environments without FastAPI installed."""

from dataclasses import dataclass
import inspect
import json
import re
from typing import Any, Awaitable, Callable, Iterable, get_args, get_origin
from urllib.parse import parse_qs


class HTTPException(Exception):
    """Minimal HTTP exception compatible with FastAPI-style handlers."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class Response:
    content: bytes
    status_code: int = 200
    media_type: str = "application/json"
    headers: dict[str, str] | None = None

    def to_asgi(self) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
        body = self.content if isinstance(self.content, bytes) else str(self.content).encode("utf-8")
        headers = [(b"content-type", self.media_type.encode("utf-8"))]
        for key, value in (self.headers or {}).items():
            headers.append((key.encode("utf-8"), value.encode("utf-8")))
        return self.status_code, headers, body


class JSONResponse(Response):
    def __init__(self, content: Any, status_code: int = 200) -> None:
        super().__init__(json.dumps(content, default=str).encode("utf-8"), status_code=status_code, media_type="application/json")


class PlainTextResponse(Response):
    def __init__(self, content: str, status_code: int = 200) -> None:
        super().__init__(content.encode("utf-8"), status_code=status_code, media_type="text/plain; charset=utf-8")


class FileResponse(Response):
    def __init__(self, path: str, media_type: str = "application/octet-stream", filename: str | None = None) -> None:
        data = open(path, "rb").read()
        headers = {}
        if filename:
            headers["content-disposition"] = f'attachment; filename="{filename}"'
        super().__init__(data, status_code=200, media_type=media_type, headers=headers)


class Request:
    def __init__(self, method: str, path: str, query_string: str = "", headers: dict[str, str] | None = None) -> None:
        self.method = method.upper()
        self.path = path
        self.query_params = {key: values[-1] for key, values in parse_qs(query_string, keep_blank_values=True).items()}
        self.headers = headers or {}


class _Route:
    def __init__(self, path: str, methods: Iterable[str], endpoint: Callable[..., Any]) -> None:
        self.path = path
        self.methods = {method.upper() for method in methods}
        self.endpoint = endpoint
        self.param_names = re.findall(r"{([^}]+)}", path)
        pattern = re.escape(path)
        for name in self.param_names:
            pattern = pattern.replace(r"\{" + re.escape(name) + r"\}", fr"(?P<{name}>[^/]+)")
        self.regex = re.compile("^" + pattern + "$")

    def match(self, path: str) -> dict[str, str] | None:
        match = self.regex.match(path)
        if not match:
            return None
        return match.groupdict()


class APIRouter:
    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix.rstrip("/")
        self.routes: list[_Route] = []

    def get(self, path: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.routes.append(_Route(self.prefix + path, ["GET"], func))
            return func

        return decorator


class CORSMiddleware:  # pragma: no cover - placeholder
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs


class FastAPI:
    def __init__(self, title: str = "API", version: str = "1.0.0") -> None:
        self.title = title
        self.version = version
        self.routes: list[_Route] = []
        self.middleware_stack: list[tuple[Any, dict[str, Any]]] = []

    def add_middleware(self, middleware_class: Any, **kwargs: Any) -> None:
        self.middleware_stack.append((middleware_class, kwargs))

    def include_router(self, router: APIRouter, prefix: str = "") -> None:
        prefix = prefix.rstrip("/")
        for route in router.routes:
            route.path = prefix + route.path
            pattern = re.escape(route.path)
            for name in route.param_names:
                pattern = pattern.replace(r"\{" + re.escape(name) + r"\}", fr"(?P<{name}>[^/]+)")
            route.regex = re.compile("^" + pattern + "$")
            self.routes.append(route)

    def get(self, path: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        router = APIRouter()
        return router.get(path)

    def route(self, method: str, path: str, endpoint: Callable[..., Any]) -> None:
        self.routes.append(_Route(path, [method], endpoint))

    async def __call__(self, scope: dict[str, Any], receive: Callable[..., Awaitable[dict[str, Any]]], send: Callable[..., Awaitable[None]]) -> None:
        if scope.get("type") != "http":
            return
        request = Request(scope.get("method", "GET"), scope.get("path", "/"), scope.get("query_string", b"").decode("utf-8"))
        route, path_params = self._resolve_route(request.method, request.path)
        started = 0.0
        status_code = 500
        if route is None:
            response = JSONResponse({"detail": "Not Found"}, status_code=404)
            status_code = 404
        else:
            try:
                import time

                started = time.time()
                result = self._invoke(route.endpoint, request, path_params)
                response = self._coerce_response(result)
                status_code = response.status_code
            except HTTPException as exc:
                response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
                status_code = exc.status_code
            except Exception as exc:  # pragma: no cover - defensive
                response = JSONResponse({"detail": str(exc)}, status_code=500)
                status_code = 500
        status_code, headers, body = response.to_asgi()
        if hasattr(self, "request_logger") and route is not None:
            try:
                import time

                duration = time.time() - started if started else 0.0
                self.request_logger(request.method, request.path, response.status_code, duration)
            except Exception:  # pragma: no cover - defensive
                pass
        await send({"type": "http.response.start", "status": status_code, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    def _resolve_route(self, method: str, path: str) -> tuple[_Route | None, dict[str, str]]:
        for route in self.routes:
            if method.upper() not in route.methods:
                continue
            params = route.match(path)
            if params is not None:
                return route, params
        return None, {}

    def _coerce_response(self, result: Any) -> Response:
        if isinstance(result, Response):
            return result
        if isinstance(result, (bytes, bytearray)):
            return Response(bytes(result), media_type="application/octet-stream")
        if isinstance(result, str):
            return PlainTextResponse(result)
        return JSONResponse(result)

    def _invoke(self, endpoint: Callable[..., Any], request: Request, path_params: dict[str, str]) -> Any:
        signature = inspect.signature(endpoint)
        kwargs: dict[str, Any] = {}
        for name, parameter in signature.parameters.items():
            if name == "request":
                kwargs[name] = request
                continue
            if name in path_params:
                kwargs[name] = path_params[name]
                continue
            if name in request.query_params:
                raw = request.query_params[name]
                annotation = parameter.annotation
                origin = get_origin(annotation)
                args = get_args(annotation)
                scalar_type = annotation
                if origin is None and args:
                    scalar_type = args[0]
                elif origin is not None and args:
                    scalar_type = next((arg for arg in args if arg in {int, float, bool, str}), str)
                if scalar_type in {int, "int"}:
                    kwargs[name] = int(raw)
                elif scalar_type in {float, "float"}:
                    kwargs[name] = float(raw)
                elif scalar_type in {bool, "bool"}:
                    kwargs[name] = raw.lower() in {"1", "true", "yes", "on"}
                else:
                    kwargs[name] = raw
                continue
            if parameter.default is not inspect._empty:
                kwargs[name] = parameter.default
                continue
            kwargs[name] = None
        return endpoint(**kwargs)


def asgi_json(data: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status_code)
