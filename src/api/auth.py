"""Session validation against the Done Deal company-service.

This service owns no users and no session store. Every request carries a Done
Deal session id, and company-service's internal `token/validate` endpoint is
the single authority on two separate questions:

1. Does this session exist and belong to a live user? (its `UserProfileFilter`)
2. Is that user's role allowed to call *this* endpoint? (`user_auth`, keyed by
   the `apiEndPoint` we send)

So the request we make carries the caller's session id in the header and the
endpoint *they* were trying to reach in the body — not the validate endpoint's
own path. We take the verdict verbatim: 401 stays 401, 403 stays 403. Nothing
here decides authorization locally.

We send the matched route *template*, not the literal URL, so `user_auth` holds
one row per endpoint instead of one per company id. It always carries
`API_PREFIX`, whatever path actually reached uvicorn — see `auth_endpoint_for`.

`clientIp` in the upstream response is company-service's view of the caller —
which is us, not the browser. We overwrite it with our own view of the peer, as
ga-integration does, so downstream logging sees the real client.

Settings come from `src/config.py` under `auth`, overridable with
--auth-enabled, --auth-base-url, --auth-validate-path, --auth-timeout-seconds,
--auth-cache-ttl-seconds and --auth-trust-proxy-headers.
"""

import logging
import threading
import time
from typing import Any, Optional, Tuple

import requests
from fastapi import Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, ValidationError

from . import API_PREFIX
from ..config import DEFAULT_VALIDATE_PATH, AuthSettings, ConfigError, get_config
from ..logging_config import profile_id_ctx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_REFUSAL_DETAIL = "Not authorised for this endpoint"
DEFAULT_CACHE_TTL_SECONDS = 30.0
CACHE_MAX_ENTRIES = 10_000

# Endpoints that must answer without a session. Keyed by (method, route
# template) so a path parameter can never accidentally widen an exemption.
#
# - /health is hit by load balancer probes, which carry no token.
# - POST /tracked-companies is Done Deal's backend pushing companies to us
#   service-to-service; there is no user session behind it.
EXEMPT_ROUTES = frozenset(
    {
        ("GET", "/health"),
        ("POST", f"{API_PREFIX}/tracked-companies"),
    }
)

# Swagger and the schema it renders from. These are Starlette routes rather
# than APIRoutes so the app-level dependency does not reach them anyway; the
# prefixes are here so that stays true if that ever changes.
EXEMPT_PATH_PREFIXES = ("/docs", "/redoc", "/openapi.json")


class UserSession(BaseModel):
    """The authenticated caller, as company-service describes them.

    `extra="allow"` on purpose: company-service may add fields to the payload,
    and dropping them silently would be worse than carrying them through.
    """

    session_id: str = Field(alias="sessionId")
    profile_id: Optional[str] = Field(default=None, alias="profileId")
    email: Optional[str] = None
    user_type: Optional[int] = Field(default=None, alias="userType")
    user_id: Optional[int] = Field(default=None, alias="userId")
    client_ip: Optional[str] = Field(default=None, alias="clientIp")
    device: Optional[str] = None
    biz_permission: Optional[Any] = Field(default=None, alias="bizPermission")
    temp_user_id: Optional[Any] = Field(default=None, alias="tempUserId")

    model_config = {"populate_by_name": True, "extra": "allow"}


class AuthConfig(BaseModel):
    base_url: str
    validate_path: str = DEFAULT_VALIDATE_PATH
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS
    trust_proxy_headers: bool = False

    @property
    def validate_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/{self.validate_path.lstrip('/')}"

    @classmethod
    def from_settings(cls, settings: Optional[AuthSettings] = None) -> "AuthConfig":
        settings = settings if settings is not None else get_config().auth
        base_url = (settings.service_base_url or "").strip()
        if not base_url:
            raise ConfigError(
                "The auth service base URL is not set. Every API route validates "
                "its session against company-service; pass --auth-base-url, or "
                "--auth-enabled false for local development."
            )
        return cls(
            base_url=base_url,
            validate_path=(settings.validate_path or DEFAULT_VALIDATE_PATH).strip(),
            timeout_seconds=settings.timeout_seconds,
            cache_ttl_seconds=settings.cache_ttl_seconds,
            trust_proxy_headers=settings.trust_proxy_headers,
        )


def auth_enabled() -> bool:
    return get_config().auth.enabled


class _TTLCache:
    """Successful verdicts only, keyed by (session id, endpoint).

    The key has to include the endpoint because the verdict is per-endpoint:
    the same session may pass on one route and be refused on another.

    Rejections are deliberately not cached — a permission granted in Done Deal
    should take effect on the caller's next request, and 401s are rare enough
    in normal traffic that caching them buys nothing. The cost is that a
    *revoked* session keeps working until its cached entry expires, which is
    the trade the TTL is there to bound.
    """

    def __init__(self, ttl_seconds: float, max_entries: int = CACHE_MAX_ENTRIES):
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._entries: dict[Tuple[str, str], Tuple[float, UserSession]] = {}

    @property
    def enabled(self) -> bool:
        return self._ttl > 0

    def get(self, key: Tuple[str, str]) -> Optional[UserSession]:
        if not self.enabled:
            return None
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, session = entry
            if expires_at <= time.monotonic():
                del self._entries[key]
                return None
            return session

    def set(self, key: Tuple[str, str], session: UserSession) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        with self._lock:
            if len(self._entries) >= self._max_entries:
                # Cheap upkeep: drop what has expired, and if that frees
                # nothing, drop everything rather than grow without bound.
                self._entries = {k: v for k, v in self._entries.items() if v[0] > now}
                if len(self._entries) >= self._max_entries:
                    self._entries.clear()
            self._entries[key] = (now + self._ttl, session)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class AuthClient:
    """Blocking client for the validate endpoint, with a short-lived cache.

    Held on `app.state` rather than as a module global so the connection pool
    is closed with the app and tests can substitute their own.
    """

    def __init__(self, config: AuthConfig, session: Optional[requests.Session] = None):
        self.config = config
        self._http = session or requests.Session()
        self._cache = _TTLCache(config.cache_ttl_seconds)

    def validate(self, session_id: str, api_endpoint: str) -> UserSession:
        """Resolve a session id for one endpoint, or raise the caller's error.

        Raises HTTPException with company-service's own verdict (401/403), 503
        when it cannot be reached, or 502 when it answers something we cannot
        make sense of.
        """
        key = (session_id, api_endpoint)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        logger.info(
            "Validating session %s...%s against %s for endpoint %s",
            session_id[:4], session_id[-4:], self.config.validate_url, api_endpoint,
        )
        try:
            response = self._http.post(
                self.config.validate_url,
                json={"apiEndPoint": api_endpoint},
                headers={
                    # The raw session id, no scheme prefix — company-service
                    # compares the header against the stored id verbatim.
                    "Authorization": session_id,
                    "Content-Type": "application/json",
                },
                timeout=self.config.timeout_seconds,
            )
        except requests.RequestException as exc:
            # Unreachable auth is our outage to report, not the caller's fault.
            logger.error("Auth service unreachable at %s: %s", self.config.validate_url, exc)
            raise HTTPException(
                status_code=503, detail="Authentication service is unavailable"
            ) from exc

        logger.info(
            "Auth service responded HTTP %s for endpoint %s: %s",
            response.status_code, api_endpoint, response.text[:500],
        )
        user_session = self._parse(response, api_endpoint)
        self._cache.set(key, user_session)
        return user_session

    def _parse(self, response: requests.Response, api_endpoint: str) -> UserSession:
        if response.status_code in (401, 403):
            raise HTTPException(
                status_code=response.status_code,
                detail=self._message(response),
            )
        if response.status_code >= 500:
            logger.error(
                "Auth service returned %s for %s", response.status_code, api_endpoint
            )
            raise HTTPException(status_code=503, detail="Authentication service is unavailable")

        try:
            body = response.json()
        except ValueError as exc:
            logger.error("Auth service returned a non-JSON body (HTTP %s)", response.status_code)
            raise HTTPException(
                status_code=502, detail="Invalid response from authentication service"
            ) from exc

        # The envelope carries its own status as a string, and it does not
        # always agree with the HTTP status — an auth failure can arrive as
        # HTTP 200 with {"status": "401"}. The envelope wins.
        status = _as_int(body.get("status"), default=response.status_code)
        if status in (401, 403):
            raise HTTPException(status_code=status, detail=_detail_from(body))
        if status != 200 or response.status_code != 200:
            logger.error(
                "Auth service returned status=%s (HTTP %s) for %s",
                body.get("status"),
                response.status_code,
                api_endpoint,
            )
            raise HTTPException(
                status_code=502, detail="Invalid response from authentication service"
            )

        data = body.get("data")
        if not isinstance(data, dict):
            logger.error("Auth service returned no session data for %s", api_endpoint)
            raise HTTPException(
                status_code=502, detail="Invalid response from authentication service"
            )
        try:
            return UserSession.model_validate(data)
        except ValidationError as exc:
            logger.error("Auth service session payload did not parse: %s", exc)
            raise HTTPException(
                status_code=502, detail="Invalid response from authentication service"
            ) from exc

    @staticmethod
    def _message(response: requests.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return DEFAULT_REFUSAL_DETAIL
        return _detail_from(body)

    def close(self) -> None:
        self._cache.clear()
        self._http.close()


def _detail_from(body: Any) -> str:
    """The most specific refusal message company-service gave us.

    Its envelope carries a generic `message` ("Failure") and puts the useful
    one inside `data`:

        {"status": "401", "message": "Failure",
         "data": {"code": "unauthenticated", "message": "User not authenticated"}}

    Passing "Failure" to the caller tells them nothing, so the nested message
    wins where there is one.
    """
    if not isinstance(body, dict):
        return DEFAULT_REFUSAL_DETAIL
    data = body.get("data")
    if isinstance(data, dict) and data.get("message"):
        return str(data["message"])
    return str(body.get("message") or DEFAULT_REFUSAL_DETAIL)


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def extract_session_id(request: Request) -> Optional[str]:
    """The session id from the Authorization header, taken verbatim.

    The header carries a bare Done Deal session id and nothing else. A
    `Bearer ` prefix is no longer recognised: it would travel upstream as part
    of the id and company-service would refuse it, which is the intended
    signal that the caller is on the old contract.
    """
    header = request.headers.get("Authorization") or request.headers.get("authorization")
    if not header:
        return None
    return header.strip() or None


def api_endpoint_for(request: Request) -> str:
    """The route template this request matched, e.g.
    `/api/news/deals/{deal_id}`.

    Falls back to the literal path only if routing left no route on the scope,
    which should not happen for a matched request.
    """
    route = request.scope.get("route")
    return getattr(route, "path", None) or request.url.path


def auth_endpoint_for(request: Request) -> str:
    """The endpoint as company-service knows it, always under `API_PREFIX`.

    `user_auth` is keyed by the path the client called through the gateway. If
    a rewrite strips `/api/news` before the request reaches us, the matched
    template is bare (`/deals`) and matches no row upstream — a 401 that has
    nothing to do with the caller's permissions. So the prefix is asserted here
    rather than assumed from the incoming path.

    Only the value sent upstream is normalised: `is_exempt` keeps matching the
    raw template, because `GET /health` is not under the prefix.
    """
    endpoint = api_endpoint_for(request)
    if endpoint == API_PREFIX or endpoint.startswith(f"{API_PREFIX}/"):
        return endpoint
    return f"{API_PREFIX}/{endpoint.lstrip('/')}"


def client_ip_for(request: Request, trust_proxy_headers: bool) -> Optional[str]:
    if trust_proxy_headers:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # Left-most entry is the original client; the rest are proxies.
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def is_exempt(request: Request) -> bool:
    path = request.url.path
    if path.startswith(EXEMPT_PATH_PREFIXES):
        return True
    return (request.method.upper(), api_endpoint_for(request)) in EXEMPT_ROUTES


# Declared only so the scheme shows up in OpenAPI and Swagger grows an
# Authorize button. An apiKey scheme rather than HTTPBearer because Swagger
# prepends `Bearer ` to whatever is typed into a bearer box, which would now
# be sent as part of the session id. `auto_error=False` because the header is
# read by `extract_session_id`; this never rejects anything itself.
_session_scheme = APIKeyHeader(
    name="Authorization",
    auto_error=False,
    scheme_name="DoneDealSession",
    description="Done Deal session id, sent raw with no scheme prefix.",
)


async def require_session(
    request: Request,
    _credentials: Optional[str] = Depends(_session_scheme),
) -> Optional[UserSession]:
    """Validate the caller's session before the route runs.

    Wired as an app-level dependency in `app.py` so a newly added router is
    protected by default — an endpoint becomes public only by being named in
    `EXEMPT_ROUTES`, never by omission.

    The validated session is left on `request.state.user_session`; routes that
    want it typed can depend on `get_user_session`.
    """
    request.state.user_session = None
    if is_exempt(request) or not auth_enabled():
        return None

    session_id = extract_session_id(request)
    if not session_id:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    client: AuthClient = request.app.state.auth_client
    api_endpoint = auth_endpoint_for(request)
    # The call is blocking, so it goes to the threadpool rather than stalling
    # the event loop for every concurrent request.
    user_session = await run_in_threadpool(client.validate, session_id, api_endpoint)

    # company-service saw our IP, not the caller's. Replace it on a copy so the
    # cached entry stays valid for the next caller of the same session.
    user_session = user_session.model_copy(
        update={"client_ip": client_ip_for(request, client.config.trust_proxy_headers)}
    )

    request.state.user_session = user_session
    # Set on the request's context, so log records emitted by this request —
    # including from sync route handlers running in the threadpool — carry the
    # profile id.
    profile_id_ctx.set(user_session.profile_id or "-")
    return user_session


def get_user_session(request: Request) -> UserSession:
    """The validated caller, for routes that need to know who is asking.

    A 401 here means the route is exempt from auth but asked for a session
    anyway — a wiring mistake, not something a caller can cause.
    """
    user_session = getattr(request.state, "user_session", None)
    if user_session is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_session
