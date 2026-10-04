import fcntl
import logging
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

from boxen.api.oauth import OAUTH_OPERATION_IDS, register_oauth_routes
from boxen.platform.application import Application
from boxen.platform.config import Settings
from boxen.platform.contracts import api_contract, resolve, strict_json, validate_payload
from boxen.shared.errors import DomainError
from boxen.shared.values import new_id
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; font-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(self), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def problem(request, error):
    request_id = getattr(request.state, "request_id", new_id())
    data = {
        "type": "urn:boxen:problem:" + error.code,
        "title": error.detail,
        "status": error.status,
        "detail": error.detail,
        "instance": request.url.path,
        "code": error.code,
        "request_id": request_id,
    }
    if error.errors:
        data["errors"] = error.errors
    return JSONResponse(
        data,
        error.status,
        headers={
            **SECURITY_HEADERS,
            "Cache-Control": "no-store",
            "X-Request-ID": request_id,
            **error.headers,
        },
        media_type="application/problem+json",
    )


def create_app(settings: Settings | None = None, vision=None) -> FastAPI:
    settings = settings or Settings.load()
    services = Application(settings, vision)

    @asynccontextmanager
    async def lifespan(_app):
        with (settings.data_dir / "db/runtime.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            yield
        services.database.close()

    app = FastAPI(title="Boxen", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.services = services
    app.openapi = api_contract  # type: ignore[method-assign]

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        request.state.request_id = new_id()
        content_length = request.headers.get("content-length")
        limit = (
            settings.max_upload_bytes + 1024 * 1024
            if request.headers.get("content-type", "").startswith("multipart/")
            else 1024 * 1024
        )
        try:
            if request.headers.get("host") != urlsplit(settings.origin).netloc:
                raise DomainError("request.host_invalid", "This host is not configured for Boxen.", 400)
            if content_length and (not content_length.isdigit() or int(content_length) > limit):
                raise DomainError("request.too_large", "The request exceeds the supported size.", 413)
            response = await call_next(request)
        except DomainError as error:
            return problem(request, error)
        except Exception as error:
            logging.getLogger("boxen").error(
                "request_failed type=%s request_id=%s", type(error).__name__, request.state.request_id
            )
            return problem(
                request,
                DomainError(
                    "system.internal",
                    "The operation could not complete. Try again or contact the owner.",
                    500,
                ),
            )
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        response.headers["X-Request-ID"] = request.state.request_id
        if "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return problem(request, error)

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return problem(
            request,
            DomainError("request.invalid", "The request or route is not supported.", error.status_code),
        )

    @app.exception_handler(OperationalError)
    async def database_error(request, _error):
        return problem(
            request,
            DomainError(
                "database.unavailable",
                "The local database is temporarily unavailable. Try again shortly.",
                503,
                {"Retry-After": "5"},
            ),
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, _error):
        return problem(
            request,
            DomainError(
                "resource.conflict",
                "The operation conflicts with the current data. Reload and try again.",
                409,
            ),
        )

    def endpoint_factory(operation, common_parameters, method):
        async def endpoint(request: Request):
            operation_id = operation["operationId"]
            headers = dict(request.headers)
            token = request.cookies.get("boxen_session")
            write = method not in {"get", "head"} or operation_id == "renderBoxLabel"
            actor = await run_in_threadpool(
                services.preflight,
                operation_id,
                token,
                headers,
                request.state.request_id,
                method not in {"get", "head"},
            )
            params = dict(request.path_params)
            for original in [*common_parameters, *operation.get("parameters", [])]:
                parameter = resolve(original)
                schema, name = parameter["schema"], parameter["name"]
                location = "headers" if parameter["in"] == "header" else parameter["in"]
                prefix = "/" + location + "/" + name.replace("~", "~0").replace("/", "~1")
                source = (
                    params
                    if parameter["in"] == "path"
                    else request.query_params
                    if parameter["in"] == "query"
                    else request.headers
                )
                value = source.get(name)
                if value is None:
                    if "default" in schema:
                        value = schema["default"]
                    elif parameter.get("required"):
                        fields = [
                            {"path": prefix, "code": "value.required", "message": "This field is required."}
                        ]
                        if name == "If-Match":
                            raise DomainError(
                                "resource.precondition_required",
                                "Reload the record before saving.",
                                428,
                                errors=fields,
                            )
                        raise DomainError(
                            "request.parameter_required", f"The {name} parameter is required.", errors=fields
                        )
                    else:
                        continue
                try:
                    if schema.get("type") == "integer":
                        if isinstance(value, str) and not value.isdigit():
                            raise ValueError
                        value = int(value)
                    if schema.get("type") == "boolean" and isinstance(value, str):
                        if value not in {"true", "false"}:
                            raise ValueError
                        value = value == "true"
                except ValueError:
                    raise DomainError(
                        "request.parameter_invalid",
                        f"The {name} parameter is invalid.",
                        errors=[
                            {
                                "path": prefix,
                                "code": "value.invalid",
                                "message": "Use a whole number."
                                if schema.get("type") == "integer"
                                else "Use true or false.",
                            }
                        ],
                    ) from None
                validate_payload(value, schema, prefix=prefix)
                if parameter["in"] != "header":
                    params[name] = value
            body: Any = {}
            prepared, upload_path = None, None
            try:
                content = operation.get("requestBody", {}).get("content", {})
                if "multipart/form-data" in content:
                    actor.authorize("editor")
                    original_receive = request._receive
                    received = 0

                    async def bounded_receive():
                        nonlocal received
                        message = await original_receive()
                        received += len(message.get("body", b""))
                        if received > settings.max_upload_bytes + 1024 * 1024:
                            raise DomainError("request.too_large", "The upload request is too large.", 413)
                        return message

                    request._receive = bounded_receive
                    async with request.form(max_files=1, max_fields=1, max_part_size=1024 * 1024) as form:
                        if set(form) - {"file", "caption"} or not isinstance(form.get("file"), UploadFile):
                            raise DomainError("image.invalid_upload", "Choose exactly one photo to upload.")
                        upload = form["file"]
                        assert isinstance(upload, UploadFile)
                        caption = form.get("caption", "")
                        validate_payload({"caption": caption}, {"$ref": "#/components/schemas/ImagePatch"})
                        body = {"caption": caption, "filename": upload.filename or "photo"}
                        upload_path = await run_in_threadpool(services.media.stage, upload.file)
                    prepared = await run_in_threadpool(services.media.prepare, upload_path)
                elif "application/json" in content:
                    if request.headers.get("content-type", "").split(";")[0] != "application/json":
                        raise DomainError("request.media_type", "Use application/json for this request.", 415)
                    raw = bytearray()
                    async for chunk in request.stream():
                        raw.extend(chunk)
                        if len(raw) > 1024 * 1024:
                            raise DomainError("request.too_large", "The JSON request is too large.", 413)
                    body = strict_json(bytes(raw))
                    validate_payload(body, content["application/json"]["schema"])
                result = await run_in_threadpool(
                    services.execute,
                    operation_id,
                    params,
                    body,
                    headers,
                    token,
                    request.client.host if request.client else "local",
                    request.state.request_id,
                    write,
                    prepared,
                )
            finally:
                if upload_path:
                    await run_in_threadpool(services.media.clear_staging, upload_path)
            response: Response
            if result.file:
                response = FileResponse(result.file, media_type=result.media_type, headers=result.headers)
            elif isinstance(result.body, bytes):
                response = Response(
                    result.body, result.status, headers=result.headers, media_type=result.media_type
                )
            elif result.status in {204, 304}:
                response = Response(status_code=result.status, headers=result.headers)
            else:
                response = JSONResponse(result.body, result.status, headers=result.headers)
            if result.cookie is not None:
                response.set_cookie(
                    "boxen_session",
                    result.cookie,
                    secure=settings.origin.startswith("https://"),
                    httponly=True,
                    samesite="strict",
                    path="/",
                    max_age=7 * 86400 if result.cookie else 0,
                )
            return response

        return endpoint

    register_oauth_routes(app, services)

    for path, item in api_contract()["paths"].items():
        for method, operation in item.items():
            if method in {"get", "post", "put", "patch", "delete"}:
                if operation["operationId"] in OAUTH_OPERATION_IDS:
                    continue
                app.add_api_route(
                    "/api/v1" + path,
                    endpoint_factory(operation, item.get("parameters", []), method),
                    methods=[method.upper()],
                    operation_id=operation["operationId"],
                )

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str, request: Request):
        if path.startswith("api/"):
            return problem(request, DomainError("resource.not_found", "API route not found.", 404))
        return services.frontend(path)

    return app
