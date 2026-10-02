# `oldman.ops`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Building blocks for server maintenance and deployment tools.

Import with `from oldman.ops import <name>`.

## `edit_marked_block`

function · defined in `oldman.ops.files`

```python
def edit_marked_block(path: str | os.PathLike[str], marker: str, content: str, *, follow_symlinks: bool, comment: str='#') -> bool
```

Put `content` between `{comment} >>> {marker}` and `{comment} <<< {marker}` lines.

## `os_release`

function · defined in `oldman.ops.files`

```python
def os_release(path: str | os.PathLike[str] | None=None) -> dict[str, str]
```

The operating system's identification, such as `ID`, `VERSION_ID` and `PRETTY_NAME`.

## `read_directive`

function · defined in `oldman.ops.files`

```python
def read_directive(path: str | os.PathLike[str], key: str, default: str | None=None, *, separator: str=' ', comment: str='#') -> str | None
```

The value of the first line setting `key` that is not commented out, else `default`.

## `set_directive`

function · defined in `oldman.ops.files`

```python
def set_directive(path: str | os.PathLike[str], key: str, value: str, *, follow_symlinks: bool, separator: str=' ', comment: str='#') -> bool
```

Make `key` read `value` in a `key value` style file such as sshd_config.

## `systemd`

module · defined in `oldman.ops.systemd`

```python
module oldman.ops.systemd
```

systemd units: ask whether one runs, restart or reload it, reload the unit files.

## Module `oldman.ops.systemd`

systemd units: ask whether one runs, restart or reload it, reload the unit files.

Import with `from oldman.ops.systemd import <name>`.

### `daemon_reload`

function · defined in `oldman.ops.systemd`

```python
async def daemon_reload(*, command: Sequence[str]=SYSTEMCTL) -> None
```

Make systemd read changed unit files; raises `subprocess.CalledProcessError` when it fails.

### `is_active`

function · defined in `oldman.ops.systemd`

```python
async def is_active(unit: str, *, command: Sequence[str]=SYSTEMCTL) -> bool
```

Whether `unit` is running (`systemctl is-active --quiet`).

### `reload`

function · defined in `oldman.ops.systemd`

```python
async def reload(unit: str, *, command: Sequence[str]=SYSTEMCTL) -> None
```

Have `unit` reload its configuration; raises `subprocess.CalledProcessError` when it fails.

### `restart`

function · defined in `oldman.ops.systemd`

```python
async def restart(*candidates: str, command: Sequence[str]=SYSTEMCTL) -> str | None
```

Restart the first of `candidates` that is running and return its name; None if none is.

### `SYSTEMCTL`

value · defined in `oldman.ops.systemd`

```python
SYSTEMCTL: tuple[str, ...] = ('systemctl',)
```
