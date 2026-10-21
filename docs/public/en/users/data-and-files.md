# Demo data import and file upload

This chapter continues to use EPG Demo without adding an attachment table or writing another upload interface. For the Fixture preparation method, see [Real Data Tutorial](tutorial-tasks.md#4-import-repeatable-real-data). This chapter directly operates the existing `ExampleAsset`.

Complete database migration, accounts, Redis, static build and web launch first. Open:

- [/examples/storage/upload](http://127.0.0.1:17997/examples/storage/upload): Upload records.
- [/examples/storage/lifecycle](http://127.0.0.1:17997/examples/storage/lifecycle): Check, replace, empty and delete files.
- [/examples/storage/api](http://127.0.0.1:17997/examples/storage/api): Call the public Storage API.
- [/examples/forms/upload](http://127.0.0.1:17997/examples/forms/upload): The entrance of the same upload capability under the Forms category, not the second set of implementations.

These operations create or delete actual files and are only tested in your own Demo data and storage directory.

## 1. The model determines where to save the file

The ExampleAsset of [apps/examples/models.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/models.py) declares two file columns, excerpt from the original text:

```python
    document_path: Mapped[str] = file_column(upload_to="examples/assets", storage="default")
    preview_path: Mapped[str | None] = file_column(upload_to="examples/previews", storage="default", nullable=True)
```

The file column is created by `oldman.storage.file_column` and is still a database string column. It records the upload directory and Storage alias. The model saves the logical name returned by Storage, not the absolute path of the local machine, nor the content of the uploaded file.

[Configuration Template](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/data/web_settings.example.yaml) contains:

```yaml
storages:
  default:
    backend: oldman.storage.backends.filesystem.FileSystemStorage
    options:
      location: media
```

When running through run.sh in the Demo root directory, the relative directory here is the Demo media. Do not add additional attachments alias for this chapter. It is also not necessary to generate the initial migration of ExampleAsset when the migration is performed for the first time.

## 2. Form receives files through the ordinary submission flow

[ExampleAssetForm](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/forms.py) inherits TailwindModelForm:

- `display_name` is required, with a maximum of 160 characters.
- `document_path` accepts txt/pdf up to 1 MiB. Creation requires an upload; editing without an upload preserves the existing file.
- `preview_path` accepts png/jpg/jpeg/webp up to 512 KiB; uploading is optional.
- `description` is optional.
- Meta.fields exposes only these four fields, rather than exposing all model fields such as project_id to requests.

These are the current field rules of the Demo and are not uniform upload restrictions for all businesses. The browser's accept attribute only helps select files, and the server's FileSize/FileExtension performs corresponding checks; extension verification is not equal to content security scanning.

Rendering uses [storage/_asset_form.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/storage/_asset_form.html). It puts the upload interaction, fields, messages, and submission status in a normal Form, which is mounted by the shared loader, without writing a separate set of fetch upload logic.

## 3. Complete save entry point

The following is the existing complete function in [views/storage.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/storage.py). The module already imports db_manager, ExampleAssetForm, CSRF/permission decorators, and response helpers; this is not a standalone script that runs at the top of any file.

```python
@router.post("/examples/storage/assets/create", name="example_asset_create")
@csrf_protect()
@login_required()
async def example_asset_create(request: Request):
    """Save both uploaded fields through the framework write session."""
    async with db_manager.get_session() as session:
        form = ExampleAssetForm.from_request(request, session=session)
        if not await form.validate():
            return json_response(form.to_api_response().to_dict())
        asset = await form.save(commit=True, session=session)
        asset_id = int(asset.id)
    return form_saved_response(_("Asset uploaded."), url=f"/examples/storage/lifecycle?asset={asset_id}")
```

The form uses in-memory file objects from the request. ModelForm calls Storage using model metadata, obtains the final name, and writes it to the model. `commit=True` does not mean Form ends the outer transaction itself; commit occurs only on normal context exit. The ordinary Form and Page Runner execute Feedback/Redirect in the success response. After redirecting, inspect this actual record's file state.

## 4. Check more than “upload successful”

The lifecycle page reads the current record, then calls [asset_file_states() in services.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/services.py) to inspect both files. The original function:

```python
async def asset_file_states(asset: ExampleAsset) -> dict[str, dict[str, object]]:
    """Read the real Storage state of both logical file names."""
    storage = storages.using("default")
    states: dict[str, dict[str, object]] = {}
    for field_name in ("document_path", "preview_path"):
        path = getattr(asset, field_name)
        exists = bool(path) and await storage.exists(path)
        info = await storage.stat(path) if exists else None
        states[field_name] = {
            "exists": exists,
            "info": info,
            "path": path,
            "url": media_url(path) if exists else None,
        }
    return states
```

This module imports storages from `oldman.storage`, quote from urllib.parse, and ExampleAsset from the current App. Paths, exists, and stat come from actual storage, rather than assuming file existence because an upload request succeeded.

Demo's /media URL is used to display its own test files, not a private download interface with object authorization. If real business handles confidential attachments, download permissions need to be implemented separately; public media addresses cannot be directly copied as an authorization solution.

## 5. Test the lifecycle in sequence

1. Create with only a name and no Document upload. A field error should appear, without a new record.
2. Upload a valid small file and optional preview. Saving opens that record's lifecycle page; check both logical names and exists.
3. Only modify the name, do not select new files, both files should be retained.
4. Replace only the preview; the document should remain. After commit, verify that the new preview exists and the current record no longer references the old one.
5. “Clear optional preview” is an explicit demo business operation setting the nullable field to None, rather than a delete checkbox automatically provided by UploadField.
6. Upload a replacement preview through the page's rollback example. It deliberately aborts the transaction after an actual form.save. Verify that the old record and file remain and the unreferenced new file is cleaned up; do not check only the message.
7. Delete the record you created and check that the non-referenced files corresponding to the two fields are processed.
8. Saving oversized files or unsupported extensions should fail. Check browser and backend restrictions separately.

The framework checks file references after the transaction and then processes the deletion candidates. You cannot delete old files before committing the database, nor can you add a set of the same cleanup to the Demo form. Raw SQL, batch operations, concurrency, and exclusive file constraints are in [File Lifecycle Reference](../developers/storage.md#模型文件的替换与删除); do not interpret this example as an atomic transaction across the file system and database.

## 6. Use Storage API directly

Storage API page buttons call `run_storage_api_demo()`, actually checking the following under a fixed demo prefix:

Save → Saving under the same name produces another name → Explicit overwrite → exists/stat/open/read → Delete → Check exists again.

The function owns these demonstration files and cleans them up in finally. It neither scans the entire media directory nor acts as a production file cleanup task. Returned names and read contents come from actual calls, rather than fixed “call successful” placeholders.

Fixture exports only include database fields, file columns are still just logical names; files are not copied. Before importing fixtures containing file columns into other environments, you need to prepare the corresponding storage contents and understand that replacement may trigger cleanup. See [Fixture Reference](../developers/fixtures.md) for details.

<!-- source: zh/users/data-and-files.md @ d2d7dd40 -->
