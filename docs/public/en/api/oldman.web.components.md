# `oldman.web.components`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

@author:alex

Import with `from oldman.web.components import <name>`.

## `render_modal`

function · defined in `oldman.web.components.modals`

```python
async def render_modal(request: Any, **options: Any) -> Markup
```

Render one Modal through the request's environment; options are `modal_fragment_context`'s.

## Module `oldman.web.components.data_endpoint`

The data endpoint URL a component's shell points its frontend at.

Import with `from oldman.web.components.data_endpoint import <name>`.

### `DataEndpointMixin`

class · defined in `oldman.web.components.data_endpoint`

```python
class DataEndpointMixin
```

Resolve the route a rendered shell fetches its rows or series from.

Members:

- `request: Any = None`
- `route_name: str = ''`
- `route_path: str = ''`
- `def build_data_url(route_kwargs: dict[str, object]) -> str` — Return the data endpoint URL, falling back to the declared static path.

## Module `oldman.web.components.modals`

Render one dashboard Modal from Python instead of spelling out the template variables.

Import with `from oldman.web.components.modals import <name>`.

### `modal_fragment_context`

function · defined in `oldman.web.components.modals`

```python
def modal_fragment_context(*, modal_id: str, title: Any, body: Markup | str, component: str='modal', close_label: Any=_('Close'), managed: bool=False, footer_close_label: Any=None, dialog_class: str | None=None, hidden: bool=False) -> dict[str, Any]
```

The variables `modal_fragment.html` expects, so callers name arguments instead of keys.

### `MODAL_FRAGMENT_TEMPLATE`

value · defined in `oldman.web.components.modals`

```python
MODAL_FRAGMENT_TEMPLATE = 'oldman/dashboard/components/modal_fragment.html'
```
