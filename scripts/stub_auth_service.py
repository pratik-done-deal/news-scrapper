"""
A stand-in for company-service's token/validate, for local development.

Lets the API be run and exercised without reaching QA and without a real Done
Deal session — and, unlike `AUTH_ENABLED=false`, it exercises the auth path
rather than skipping it, so 401/403/503 handling is actually under test.

Never run this anywhere real: it hands out a valid session to a hardcoded id.

Usage:
    python scripts/stub_auth_service.py                  # port 9099
    python scripts/stub_auth_service.py --port 9100

Then point the API at it and start the API in another shell:
    AUTH_SERVICE_BASE_URL=http://localhost:9099 python api_server.py

    curl localhost:8000/api/news/deals                  # 401
    curl -H 'Authorization: good-session' \
         localhost:8000/api/news/deals                  # 200
    curl -H 'Authorization: good-session' \
         localhost:8000/api/news/analytics/deals/volume # 403

Behaviour:
    session "good-session"  -> valid, on every endpoint except those in
                               FORBIDDEN_ENDPOINTS, which answer 403
    anything else           -> 401
"""
import argparse

from fastapi import FastAPI, Request

app = FastAPI(title="Stub company-service auth")

VALID_SESSION = "good-session"

# One endpoint refuses, so the "role not allowed" branch can be exercised
# without editing anything on the company-service side.
FORBIDDEN_ENDPOINTS = {"/api/news/analytics/deals/volume"}


@app.post("/api/company-service/v1/internal/token/validate")
async def validate(request: Request):
    body = await request.json()
    endpoint = body.get("apiEndPoint")

    # The raw session id, as company-service reads it — no scheme prefix.
    token = request.headers.get("authorization", "").strip()

    if token != VALID_SESSION:
        return {"status": "401", "message": "Session not found", "data": None}
    if endpoint in FORBIDDEN_ENDPOINTS:
        return {"status": "403", "message": f"Role not allowed on {endpoint}", "data": None}

    return {
        "status": "200",
        "message": "Success",
        "data": {
            "sessionId": token,
            "profileId": "444a4f41-d57b-4008-ae15-be7d4910ddc4",
            "email": "hello@done.deals",
            "userType": 2,
            "userId": 10751,
            # Deliberately not the caller's IP — the API is expected to
            # overwrite this with its own view of the peer.
            "clientIp": "172.31.35.69",
            "device": "MacIntel",
            "bizPermission": None,
            "tempUserId": None,
        },
    }


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=9099)
    args = parser.parse_args()

    print(f"Stub auth on http://localhost:{args.port} — valid session id: {VALID_SESSION!r}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
