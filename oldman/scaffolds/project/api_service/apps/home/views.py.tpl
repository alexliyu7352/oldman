"""A health check, and one endpoint for each way a program signs in to this API.

Neither needs a database or a session: the API key and the HTTP Basic account are in
data/{{ service_name }}_settings.yaml (web.auth), generated when the project was created.
"""

from __future__ import annotations

from oldman.version import __VERSION__
from oldman.web import Request, json_response, router
from oldman.web.auth import authenticated_by


@router.get("/", name="home")
async def home(request: Request):
    """Open to everyone; a load balancer or monitor can use it as the health check."""
    del request
    return json_response({"service": "{{ service_name }}", "framework": __VERSION__, "status": "ok"})


@router.get("/api/caller", name="api_caller")
@authenticated_by("api_key")
async def api_caller(request: Request):
    """For programs with an API key, sent in the X-API-Key header; the key's name in web.auth.api_keys is the caller."""
    return json_response({"method": "api_key", "caller": request.ctx.auth.caller})


@router.get("/api/ops", name="api_ops")
@authenticated_by("http_basic")
async def api_ops(request: Request):
    """For tools that speak HTTP Basic (curl, monitoring); the account name in web.auth.http_basic.accounts is the caller."""
    return json_response({"method": "http_basic", "caller": request.ctx.auth.caller})
