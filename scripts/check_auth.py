"""
Check session validation against the Done Deal company-service, live.

Answers the two questions the unit tests cannot, because both live on the
other side of the network:

1. Is our config right — base URL, path, header shape — and does
   company-service accept this session id at all?
2. Does `user_auth` have a row for each of our endpoints? A missing row is not
   a bug in this service, it is a 401/403 that only shows up in production, and
   it is invisible until someone calls that endpoint.

Read-only. It calls the validate endpoint and prints what came back; it never
touches Neo4j, MySQL, or the scrape pipeline, so it runs against QA without a
local stack.

Usage:
    python scripts/check_auth.py --session <sessionId>       # one probe + verdict
    python scripts/check_auth.py --session <id> --all-routes # every endpoint
    python scripts/check_auth.py --session <id> --endpoint /api/v1/news/deals
    python scripts/check_auth.py --session <id> --json       # machine-readable

Configuration comes from `src/config.py` under `auth`; --auth-base-url and
the other flags from --help override it for one run.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException

from src.api.auth import EXEMPT_ROUTES, AuthClient, AuthConfig
from src.config import ConfigError, add_config_arguments, load_config

PROBE_ENDPOINT = "/api/v1/news/deals"

OK = "\033[32m"
BAD = "\033[31m"
WARN = "\033[33m"
DIM = "\033[2m"
OFF = "\033[0m"


def _colour(text: str, colour: str, plain: bool) -> str:
    return text if plain else f"{colour}{text}{OFF}"


def app_routes() -> list[tuple[str, str]]:
    """Every (method, route template) the API serves, exemptions dropped.

    Imported lazily: pulling in the app costs a few seconds of module imports
    and is pointless unless --all-routes was asked for.
    """
    from fastapi.routing import APIRoute

    from src.api.app import app

    routes = {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
        if method not in ("HEAD", "OPTIONS")
    }
    return sorted(routes - EXEMPT_ROUTES, key=lambda pair: (pair[1], pair[0]))


def probe(client: AuthClient, session_id: str, endpoint: str) -> dict:
    """One validate call, flattened into a result row."""
    try:
        session = client.validate(session_id, endpoint)
    except HTTPException as exc:
        return {"endpoint": endpoint, "status": exc.status_code, "detail": str(exc.detail)}
    return {
        "endpoint": endpoint,
        "status": 200,
        "profile_id": session.profile_id,
        "email": session.email,
        "user_type": session.user_type,
        "user_id": session.user_id,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True, help="A live Done Deal session id")
    parser.add_argument("--endpoint", help=f"Validate one endpoint (default {PROBE_ENDPOINT})")
    parser.add_argument("--all-routes", action="store_true", help="Validate every endpoint this API serves")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Machine-readable output")
    add_config_arguments(parser, only=("auth",))
    args = parser.parse_args()

    plain = args.as_json or not sys.stdout.isatty()

    app_config = load_config(args)
    try:
        config = AuthConfig.from_settings(app_config.auth)
    except ConfigError as exc:
        print(f"{exc}\n\nPass --auth-base-url to check without changing the default.", file=sys.stderr)
        return 2

    # No caching: two probes of the same endpoint must both hit the network,
    # or the second tells us nothing.
    config = config.model_copy(update={"cache_ttl_seconds": 0.0})
    client = AuthClient(config)

    if not args.as_json:
        print(f"{_colour('Validating against', DIM, plain)} {config.validate_url}\n")

    endpoints = app_routes() if args.all_routes else [("*", args.endpoint or PROBE_ENDPOINT)]

    results = []
    try:
        for method, endpoint in endpoints:
            result = probe(client, args.session, endpoint)
            result["method"] = method
            results.append(result)

            if args.as_json:
                continue
            if result["status"] == 200:
                mark = _colour("  ok ", OK, plain)
            elif result["status"] in (401, 403):
                mark = _colour(f" {result['status']} ", BAD, plain)
            else:
                mark = _colour(f" {result['status']} ", WARN, plain)
            suffix = "" if result["status"] == 200 else f"  {result.get('detail', '')}"
            label = endpoint if method == "*" else f"{method:6} {endpoint}"
            print(f"{mark} {label}{suffix}")
    finally:
        client.close()

    if args.as_json:
        print(json.dumps(results, indent=2))
        return 0 if all(r["status"] == 200 for r in results) else 1

    allowed = [r for r in results if r["status"] == 200]
    unauthorised = [r for r in results if r["status"] == 401]
    forbidden = [r for r in results if r["status"] == 403]
    broken = [r for r in results if r["status"] not in (200, 401, 403)]

    if allowed:
        first = allowed[0]
        print(
            f"\n{_colour('Session is live', OK, plain)} — "
            f"{first.get('email')} (userId {first.get('user_id')}, "
            f"userType {first.get('user_type')}, profileId {first.get('profile_id')})"
        )
    elif unauthorised:
        # Nothing at all came back authorized, so the likely fault is the
        # session, not the endpoint rows — saying "check user_auth" here would
        # send you after the wrong thing.
        print(
            f"\n{_colour('No endpoint accepted this session', BAD, plain)}. "
            "Most likely the session id is expired or wrong — get a fresh one "
            "before reading anything into the per-endpoint results."
        )

    if forbidden:
        print(
            f"\n{_colour(f'{len(forbidden)} endpoint(s) returned 403', BAD, plain)} — "
            "the session is valid but this user's role is not allowed there. "
            "Either intended, or a missing/too-narrow `user_auth` row on the "
            "company-service side. Every one will 403 in production."
        )
    if unauthorised and allowed:
        print(
            f"\n{_colour(f'{len(unauthorised)} endpoint(s) returned 401', BAD, plain)} "
            "while others passed — company-service has no `user_auth` row that "
            "permits this endpoint at all."
        )
    if broken:
        print(
            f"\n{_colour(f'{len(broken)} endpoint(s) could not be checked', WARN, plain)} — "
            "503 means the auth service was unreachable, 502 means it answered "
            "something we could not read. Neither is an authorization problem."
        )
    healthy = not unauthorised and not forbidden and not broken
    if healthy:
        print(_colour("\nAll checked endpoints authorize this session.", OK, plain))

    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
