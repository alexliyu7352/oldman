# `oldman.web.template`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Template integration.

Import with `from oldman.web.template import <name>`.

## `build_template_loader`

function · defined in `oldman.web.template`

```python
def build_template_loader(project_dir: str | Path | None=None) -> ChoiceLoader
```

Build loader with project templates taking priority over package templates.

## `default_template_environment`

function · defined in `oldman.web.template`

```python
def default_template_environment() -> Environment
```

Create async component template environment for tests and no-app rendering.

## `get_template_environment`

function · defined in `oldman.web.template`

```python
def get_template_environment(owner: Any=None) -> Environment
```

Return a template environment usable by server-rendered components.

## `I18nExtension`

class · defined in `oldman.web.template.i18n_extension`

```python
class I18nExtension(Extension)
```

Render language-aware URL metadata through the configured Web service.

Members:

- `def parse(parser: Any) -> nodes.Node` — Parse an alternate-URL or language-switcher tag.

## `install_template_loaders`

function · defined in `oldman.web.template`

```python
def install_template_loaders(environment: Environment, project_dir: str | Path | None=None) -> Environment
```

Install Oldman project/package template lookup on an existing environment.

## `register_component_filters`

function · defined in `oldman.web.template`

```python
def register_component_filters(environment: Environment) -> None
```

Register globals and filters required by component templates.

## `render_component_template`

function · defined in `oldman.web.template`

```python
async def render_component_template(owner: Any, template_name: str, context: dict[str, Any]) -> Markup
```

Render component template asynchronously when supported.

## `render_component_template_sync`

function · defined in `oldman.web.template`

```python
def render_component_template_sync(owner: Any, template_name: str, context: dict[str, Any]) -> Markup
```

Render component template synchronously.

## `render_fragment`

function · defined in `oldman.web.template`

```python
async def render_fragment(request: Any, template_name: str, **context: Any) -> Markup
```

Render one HTML fragment (a modal body, a result panel) through the app's installed environment.

## `render_template`

re-export · defined in `sanic_ext`

```python
from sanic_ext import render
```

Re-exported unchanged from `sanic_ext`; see that library's documentation.

## `sync_template_environment`

function · defined in `oldman.web.template`

```python
def sync_template_environment() -> Environment
```

Create sync component template environment.

## `template_globals`

function · defined in `oldman.web.template_globals`

```python
def template_globals(environment: Environment) -> MutableMapping[str, Any]
```

``environment.globals``, typed as the mapping of anything it is.
