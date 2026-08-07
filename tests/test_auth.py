"""Session validation against company-service.

Two halves, same as the routes: the client that talks to company-service and
decides what each answer means, and the dependency that puts it in front of
every endpoint.
"""
import time
from unittest.mock import MagicMock

import pytest
import requests
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from src.api.auth import (
    AuthClient,
    AuthConfig,
    UserSession,
    extract_session_id,
    get_user_session,
    require_session,
)
from src.config import AppConfig, AuthSettings, reset_config, set_config

VALID_BODY = {
    "status": "200",
    "message": "Success",
    "data": {
        "sessionId": "90062adc6228-f",
        "profileId": "444a4f41-d57b-4008-ae15-be7d4910ddc4",
        "email": "hello@done.deals",
        "userType": 2,
        "userId": 10751,
        "clientIp": "172.31.35.69",
        "device": "MacIntel",
        "bizPermission": None,
        "tempUserId": None,
    },
}


def fake_response(status_code=200, body=VALID_BODY, text=None):
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    if text is None:
        response.json.return_value = body
    else:
        response.json.side_effect = ValueError("not json")
        response.text = text
    return response


def build_auth_client(response=None, ttl=0.0, side_effect=None, trust_proxy_headers=False):
    http = MagicMock(spec=requests.Session)
    if side_effect is not None:
        http.post.side_effect = side_effect
    else:
        http.post.return_value = response if response is not None else fake_response()
    config = AuthConfig(
        base_url="https://qa.done.deals",
        cache_ttl_seconds=ttl,
        trust_proxy_headers=trust_proxy_headers,
    )
    return AuthClient(config, session=http), http


# ---------------------------------------------------------------------------
# What we send
# ---------------------------------------------------------------------------

def test_the_endpoint_being_called_is_sent_not_the_validate_endpoint():
    """`user_auth` is keyed by the caller's target endpoint. Sending validate's
    own path would authorize the wrong thing on every request."""
    client, http = build_auth_client()

    client.validate("sess-1", "/api/v1/news-scrapper/deals/{deal_id}")

    assert http.post.call_args.kwargs["json"] == {"apiEndPoint": "/api/v1/news-scrapper/deals/{deal_id}"}
    assert http.post.call_args.args[0] == (
        "https://qa.done.deals/api/company-service/v1/internal/token/validate"
    )


def test_the_session_id_travels_as_a_bearer_token():
    client, http = build_auth_client()

    client.validate("sess-1", "/api/v1/news-scrapper/deals")

    assert http.post.call_args.kwargs["headers"]["Authorization"] == "Bearer sess-1"


@pytest.mark.parametrize(
    "header, expected",
    [
        ("Bearer 90062adc6228-f", "90062adc6228-f"),
        ("bearer 90062adc6228-f", "90062adc6228-f"),
        # Done Deal's own curl sends the raw id, so both forms must work.
        ("90062adc6228-f", "90062adc6228-f"),
        ("  Bearer  90062adc6228-f  ", "90062adc6228-f"),
        ("", None),
        ("Bearer ", None),
    ],
)
def test_session_id_is_read_with_or_without_the_bearer_prefix(header, expected):
    request = MagicMock(spec=Request)
    request.headers = {"Authorization": header}
    assert extract_session_id(request) == expected


# ---------------------------------------------------------------------------
# What we do with the answer
# ---------------------------------------------------------------------------

def test_a_valid_session_is_parsed_into_its_fields():
    client, _ = build_auth_client()

    session = client.validate("sess-1", "/api/v1/news-scrapper/deals")

    assert session.profile_id == "444a4f41-d57b-4008-ae15-be7d4910ddc4"
    assert session.user_type == 2
    assert session.user_id == 10751
    assert session.email == "hello@done.deals"


def test_unknown_fields_from_company_service_survive():
    """The payload is theirs to extend; dropping a new field silently would
    make it look like they never sent it."""
    body = {**VALID_BODY, "data": {**VALID_BODY["data"], "newThing": "keep me"}}
    client, _ = build_auth_client(fake_response(body=body))

    session = client.validate("sess-1", "/api/v1/news-scrapper/deals")

    assert session.model_dump()["newThing"] == "keep me"


@pytest.mark.parametrize("status", [401, 403])
def test_their_verdict_is_passed_through_unchanged(status):
    client, _ = build_auth_client(
        fake_response(status_code=status, body={"status": str(status), "message": "Nope"})
    )

    with pytest.raises(Exception) as exc:
        client.validate("sess-1", "/api/v1/news-scrapper/deals")

    assert exc.value.status_code == status
    assert exc.value.detail == "Nope"


def test_the_specific_refusal_message_is_surfaced_not_the_generic_one():
    """company-service's envelope says "Failure" and buries the real reason in
    `data.message`. Passing "Failure" on tells the caller nothing."""
    client, _ = build_auth_client(
        fake_response(
            status_code=401,
            body={
                "status": "401",
                "message": "Failure",
                "data": {"code": "unauthenticated", "message": "User not authenticated"},
            },
        )
    )

    with pytest.raises(Exception) as exc:
        client.validate("sess-1", "/api/v1/news-scrapper/deals")

    assert exc.value.detail == "User not authenticated"


def test_a_refusal_with_no_message_at_all_still_says_something_useful():
    client, _ = build_auth_client(fake_response(status_code=403, body={"status": "403"}))

    with pytest.raises(Exception) as exc:
        client.validate("sess-1", "/api/v1/news-scrapper/deals")

    assert exc.value.detail == "Not authorised for this endpoint"


@pytest.mark.parametrize("status", [401, 403])
def test_a_refusal_carried_in_the_envelope_still_refuses(status):
    """An auth failure can arrive as HTTP 200 with {"status": "401"}. Trusting
    the HTTP status alone would let it through as authenticated."""
    client, _ = build_auth_client(
        fake_response(status_code=200, body={"status": str(status), "message": "Nope"})
    )

    with pytest.raises(Exception) as exc:
        client.validate("sess-1", "/api/v1/news-scrapper/deals")

    assert exc.value.status_code == status


def test_an_unreachable_auth_service_is_our_503_not_the_callers_401():
    """A network failure is our outage. Reporting 401 would tell every client
    their perfectly good session had expired."""
    client, _ = build_auth_client(side_effect=requests.ConnectionError("refused"))

    with pytest.raises(Exception) as exc:
        client.validate("sess-1", "/api/v1/news-scrapper/deals")

    assert exc.value.status_code == 503


def test_auth_service_5xx_is_also_a_503():
    client, _ = build_auth_client(fake_response(status_code=502, body={}))

    with pytest.raises(Exception) as exc:
        client.validate("sess-1", "/api/v1/news-scrapper/deals")

    assert exc.value.status_code == 503


@pytest.mark.parametrize(
    "response",
    [
        fake_response(text="<html>gateway</html>"),
        fake_response(body={"status": "200", "message": "Success"}),  # no data
        fake_response(body={"status": "200", "data": {"email": "x@y.z"}}),  # no sessionId
    ],
)
def test_an_answer_we_cannot_read_is_a_502_never_an_authenticated_request(response):
    client, _ = build_auth_client(response)

    with pytest.raises(Exception) as exc:
        client.validate("sess-1", "/api/v1/news-scrapper/deals")

    assert exc.value.status_code == 502


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

def test_a_repeat_call_within_the_ttl_does_not_hit_the_network_again():
    client, http = build_auth_client(ttl=30.0)

    client.validate("sess-1", "/api/v1/news-scrapper/deals")
    client.validate("sess-1", "/api/v1/news-scrapper/deals")

    assert http.post.call_count == 1


def test_the_same_session_on_a_different_endpoint_is_validated_again():
    """The verdict is per-endpoint — a session allowed on one route may be
    refused on another, so the endpoint has to be part of the key."""
    client, http = build_auth_client(ttl=30.0)

    client.validate("sess-1", "/api/v1/news-scrapper/deals")
    client.validate("sess-1", "/api/v1/news-scrapper/articles")

    assert http.post.call_count == 2


def test_a_cached_verdict_expires():
    client, http = build_auth_client(ttl=0.05)

    client.validate("sess-1", "/api/v1/news-scrapper/deals")
    time.sleep(0.06)
    client.validate("sess-1", "/api/v1/news-scrapper/deals")

    assert http.post.call_count == 2


def test_rejections_are_not_cached():
    """A permission granted in Done Deal must take effect on the next request,
    not one TTL later."""
    client, http = build_auth_client(
        fake_response(status_code=403, body={"status": "403"}), ttl=30.0
    )

    for _ in range(2):
        with pytest.raises(Exception):
            client.validate("sess-1", "/api/v1/news-scrapper/deals")

    assert http.post.call_count == 2


# ---------------------------------------------------------------------------
# The dependency, in front of an app
# ---------------------------------------------------------------------------

def build_app(auth_client=None):
    app = FastAPI(dependencies=[Depends(require_session)])
    app.state.auth_client = auth_client or build_auth_client()[0]

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/v1/news-scrapper/tracked-companies")
    def register():
        return {"registered": True}

    @app.get("/api/v1/news-scrapper/deals/{deal_id}")
    def deal(deal_id: str, session=Depends(get_user_session)):
        return {
            "deal_id": deal_id,
            "profile_id": session.profile_id,
            "client_ip": session.client_ip,
        }

    @app.get("/api/v1/news-scrapper/articles")
    def articles():
        """A route that never looks at who is asking — auth still guards it."""
        return {"items": []}

    return app


@pytest.fixture(autouse=True)
def auth_on():
    """Auth on by default, and the installed config reset after every test."""
    set_config(AppConfig(auth=AuthSettings(enabled=True)))
    yield
    reset_config()


def test_a_request_with_no_token_is_401_without_calling_the_auth_service():
    client, http = build_auth_client()

    response = TestClient(build_app(client)).get("/api/v1/news-scrapper/deals/d1")

    assert response.status_code == 401
    assert http.post.call_count == 0


def test_a_valid_session_reaches_the_route():
    response = TestClient(build_app()).get(
        "/api/v1/news-scrapper/deals/d1", headers={"Authorization": "Bearer sess-1"}
    )

    assert response.status_code == 200
    assert response.json()["profile_id"] == "444a4f41-d57b-4008-ae15-be7d4910ddc4"


def test_the_route_template_is_what_gets_authorized_not_the_literal_url():
    """One `user_auth` row per endpoint. Sending the literal path would need a
    row per company id, and unknown ids would start failing authorization."""
    client, http = build_auth_client()

    TestClient(build_app(client)).get(
        "/api/v1/news-scrapper/deals/d1", headers={"Authorization": "Bearer sess-1"}
    )

    assert http.post.call_args.kwargs["json"] == {"apiEndPoint": "/api/v1/news-scrapper/deals/{deal_id}"}


def test_health_answers_without_a_token():
    """Load balancer probes carry no session."""
    client, http = build_auth_client()

    response = TestClient(build_app(client)).get("/health")

    assert response.status_code == 200
    assert http.post.call_count == 0


def test_the_done_deal_push_endpoint_answers_without_a_token():
    """Done Deal's backend registers companies service-to-service; there is no
    user session behind that call."""
    client, http = build_auth_client()

    response = TestClient(build_app(client)).post("/api/v1/news-scrapper/tracked-companies")

    assert response.status_code == 200
    assert http.post.call_count == 0


def test_the_client_ip_is_ours_not_the_one_company_service_saw():
    """company-service sees this service's IP, not the browser's. Passing its
    value through would file every request under this service's address."""
    response = TestClient(build_app()).get(
        "/api/v1/news-scrapper/deals/d1", headers={"Authorization": "Bearer sess-1"}
    )

    assert response.status_code == 200
    # The upstream body says 172.31.35.69; the actual peer here is the TestClient.
    assert UserSession.model_validate(VALID_BODY["data"]).client_ip == "172.31.35.69"
    assert response.json()["client_ip"] == "testclient"


def test_a_cached_session_does_not_leak_the_previous_callers_ip():
    """The cached entry is shared between everyone using that session, so the
    IP has to go onto a copy rather than into the cached model."""
    auth_client, _ = build_auth_client(ttl=30.0, trust_proxy_headers=True)
    test_client = TestClient(build_app(auth_client))

    first = test_client.get(
        "/api/v1/news-scrapper/deals/d1",
        headers={"Authorization": "Bearer sess-1", "X-Forwarded-For": "10.0.0.1"},
    )
    second = test_client.get(
        "/api/v1/news-scrapper/deals/d1",
        headers={"Authorization": "Bearer sess-1", "X-Forwarded-For": "10.0.0.2, 10.9.9.9"},
    )

    assert first.json()["client_ip"] == "10.0.0.1"
    assert second.json()["client_ip"] == "10.0.0.2"


def test_a_forwarded_for_header_is_ignored_unless_proxy_headers_are_trusted():
    """Anyone can send X-Forwarded-For. It is only meaningful when a proxy we
    control is known to be setting it, so the default is to use the real peer."""
    client, _ = build_auth_client()

    response = TestClient(build_app(client)).get(
        "/api/v1/news-scrapper/deals/d1",
        headers={"Authorization": "Bearer sess-1", "X-Forwarded-For": "1.2.3.4"},
    )

    assert response.json()["client_ip"] == "testclient"


def test_every_exempt_route_still_exists_on_the_real_app():
    """An exemption is matched on the exact route template, so renaming a route
    or changing a router prefix turns its exemption into a dead entry — and the
    endpoint starts demanding a token from a caller that has none. Silent
    otherwise, since the stale entry simply never matches."""
    from src.api.app import app
    from src.api.auth import EXEMPT_ROUTES

    registered = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", None) or ()
    }

    assert EXEMPT_ROUTES <= registered, f"stale exemptions: {EXEMPT_ROUTES - registered}"


def test_the_real_app_validates_sessions_on_every_route():
    """The guard is app-level so a new router cannot forget it. If this ever
    fails, some route is being served unauthenticated."""
    from fastapi.routing import APIRoute

    from src.api.app import app

    api_routes = [route for route in app.routes if isinstance(route, APIRoute)]
    assert api_routes

    unguarded = [
        f"{sorted(route.methods)} {route.path}"
        for route in api_routes
        if not any(
            dependency.call is require_session for dependency in route.dependant.dependencies
        )
    ]
    assert not unguarded, f"served without session validation: {unguarded}"


def test_auth_disabled_lets_everything_through():
    """The local-development escape hatch, and the reason it is loud."""
    set_config(AppConfig(auth=AuthSettings(enabled=False)))
    client, http = build_auth_client()

    response = TestClient(build_app(client)).get("/api/v1/news-scrapper/articles")

    assert response.status_code == 200
    assert http.post.call_count == 0


def test_auth_enabled_guards_a_route_that_never_asks_who_is_calling():
    client, http = build_auth_client()
    test_client = TestClient(build_app(client))

    assert test_client.get("/api/v1/news-scrapper/articles").status_code == 401
    assert test_client.get(
        "/api/v1/news-scrapper/articles", headers={"Authorization": "Bearer sess-1"}
    ).status_code == 200
    assert http.post.call_count == 1
