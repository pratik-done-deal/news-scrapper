"""HTTP API package.

`API_PREFIX` is the single definition of where this service's routes live. It
is imported by `app.py` (to mount the routers) and by `auth.py` (whose
`EXEMPT_ROUTES` are keyed by full route template), so the two can never drift
apart and quietly un-exempt a public endpoint. Behind the QA gateway these
routes are reached as `https://qa.done.deals/api/news-scrapper/...`, so the
prefix here has to match the path the gateway forwards.

Changing it changes the `apiEndPoint` values sent to company-service for
authorization, so the `user_auth` rows there must be updated to match.
"""

API_PREFIX = "/api/news-scrapper"
