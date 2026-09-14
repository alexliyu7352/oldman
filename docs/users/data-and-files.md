# Demo 的数据导入与文件上传

本章继续使用 EPG Demo，不新增附件表或另写上传接口。Fixture 准备方法见[真实数据教程](tutorial-tasks.md#4-导入可重复的真实数据)，本章直接操作已经存在的 `ExampleAsset`。

先完成数据库迁移、账户、Redis、静态构建和 Web 启动。打开：

- [/examples/storage/upload](http://127.0.0.1:17998/examples/storage/upload)：上传记录。
- [/examples/storage/lifecycle](http://127.0.0.1:17998/examples/storage/lifecycle)：检查、替换、清空和删除文件。
- [/examples/storage/api](http://127.0.0.1:17998/examples/storage/api)：调用公开 Storage API。
- [/examples/forms/upload](http://127.0.0.1:17998/examples/forms/upload)：同一上传能力在 Forms 分类下的入口，不是第二套实现。

这些操作会创建或删除实际文件，只在自己的 Demo 数据和存储目录中测试。

## 1. 模型决定文件存到哪里

[apps/examples/models.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/models.py) 的 ExampleAsset 声明两个文件列，原文节选：

```python
    document_path: Mapped[str] = file_column(upload_to="examples/assets", storage="default")
    preview_path: Mapped[str | None] = file_column(upload_to="examples/previews", storage="default", nullable=True)
```

文件列由 `oldman.storage.file_column` 创建，仍是数据库字符串列。它记录上传目录和 Storage alias，模型保存的是 Storage 返回的逻辑名称，不是本机绝对路径，也不是上传文件内容。

[配置模板](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/data/web_settings.example.yaml) 已包含：

```yaml
storages:
  default:
    backend: oldman.storage.backends.filesystem.FileSystemStorage
    options:
      location: media
```

通过 Demo 根目录的 run.sh 运行时，这里的相对目录就是 Demo 的 media。不要为了本章另外添加 attachments alias。首次已执行迁移时，也不必再生成 ExampleAsset 的初始迁移。

## 2. Form 接收文件，仍使用普通提交链路

[ExampleAssetForm](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/forms.py) 继承 TailwindModelForm：

- `display_name` 必填，最大 160 字符。
- `document_path` 接收 txt/pdf，大小上限 1 MiB；新建必须上传，编辑未上传则保留原文件。
- `preview_path` 接收 png/jpg/jpeg/webp，大小上限 512 KiB；允许不上传。
- `description` 可选。
- Meta.fields 只开放这四项；没有把模型的 project_id 等全部暴露给请求。

这些是 Demo 当前的字段规则，不是所有业务统一的上传限制。浏览器的 accept 属性只帮助选择文件，服务端 FileSize/FileExtension 才执行相应检查；扩展名校验不等于内容安全扫描。

渲染使用 [storage/_asset_form.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/storage/_asset_form.html)。它把上传交互、字段、message、提交状态放在普通 Form 中，由共享 loader 挂载，不另外写一套 fetch 上传逻辑。

## 3. 完整保存入口

下面是 [views/storage.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/storage.py) 已有的完整函数。模块已经导入 db_manager、ExampleAssetForm、CSRF/权限装饰器和响应帮助函数；不是可放到任意文件顶层直接运行的脚本。

```python
@app.post("/examples/storage/assets/create", name="example_asset_create")
@csrf_protect()
@admin_required()
async def example_asset_create(request: Request):
    """Save both uploaded fields through the framework write session."""
    async with db_manager.get_session() as session:
        form = ExampleAssetForm.from_request(request, session=session)
        if not await form.validate():
            return json_response(form.to_api_response().to_dict())
        asset = await form.save(commit=True, session=session)
        asset_id = int(asset.id)
    return _redirect_response(_("Asset uploaded."), f"/examples/storage/lifecycle?asset={asset_id}")
```

表单使用请求中的内存文件对象，ModelForm 按模型元数据调用 Storage，取得最终名称后写入模型。`commit=True` 不意味着 Form 自己结束外层事务；上下文正常退出时才提交。成功响应里的 Feedback/Redirect 由普通 Form 和 Page Runner 执行，跳转后查看这条真实记录的文件状态。

## 4. 不仅检查“上传成功”

生命周期页读取当前记录，再调用 [services.py 的 asset_file_states()](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/services.py) 检查两个文件。函数原文：

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
            "url": f"/media/{quote(path, safe='/')}" if exists else None,
        }
    return states
```

该模块从 `oldman.storage` 导入 storages，从 urllib.parse 导入 quote，并使用当前 App 的 ExampleAsset。路径、exists 和 stat 来自实际存储，不是根据“上传请求返回成功”猜测文件存在。

Demo 的 /media URL 用于展示自己的测试文件，不是带对象授权的私有下载接口。真实业务若处理保密附件，需要另行实现下载权限；不能直接复制公开媒体地址当成授权方案。

## 5. 按顺序测试生命周期

1. 新建只填名称、不上传 Document，应显示字段错误，不新增记录。
2. 上传合法小文件和可选预览，保存后进入该记录的生命周期页；检查两个逻辑名和 exists。
3. 仅修改名称，不选新文件，两个文件应保留。
4. 只替换预览，文档应保留；提交完成后检查新预览存在，旧预览不再被当前记录引用。
5. “清空预览”是 Demo 的显式业务操作：把 nullable 字段设为 None，不是 UploadField 自动提供的删除勾选框。
6. 使用页内的回滚示例上传替代预览。它在真实 form.save 后故意中止事务，核对旧记录及旧文件保留、无引用新文件得到清理，而不是只看提示文字。
7. 删除自己创建的记录，核对两个字段对应的无引用文件均得到处理。
8. 上传超限或不支持扩展名的文件，保存应失败；浏览器限制和后端限制应分别检查。

框架在事务结束后核对文件引用，再处理可删除候选。不能在数据库提交前先删旧文件，也不能在 Demo 表单中再加一套相同的清理。原始 SQL、批量操作、并发与独占文件约束见[文件生命周期参考](../developers/storage.md#模型文件的替换与删除)；不要把这个示例解释成跨文件系统和数据库的原子事务。

## 6. 直接使用 Storage API

Storage API 页的按钮调用 `run_storage_api_demo()`，在 Demo 固定前缀下实际验证：

保存 → 同名保存产生另一个名称 → 显式覆盖 → exists/stat/open/read → 删除 → 再检查 exists。

函数拥有这些演示文件，并在 finally 中清理。它不是扫描整个 media 目录，也不是生产文件回收任务。页面中的返回名称和读取内容来自实际调用，不是固定的“调用成功”占位文案。

Fixture 导出只包含数据库字段，文件列仍只是逻辑名；不会复制文件。将包含文件列的 fixture 导入其他环境前，需要准备对应存储内容并理解替换可能触发清理。详见 [Fixture 参考](../developers/fixtures.md)。
