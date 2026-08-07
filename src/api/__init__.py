"""HTTP API package.

`API_PREFIX` is the single definition of where this service's routes live. It
is imported by `app.py` (to mount the routers) and by `auth.py` (whose
`EXEMPT_ROUTES` are keyed by full route template), so the two can never drift
apart and quietly un-exempt a public endpoint.

Changing it changes the `apiEndPoint` values sent to company-service for
authorization, so the `user_auth` rows there must be updated to match.
"""

API_PREFIX = "/api/v1/news-scrapper"
