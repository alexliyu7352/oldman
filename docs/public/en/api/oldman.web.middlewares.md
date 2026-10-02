# `oldman.web.middlewares`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Web middleware entry points.

Import with `from oldman.web.middlewares import <name>`.

## `add_timezone_info`

function · defined in `oldman.web.middlewares.timezone`

```python
async def add_timezone_info(request: Request) -> None
```

Resolve the caller's timezone onto `request.ctx.timezone`.

## `cleanup_i18n`

function · defined in `oldman.web.middlewares.i18n`

```python
async def cleanup_i18n(request: Request, response: Response) -> None
```

Restore the handler context and preserve it only while a stream executes.

## `install_i18n`

function · defined in `oldman.web.middlewares.i18n`

```python
def install_i18n(request: Request) -> None
```

Resolve and bind one request catalog without mutating the Jinja environment.

## `install_timezone`

function · defined in `oldman.web.middlewares.timezone`

```python
def install_timezone(app: Any) -> None
```

Register the timezone middleware on one application.

## Module `oldman.web.middlewares.timezone`

Per-request timezone resolution, installed by the application when it wants it.

Import with `from oldman.web.middlewares.timezone import <name>`.

### `TIMEZONE_COOKIE`

value · defined in `oldman.web.middlewares.timezone`

```python
TIMEZONE_COOKIE = 'timezone'
```

### `TIMEZONE_HEADER`

value · defined in `oldman.web.middlewares.timezone`

```python
TIMEZONE_HEADER = 'X-Timezone'
```
