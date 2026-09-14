# 文件存储与模型文件字段

Storage 保存文件内容，数据库只保存逻辑名称，例如 Demo 的 `examples/assets/...`。不要把本机绝对路径或某次部署的域名写成文件字段。它与数据库不是一个事务，也不是浏览器 Form 组件。

本章使用 EPG Demo 的 ExampleAsset。按[入门步骤](../users/getting-started.md)准备配置、数据库、账户和静态资源后，打开 `/examples/storage/upload`、`/examples/storage/lifecycle`、`/examples/storage/api`。这些页面会创建、替换和删除真实测试文件，只操作自己的 Demo 数据；逐步操作说明见[文件教程](../users/data-and-files.md)。

## 配置、对象与初始化

服务 YAML 顶层使用 storages，不在 web 下。[data/web_settings.example.yaml](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/data/web_settings.example.yaml) 的实际配置节选：

```yaml
storages:
  default:
    backend: oldman.storage.backends.filesystem.FileSystemStorage
    options:
      location: media
```

`oldman.storage` 公开 Storage、FileSystemStorage、InMemoryStorage、StorageRegistry、storages、default_storage、media_storage、memory_storage、StoredFile、FileInfo 和 file_column。

storages 是当前进程的命名存储 Registry，Demo 使用 `storages.using("default")` 取得缓存实例。default 必须存在；memory 是保留的进程内存储名，不在 YAML 中覆盖。这里的 media 相对 Demo 根目录解析，其他 alias 按需配置和构造；初始化不预先读写文件。

WebApplication/SimpleApplication 初始化时已调用 storages.init_app，业务不必每个请求重复初始化。**仅调用 bootstrap_service 不会初始化 Storage Registry**；普通 IDE/Python 脚本需显式调用一次 `storages.init_app()`，之后才能 using。它使用已经加载的全局 Settings，不是第二套配置选择入口。

default_storage 和 media_storage 当前都指向 default alias；media_storage 不是自动跟随 web.media.storage 的解析器。需要其他 alias 就用 storages.using，避免从对象名猜配置关联。

FileSystemStorage(location, alias=None, chunk_size=262144) 的相对 location 按项目根解析。文件分块读写，保存先写临时文件再发布最终名称；不覆盖模式下同名另取名称，必须使用 save 的返回值。InMemoryStorage 使用同样接口，但数据只在本进程、无容量上限、重启丢失，不适合作为多个 worker 共用的持久存储。

## 最小读写

下面是 Demo [apps/examples/services.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/services.py) 的完整 `run_storage_api_demo()`。同文件从 `oldman.storage` 导入 storages，并定义 `STORAGE_API_PREFIX = "examples/storage-api"`。它不是通用的生产保存助手，而是由 `/examples/storage/api` 的按钮调用的读写演示：

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

保存返回的名称可能与请求名称不同；代码记录实际名称，并在 finally 中清理自己创建的文件。固定前缀和先删除 sample.txt 是这个演示的约定，不适合原样用于保存用户附件，也不应同时并发运行多个同名前缀演示。它没有写数据库或声明模型文件引用。

HTTP 入口在 [views/storage.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/storage.py)：`example_storage_api_run()` 受 CSRF 和 staff 权限保护，调用服务函数，再渲染 `_api_result.html`，通过 ReplaceHtmlAction 更新结果面板。不能把返回的 Python dict 直接当作已经发送给浏览器的响应。

| 接口 | 行为 |
| --- | --- |
| `await save(name, content, overwrite=False) -> str` | content 为 bytes 或 AsyncIterable[bytes]；返回实际名称，默认不覆盖 |
| `await open(name) -> StoredFile` | 取得异步文件句柄，使用者负责关闭 |
| `await exists(name) -> bool` | 是否存在 |
| `await stat(name) -> FileInfo` | name、size、带时区的 modified_at |
| `await delete(name)` | 删除；不存在时不报错 |
| `await get_available_name(name) -> str` | 获取候选可用名，不预留该名称；最终仍以 save 返回为准 |

StoredFile 支持 `await read(size=-1)`、`async for chunk in stored`、`await close()` 和 async with。大文件应逐块消费，不无条件 read 全部内容；传入 Storage 的异步内容也必须逐块为 bytes，普通同步文件对象并不是 StorageContent。

名称必须是非空相对 POSIX 路径；拒绝绝对路径、反斜杠、点/父目录段、重复斜杠、控制字符和末尾斜杠。存储验证不代替业务对文件类型、上传者权限或公开下载内容的判断。

错误分为 InvalidStorageName、StorageFileNotFound、StorageAliasNotConfigured、StorageConfigurationError、StorageBackendError，均属于 StorageError。后端系统异常会包装为带 operation/name/alias 的 StorageBackendError，原因为异常链保留；取消继续传播。捕获业务确实能处理的异常，不把所有失败当“文件不存在”。

## 模型声明与 Form

Demo [apps/examples/models.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/models.py) 的 ExampleAsset 类中有下面两个文件列。Mapped 来自 sqlalchemy.orm，file_column 来自 oldman.storage；这里只摘出列声明，完整模型还含主键、名称、项目关系和时间戳：

```python
    document_path: Mapped[str] = file_column(upload_to="examples/assets", storage="default")
    preview_path: Mapped[str | None] = file_column(upload_to="examples/previews", storage="default", nullable=True)
```

file_column 的参数是 upload_to、storage="default"、max_length=255、nullable=False，以及普通 mapped_column 的其他参数。它始终生成 String 列，在 info 中保存文件配置，不是自定义 BLOB 或数据库 JSON 类型。

upload_to 可以是目录字符串，也可以是同步函数 `(instance, filename) -> str`。框架先移除浏览器文件名携带的目录，再传给函数；返回完整逻辑名称，最终仍由 Storage 验证。函数不要执行 I/O；新增实例还没有自增主键，不要依赖刚生成的 id 命名。一个列保存一个文件，多文件列表用关联模型。

对应 [ExampleAssetForm](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/forms.py) 显式声明了下面两个字段，以限制文件类型和大小。UploadField、FileSize、FileExtension 来自 `oldman.web.components.forms`，`_` 是 gettext_lazy。这是类内节选，不包括该类的名称字段、Meta 和新增必填校验：

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

未显式声明时，ModelForm 自动将文件列转成 UploadField。字段绑定 request.files 中 Sanic 的 File 对象，渲染时使用 multipart enctype；不会把编辑记录中的旧字符串当成本次上传。非空自动文件字段首次必须上传，编辑已有文件时允许不上传并保留原名。Demo 显式覆盖后，自己的 validate() 另外处理了“新建必须有 Document”，不能只抄上面的两个字段而漏掉此规则。

实际上传控件由 [_asset_form.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/storage/_asset_form.html) 放进普通 Form，包含 message、字段错误、CSRF 和提交状态。上面的 hidden input 与该模板中的上传增强配合使用，不是孤立复制一个隐藏 input 就能完成上传 UI。

普通 OldmanForm 使用 UploadField 时只得到上传对象，不自动保存。可使用 FileSize(max_bytes)、FileExtension(("pdf", "txt")) 校验；扩展名不等于内容真实性，也没有自动病毒扫描。显式覆盖自动文件字段时，应自行定义新增/编辑必填规则；不要对所有编辑请求直接 DataRequired 而误拒绝“保留原文件”。

保存必须先通过 form.validate。Demo 的完整创建入口已在[文件教程](../users/data-and-files.md#3-完整保存入口)列出；这里给出同一 views/storage.py 中完整编辑入口，展示 instance 的来源：

```python
@app.post("/examples/storage/assets/<asset_id:int>/update", name="example_asset_update")
@csrf_protect()
@admin_required()
async def example_asset_update(request: Request, asset_id: int):
    """Replace only files submitted by the edit Form and keep missing uploads."""
    async with db_manager.get_session() as session:
        asset = await _asset_or_404(session, asset_id)
        form = ExampleAssetForm.from_request(request, instance=asset, session=session)
        if not await form.validate():
            return json_response(form.to_api_response().to_dict())
        await form.save(commit=True, session=session)
    return _redirect_response(_("Asset saved."), f"/examples/storage/lifecycle?asset={asset_id}")
```

app 是该模块 get_app() 取得的 Sanic 实例；db_manager 来自 oldman.db，CSRF 来自框架，admin_required 是 Demo 的 staff 保护。`_asset_or_404()` 在当前 Session 中读取 ExampleAsset，不存在则 404；`_redirect_response()` 输出 Feedback 和 Redirect 动作，并不直接返回浏览器 302。Demo 是 staff 共用测试数据，需要用户隔离的应用还要在对象查询中增加权限范围。

Form 先写新文件，再把实际名称写到实例；commit=True 只是 add/flush，外层上下文才提交。commit=False 同样会写文件，不等于“没有外部副作用”。即使后续由业务自己 add/flush，也应传入当前 Session，使新文件进入失败清理；不提供 Session 就没有这项自动清理保证。

## 模型文件的替换与删除

App Registry 加载模型时，识别 file_column 并安装已有生命周期；不要在每个 Form、Admin 或视图中再写一套删除旧文件的逻辑。流程是：

1. 文件属性赋值只登记内存标记，不执行查询或 Storage I/O。
2. 第一次真实文件变更或 ORM 删除前，从写事务使用的连接读取该记录原来的全部文件列；同一记录只取一次快照。Form 另登记本次实际新建的文件。
3. 写 Session 退出并关闭之后，无论提交还是回滚，只对有候选的记录开一个新的读 Session，核对数据库中该记录的最终文件名。
4. 逐字段比较：仍是该字段最终值的候选保留，已不再引用的旧文件或本次新文件删除。
5. 最终状态查询失败则记录错误并不删；单文件删除失败也只记日志，不推翻已经完成的数据库提交。

因此提交替换后删除旧文件；回滚时保留仍在数据库中的旧名，并清理已登记但未被最终记录引用的新文件；ORM 真正删除记录或字段置 None 后清理原文件。没有文件候选的读写不会额外查询；有文件更新/删除会增加原值读取和收尾读取、删除 I/O，不承诺这些操作零开销。

Demo 同一文件中的 `example_asset_clear_preview()` 仅把 nullable 的 preview_path 设为 None；`example_asset_delete()` 调用 session.delete(asset)。两者都没有重复调用 Storage 删除文件。`example_asset_rollback()` 则在 form.save 后故意抛出本地 `_ExpectedRollback`，让异常先穿过写 Session，再在外层捕获，并检查候选新文件是否已清理。它只捕获预期演示异常，不掩盖真正的数据库或 Storage 错误。

多个文件列按字段处理，一次快照/最终查询取得同一记录的全部文件列。**这里不是跨表、跨记录的全库引用计数**：每个文件字段应独占自己的文件；不要手工把同一个 alias/name 复制给其他字段或记录后，仍期待自动清理判断所有引用。需要共享资源时用单独的文件实体设计引用关系，关闭“通过多个 file_column 共享同一实际文件”的用法。

原始 SQL、批量 UPDATE/DELETE、数据库级联删除的未加载子记录都不保证自动清理。SoftDeleteMixin 仅改逻辑字段，不等于 ORM 删除。业务使用这些路径时要显式管理文件，不为此绕过框架 Session 或删除仍可能被引用的文件。

这是当前请求结束时的即时核对，不是 Redis 延迟队列、后台清理 Worker 或跨数据库/文件系统事务。进程被强杀、系统故障仍可能留下孤立文件，日志与运维清理由应用负责。

## Web 下载与私有文件

WebApplication 按 `web.media.storage` 和 `web.media.url` 发布一个只读媒体入口，默认 default 和 /media/；空 url 不安装该路由。文件系统后端使用 Sanic static（支持 Range），其他后端用 StoredFile 流式响应。

这个默认媒体路由不是认证下载接口。私有附件使用单独 alias/location，不把它发布为公开 media；在自己的下载视图先验证用户和记录权限，再读取流。Storage 没有统一的 url()、signed_url() 或按用户授权方法，不要调用不存在的 API。

## 增加后端

继承 `Storage`，实现五个异步方法：`_save(name, content, *, overwrite)`、`_open(name)`、`_delete(name)`、`_exists(name)`、`_stat(name)`。构造参数对应 YAML options；保存返回逻辑名，open 返回 StoredFile 子类，stat 返回 FileInfo。复用基类的名称/分块校验和错误包装，不另建一套公共方法。

将完整类路径写入对应 alias 的 backend，Registry 才会创建它。当前 Registry 没有通用的 close/aclose 钩子；自定义后端若持有远程客户端，应由应用明确管理其生命周期，不能假定设置了 backend 就自动关闭所有连接。
