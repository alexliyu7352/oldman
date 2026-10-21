# `oldman.web.security.csrf`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

@author:alex

Import with `from oldman.web.security.csrf import <name>`.

## `add_csrf_token`

value · defined in `oldman.web.security.csrf.decorators`

```python
add_csrf_token = method_adaptor(_add_csrf_token)
```

## `csrf_exempt`

function · defined in `oldman.web.security.csrf.decorators`

```python
def csrf_exempt(func)
```

CSRF-exemption decorator.

## `csrf_protect`

value · defined in `oldman.web.security.csrf.decorators`

```python
csrf_protect = method_adaptor(_csrf_protect)
```

## `csrf_token_for`

function · defined in `oldman.web.security.csrf.manager`

```python
def csrf_token_for(request: Any) -> str
```

A page-level token for the installed manager, e.g. the `csrf-token` meta tag; empty without a manager.

## `CsrfExtension`

class · defined in `oldman.web.security.csrf.csrf_extension`

```python
class CsrfExtension(Extension)
```

Jinja2 CSRF Token Extension

Members:

- `def parse(parser)` — Parse the {% csrf_token %} tag.

## `Payload`

class · defined in `oldman.web.security.csrf.manager`

```python
class Payload(MsgspecModel)
```

Members:

- `sid: str`
- `exp: int`
- `url: str`
- `browser: str | None = None`

## `StatelessCSRFManager`

class · defined in `oldman.web.security.csrf.manager`

```python
class StatelessCSRFManager
```

Stateless CSRF token manager.

Constructor:

```python
StatelessCSRFManager(app: WebApp | None=None, secret_key: str | None=None, ttl: int | None=None, anonymous_id: str='anonymous', session_name: str='session', check_referer: bool | None=None, check_url: bool | None=None, enforce: bool | None=None, cookie_name: str | None=None)
```

Members:

- `def init_app(app: WebApp, secret_key: str | None=None)` — Initialize the application.
- `def generate_token(request: Request) -> str` — Generate a CSRF token.
- `def get_token_from_request(request: Request) -> str | None` — Extract a CSRF token from the request.
- `def register_enforcement(app: WebApp) -> None` — Validate every unsafe-method request, except handlers marked csrf_exempt.
- `def validate_token(request: Request, token: str) -> tuple[bool, str]` — Validate a CSRF token.
- `async def before_server_start(app)`
