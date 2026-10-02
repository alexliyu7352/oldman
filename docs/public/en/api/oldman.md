# `oldman`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

@author:alex

Import with `from oldman import <name>`.

## `bootstrap_service`

function · defined in `oldman.runtime.bootstrap`

```python
def bootstrap_service(service_module: str, *, config_file: str | Path | None=None) -> ServiceBootstrapContext
```

Load one service's YAML, App settings and models without starting it.

## `ServiceBootstrapContext`

class · defined in `oldman.runtime.bootstrap`

```python
class ServiceBootstrapContext
```

Validated settings and model Registry for one selected service process.

Members:

- `service_module: str`
- `config_file: Path`
- `settings: DefaultSettings`
- `apps: AppRegistry`
