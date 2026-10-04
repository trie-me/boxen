"""OIDC browser endpoints, separate from normal SameSite=Strict session APIs."""

from boxen.identity.oauth import OIDC, TRANSACTION_SECONDS
from boxen.platform.contracts import strict_json, validate_payload
from boxen.shared.errors import DomainError
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

OAUTH_OPERATION_IDS = {
    "listAuthProviders",
    "startOIDCSignIn",
    "completeOIDCSignIn",
    "listAuthProviderStatus",
    "listAuthIdentities",
    "linkAuthIdentity",
    "unlinkAuthIdentity",
}
OAUTH_COOKIE = "boxen_oidc"
OAUTH_PATH = "/api/v1/auth/oidc/"


async def json_body(request: Request, schema: dict) -> dict:
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise DomainError("request.media_type", "Use application/json for this request.", 415)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 8192:
            raise DomainError("request.too_large", "The JSON request is too large.", 413)
    body = strict_json(bytes(raw))
    validate_payload(body, schema)
    assert isinstance(body, dict)
    return body


def register_oauth_routes(app: FastAPI, services) -> None:
    oidc = OIDC(services.settings, services.identity, services.database)
    app.state.oauth = oidc
    secure = services.settings.origin.startswith("https://")

    def admin(request: Request, operation: str, *, write: bool = False):
        actor = services.preflight(
            operation,
            request.cookies.get("boxen_session"),
            dict(request.headers),
            request.state.request_id,
            write,
        )
        actor.authorize("owner", recent=write)
        return actor

    @app.get("/api/v1/auth/providers", operation_id="listAuthProviders")
    async def providers():
        return {"items": oidc.public_providers()}

    @app.post("/api/v1/auth/oidc/{provider_id}/start", operation_id="startOIDCSignIn")
    async def start(provider_id: str, request: Request):
        if request.headers.get("origin") != services.settings.origin:
            raise DomainError("auth.origin_invalid", "The request origin was not accepted.", 403)
        await json_body(request, {"type": "object", "additionalProperties": False})
        url, browser = await run_in_threadpool(
            oidc.start, provider_id, request.client.host if request.client else "local"
        )
        response = JSONResponse({"authorization_url": url})
        response.set_cookie(
            OAUTH_COOKIE,
            browser,
            secure=secure,
            httponly=True,
            samesite="lax",
            path=OAUTH_PATH,
            max_age=TRANSACTION_SECONDS,
        )
        return response

    @app.get("/api/v1/auth/oidc/{provider_id}/callback", operation_id="completeOIDCSignIn")
    async def callback(provider_id: str, request: Request):
        params = request.query_params
        rejected = "error" in params or any(
            len(params.getlist(key)) > 1 for key in ("state", "code", "iss", "error")
        )
        try:
            token = await run_in_threadpool(
                oidc.complete,
                provider_id,
                params.get("state", ""),
                request.cookies.get(OAUTH_COOKIE, ""),
                params.get("code", ""),
                request.state.request_id,
                response_issuer=params.get("iss"),
                rejected=rejected,
                client=request.client.host if request.client else "local",
            )
            response = RedirectResponse("/", status_code=302)
            response.set_cookie(
                "boxen_session",
                token,
                secure=secure,
                httponly=True,
                samesite="strict",
                path="/",
                max_age=7 * 86400,
            )
        except DomainError:
            response = RedirectResponse("/login?oauth_error=failed", status_code=302)
        response.delete_cookie(OAUTH_COOKIE, secure=secure, httponly=True, samesite="lax", path=OAUTH_PATH)
        return response

    @app.get("/api/v1/auth/provider-status", operation_id="listAuthProviderStatus")
    async def provider_status(request: Request):
        actor = await run_in_threadpool(admin, request, "listAuthProviderStatus")
        return {"items": oidc.provider_status(actor)}

    @app.get("/api/v1/auth/identities", operation_id="listAuthIdentities")
    async def identities(request: Request):
        actor = await run_in_threadpool(admin, request, "listAuthIdentities")
        user_id = request.query_params.get("user_id")
        if user_id is not None:
            validate_payload(user_id, {"type": "string", "format": "uuid"}, prefix="/query/user_id")

        def read():
            with services.database.transaction() as repo:
                return oidc.list_identities(repo, actor, user_id)

        return {"items": await run_in_threadpool(read)}

    @app.post("/api/v1/auth/identities", operation_id="linkAuthIdentity", status_code=201)
    async def link(request: Request):
        await run_in_threadpool(admin, request, "linkAuthIdentity", write=True)
        body = await json_body(
            request,
            {
                "type": "object",
                "required": ["user_id", "provider_id", "subject"],
                "additionalProperties": False,
                "properties": {
                    "user_id": {"type": "string", "format": "uuid"},
                    "provider_id": {"type": "string", "pattern": "^[a-z][a-z0-9_-]{0,39}$"},
                    "subject": {"type": "string", "minLength": 1, "maxLength": 255},
                },
            },
        )

        def write():
            with services.database.transaction(write=True) as repo:
                actor = services.identity.authenticate(
                    repo, request.cookies.get("boxen_session"), request.state.request_id
                )
                return oidc.link(repo, actor, body)

        return JSONResponse(await run_in_threadpool(write), status_code=201)

    @app.delete("/api/v1/auth/identities/{identity_id}", operation_id="unlinkAuthIdentity", status_code=204)
    async def unlink(identity_id: str, request: Request):
        await run_in_threadpool(admin, request, "unlinkAuthIdentity", write=True)
        validate_payload(identity_id, {"type": "string", "format": "uuid"}, prefix="/path/identity_id")

        def write():
            with services.database.transaction(write=True) as repo:
                actor = services.identity.authenticate(
                    repo, request.cookies.get("boxen_session"), request.state.request_id
                )
                oidc.unlink(repo, actor, identity_id)

        await run_in_threadpool(write)
        return Response(status_code=204)
