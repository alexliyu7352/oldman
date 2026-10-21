# File storage and model file fields

Storage holds file contents; the database stores only logical names, such as `examples/assets/...` in the demo. Do not store local absolute paths or a deployment-specific domain in file fields. Storage does not share a transaction with the database and is not a browser Form component.

This chapter uses ExampleAsset in the EPG demo. Follow [Run the EPG dashboard demo](../users/getting-started.md) to prepare configuration, the database, accounts, and static assets, then open `/examples/storage/upload`, `/examples/storage/lifecycle`, and `/examples/storage/api`. These pages create, replace, and delete real test files. Operate only on your own demo data; see [the file tutorial](../users/data-and-files.md) for step-by-step instructions.

## Configuration, objects, and initialization

storages belongs at the service YAML's top level, outside web. An excerpt from the actual [data/web_settings.example.yaml](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/data/web_settings.example.yaml):

```yaml
storages:
  default:
    backend: oldman.storage.backends.filesystem.FileSystemStorage
    options:
      location: media
```

`oldman.storage` exposes Storage, FileSystemStorage, InMemoryStorage, StorageRegistry, storages, default_storage, media_storage, memory_storage, StoredFile, FileInfo, and file_column.

storages is the current process's named-storage Registry. The demo gets a cached instance with `storages.using("default")`. default must exist; memory is reserved for process-local storage and must not be overridden in YAML. Here, media resolves relative to the demo root. Configure and construct other aliases as needed. Initialization does not read or write files in advance.

WebApplication/SimpleApplication initialization already calls storages.init_app; business code need not repeat initialization per request. **Calling bootstrap_service alone does not initialize the Storage Registry**. Ordinary IDE/Python scripts must explicitly call `storages.init_app()` once before using. It uses the already-loaded global Settings rather than providing a second configuration-selection entry point.

default_storage and media_storage currently both refer to the default alias. media_storage does not automatically resolve web.media.storage. For other aliases, use storages.using rather than inferring configuration relationships from object names.

FileSystemStorage(location, alias=None, chunk_size=262144) resolves relative locations against the project root. Reads and writes are chunked. Saving writes a temporary file before publishing the final name. Without overwrite, a conflicting name is replaced with another available name; always use save's return value. InMemoryStorage has the same interface, but its data exists only in this process, has no capacity limit, and disappears on restart. It is unsuitable for persistent storage shared by multiple workers.

## Minimal reads and writes

Below is the demo's complete `run_storage_api_demo()` from [apps/examples/services.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/services.py). That file imports storages from `oldman.storage` and defines `STORAGE_API_PREFIX = "examples/storage-api"`. This is a read/write demonstration invoked by the button on `/examples/storage/api`, rather than a general-purpose production save helper:

```python
async def run_storage_api_demo() -> dict[str, object]:
    """Exercise the public Storage API under one fixed Demo-owned prefix."""
    storage = storages.using("default")
    requested_name = f"{STORAGE_API_PREFIX}/sample.txt"
    await storage.delete(requested_name)
    saved_names: list[str] = []
    try:
        saved_name = await storage.save(requested_name, b"first Storage API demo value")
        saved_names.append(saved_name)
        collision_name = await storage.save(
            requested_name, b"collision Storage API demo value"
        )
        saved_names.append(collision_name)
        overwritten_name = await storage.save(
            requested_name, b"overwritten by the Storage API demo", overwrite=True
        )
        exists_before_delete = await storage.exists(saved_name)
        info = await storage.stat(saved_name)
        async with await storage.open(saved_name) as stored:
            content = (await stored.read()).decode("utf-8")
        await storage.delete(saved_name)
        await storage.delete(collision_name)
        exists_after_delete = await storage.exists(saved_name)
        return {
            "collision_name": collision_name,
            "content": content,
            "exists_after_delete": exists_after_delete,
            "exists_before_delete": exists_before_delete,
            "info": info,
            "overwritten_name": overwritten_name,
            "saved_name": saved_name,
        }
    finally:
        for name in saved_names:
            await storage.delete(name)
```

The returned name may differ from the requested name. The code records the actual name and cleans up files it created in finally. The fixed prefix and initial sample.txt deletion are conventions of this demo. Do not copy them unchanged for user attachments or run multiple demonstrations concurrently with the same prefix. This function neither writes to the database nor declares model-file references.

The HTTP endpoint is in [views/storage.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/storage.py). `example_storage_api_run()` requires CSRF and sign-in checks, calls the service function, renders `_api_result.html`, and updates the result panel through ReplaceHtmlAction. Do not treat the returned Python dict as a response already sent to the browser.

| Interface | Behavior |
| --- | --- |
| `await save(name, content, overwrite=False) -> str` | content is bytes or AsyncIterable[bytes]; returns the actual name; does not overwrite by default |
| `await open(name) -> StoredFile` | Returns an asynchronous file handle; the consumer must close it |
| `await exists(name) -> bool` | Reports whether the file exists |
| `await stat(name) -> FileInfo` | Returns name, size, and timezone-aware modified_at |
| `await delete(name)` | Deletes the file; a missing file is not an error |
| `await get_available_name(name) -> str` | Returns an available candidate without reserving it; save's return value remains authoritative |

StoredFile supports `await read(size=-1)`, `async for chunk in stored`, `await close()`, and async with. Consume large files in chunks rather than unconditionally reading everything. Asynchronous content passed to Storage must also yield bytes chunks. An ordinary synchronous file object is not StorageContent.

Names must be nonempty relative POSIX paths. Absolute paths, backslashes, dot/parent segments, repeated slashes, control characters, and trailing slashes are rejected. Storage validation does not replace business checks on file types, uploader permissions, or publicly downloadable content.

Errors include InvalidStorageName, StorageFileNotFound, StorageAliasNotConfigured, StorageConfigurationError, and StorageBackendError, all under StorageError. Backend system exceptions are wrapped in StorageBackendError with operation/name/alias, retaining the cause through exception chaining. Cancellation propagates. Catch only errors the business operation can actually handle; do not interpret every failure as "file not found."

## Model declarations and Forms

The ExampleAsset class in the demo's [apps/examples/models.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/models.py) contains the following file columns. Mapped comes from sqlalchemy.orm and file_column from oldman.storage. This excerpt includes only the columns; the full model also has a primary key, name, project relationship, and timestamps:

```python
    document_path: Mapped[str] = file_column(upload_to="examples/assets", storage="default")
    preview_path: Mapped[str | None] = file_column(upload_to="examples/previews", storage="default", nullable=True)
```

file_column accepts upload_to, storage="default", max_length=255, nullable=False, and other ordinary mapped_column parameters. It always creates a String column and stores file configuration in info. It is not a custom BLOB or database JSON type.

upload_to can be a directory string or a synchronous `(instance, filename) -> str` function. The framework strips directories from the browser-supplied filename before passing it to the function. Return a complete logical name, which Storage still validates. Do not perform I/O in this function. New instances do not yet have an auto-incremented primary key, so do not depend on a newly generated id for naming. Each column holds one file; use a related model for multiple files.

The corresponding [ExampleAssetForm](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/forms.py) explicitly declares the following fields to limit file types and sizes. UploadField, FileSize, and FileExtension come from `oldman.web.components.forms`; `_` is gettext_lazy. This class excerpt excludes its name field and Meta:

```python
    document_path = UploadField(
        _("Document"),
        validators=[FileSize(1024 * 1024), FileExtension(("txt", "pdf"))],
        render_kw={"class": "hidden", "data-om-upload-input": True, "accept": ".txt,.pdf"},
    )
    preview_path = UploadField(
        _("Preview image"),
        validators=[FileSize(512 * 1024), FileExtension(("png", "jpg", "jpeg", "webp"))],
        render_kw={"class": "hidden", "data-om-upload-input": True, "accept": "image/png,image/jpeg,image/webp"},
    )
```

Unless explicitly declared, ModelForm converts file columns to UploadField automatically. The field binds Sanic File objects from request.files and renders with multipart enctype. It does not interpret the old string from an edited record as a new upload. A non-nullable file column requires an upload initially; editing a record with an existing file permits no upload and retains the old name. This rule depends on the model column and UploadField. Explicit field declarations for size/extension validation or render_kw do not disable it, so business code need not implement validate() itself.

[_asset_form.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/storage/_asset_form.html) places the actual upload control inside an ordinary Form, including messages, field errors, CSRF, and submission state. The hidden input above works with that template's upload enhancement. Copying a hidden input alone does not create a complete upload UI.

An UploadField on an ordinary `Form` (rather than `ModelForm`) only returns the upload object. It does not save it automatically and has no model column to determine requiredness, so implement that rule yourself. FileSize(max_bytes) and FileExtension(("pdf", "txt")) provide validation. An extension does not prove content authenticity, and no virus scan runs automatically. Do not apply DataRequired to every edit request and thereby reject requests that retain the existing file.

Saving must follow successful form.validate. The demo's complete creation endpoint is in [the file tutorial](../users/data-and-files.md#3-complete-save-entry-point). Below is the complete edit endpoint from the same views/storage.py, showing where instance comes from:

```python
@router.post("/examples/storage/assets/<asset_id:int>/update", name="example_asset_update")
@csrf_protect()
@login_required()
async def example_asset_update(request: Request, asset_id: int):
    """Replace only files submitted by the edit Form and keep missing uploads."""
    async with db_manager.get_session() as session:
        asset = await get_object_or_404(session, ExampleAsset, asset_id, message="Example asset was not found")
        form = ExampleAssetForm.from_request(request, instance=asset, session=session)
        if not await form.validate():
            return json_response(form.to_api_response().to_dict())
        await form.save(commit=True, session=session)
    return form_saved_response(_("Asset saved."), url=f"/examples/storage/lifecycle?asset={asset_id}")
```

The route is registered through `router` from `oldman.web`. db_manager comes from oldman.db; CSRF and `login_required` (`oldman.web.auth`) come from the framework. `get_object_or_404()` (`oldman.web.shortcuts`) reads ExampleAsset in the current Session and returns 404 if absent. `form_saved_response()` (`oldman.web.api`) emits Feedback and Redirect actions rather than returning a browser 302 directly. Demo test data is shared by staff; applications requiring user isolation must also restrict the object query by permissions.

The Form writes the new file first, then assigns its actual name to the instance. commit=True only adds/flushes; the outer context commits. commit=False also writes files and does not mean "no external side effects." Even if business code will add/flush later, pass the current Session so new files participate in failure cleanup. Without a Session, this automatic cleanup guarantee does not apply.

## Model file replacement and deletion

When the App Registry loads models, it recognizes file_column and installs the existing lifecycle handling. Do not reimplement old-file deletion in every Form, Admin, or view. The sequence is:

1. Assigning a file attribute only records an in-memory marker; it performs no query or Storage I/O.
2. Before the first actual file change or ORM deletion, the connection used by the write transaction reads all original file columns for that record. Each record is snapshotted once. The Form separately records files actually created during this operation.
3. After the write Session exits and closes, whether committed or rolled back, a new read Session checks final database filenames only for records with candidates.
4. Candidates are compared field by field. A candidate that is still the field's final value is retained; old or newly created files no longer referenced by that field are deleted.
5. A failed final-state query logs an error and skips deletion. Individual deletion failures are also only logged and do not undo a completed database commit.

Thus a committed replacement deletes the old file. Rollback retains the old name still in the database and removes registered new files not referenced by the final record. Actual ORM deletion or setting a field to None cleans up the original file. Reads/writes without file candidates add no queries. File updates/deletions add original-value reads, final reads, and deletion I/O; these operations are not promised to have zero overhead.

In the same demo file, `example_asset_clear_preview()` only sets the nullable preview_path to None; `example_asset_delete()` calls session.delete(asset). Neither repeats Storage deletion calls. `example_asset_rollback()` deliberately raises a local `_ExpectedRollback` after form.save, lets it propagate through the write Session, catches it outside, and checks whether candidate new files were cleaned up. It catches only the expected demonstration exception, without hiding real database or Storage errors.

Multiple file columns are handled per field. One snapshot/final query obtains every file column on the record. **This is not database-wide reference counting across tables and records**: each file field should exclusively own its file. Do not manually copy the same alias/name to other fields or records and expect automatic cleanup to discover every reference. For shared resources, design references around a separate file entity rather than sharing one physical file through multiple file_column fields.

Automatic cleanup is not guaranteed for raw SQL, bulk UPDATE/DELETE, or unloaded child records removed by database cascades. SoftDeleteMixin only changes logical fields; it is not ORM deletion. Business code using these paths must manage files explicitly without bypassing framework Sessions or deleting files that may still be referenced.

This is an immediate check at the end of the current request, not a Redis delayed queue, background cleanup Worker, or database/filesystem transaction. Forced process termination and system failures may still leave orphaned files. The application owns logging and operational cleanup.

## Web downloads and private files

WebApplication publishes one read-only media endpoint according to `web.media.storage` and `web.media.url`, defaulting to default and /media/. An empty url disables the route. Filesystem backends use Sanic static with Range support; other backends stream through StoredFile.

Do not hardcode `/media/...` in templates or views. `oldman.storage.media_url(name)` joins `web.media.url` with the storage name and URL-escapes it. Values already carrying a scheme or `data:` pass through unchanged. It returns an empty string when no media route is configured and does not check whether the file exists.

The default media route is not an authenticated download interface. Keep private attachments in a separate alias/location without publishing it as public media. In your download view, check user and record permissions before reading the stream. Storage has no universal url(), signed_url(), or per-user authorization methods. Do not call nonexistent APIs.

## Adding a backend

Subclass `Storage` and implement five asynchronous methods: `_save(name, content, *, overwrite)`, `_open(name)`, `_delete(name)`, `_exists(name)`, and `_stat(name)`. Constructor arguments correspond to YAML options. Saving returns a logical name, open returns a StoredFile subclass, and stat returns FileInfo. Reuse base-class name/chunk validation and error wrapping instead of creating another public interface.

Set the alias's backend to the full class path so the Registry can instantiate it. The current Registry has no universal close/aclose hook. If a custom backend holds a remote client, the application must explicitly manage its lifecycle. Configuring backend does not automatically close all connections.

<!-- source: zh/developers/storage.md @ db5eb607 -->
