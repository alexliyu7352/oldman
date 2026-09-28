# Agent：模型变更、fixture 与文件上传

用于给现有 Oldman 应用增加真实数据、导入示例记录或接入文件字段。不涉及新增迁移引擎、Storage 实现、后台清理 Worker 或完整业务权限系统。

## 最少阅读与文件清单

| 任务 | 必须核对的参考与应用文件 |
| --- | --- |
| 模型与事务 | [数据库](../developers/database.md)；目标 App 的 models.py、服务 apps、实际 database.url |
| 改结构/改名/接管表 | [迁移](../developers/migrations.md)；项目 pyproject.toml、全部真实服务默认 YAML、App migrations |
| 示例数据 | [fixtures](../developers/fixtures.md)；App fixtures/*.json，目标服务注册范围 |
| 文件上传与删除 | [Storage](../developers/storage.md)；storages 配置、模型 file_column、Form、授权视图 |

用户步骤见[数据与文件](../users/data-and-files.md)，直接对照 Demo 的 ExampleAsset 模型、ExampleAssetForm、views/storage.py 的创建/编辑/回滚入口和生命周期页面。该模型有 document_path、preview_path 两个文件列；页面通过 asset_file_states() 实际检查路径、exists 和 stat，不依赖另一个 Attachment 模型或未提供的 Shell 脚本。需要页面交互时再结合 [Dashboard CRUD](dashboard-crud.md)，不复制第二套 Modal/Form。

## 给既有业务增加一个字段

1. 在实际 App 模型中修改 SQLAlchemy 字段；只读需求优先复用现有模型，不重新声明 Table。
2. 查看当前服务默认配置与其他服务的数据库 URL 是否完全相同。不要从测试用 --config 文件推导迁移范围。
3. 在项目根运行 db status/history。数据库未应用现有迁移时先 migrate，再 makemigrations。
4. 交互确认目标 App 与改名/删除意图，检查生成 revision，再执行 migrate。不要发明 --app/--empty/--yes。
5. 检查实际数据和 schema：改名应保留行和值；增加非空字段要处理已有数据。失败不通过自动建表或手工改 version 表绕过。

一个数据库只有一个迁移 owner 项目。发现它属于另一个 project_id 时报告用户，不覆盖 owner，也不复制 UUID。

## Fixture 的接线

放入 apps/<app>/fixtures/<name>.json，model 标识使用 `<label>.<Python类名>`；先确认主键是否与真实数据冲突。运行 `oldman <service> loaddata <name>`，再用 dumpdata/业务查询核对。

fixture 工具已由框架注册，不为此新增命令。导入是创建/更新，不清表；任意字段不是都支持，错误类型、未知字段、缺失外键应失败。文件列仅保存名称，不能借 fixture 生成上传文件或明文密码哈希。

## 文件上传的接线

1. 确定文件公开还是私有。私有文件使用未发布为 web.media 的 alias；Storage 自身不验证用户权限。
2. 模型用 `from oldman.storage import file_column`。每列保存独占文件的逻辑名，不能在多个字段或记录间复制同名来模拟共享。
3. Form 使用现有 TailwindModelForm，Meta.fields 显式列出字段。自动文件列生成 UploadField；大小/扩展名规则用已有 FileSize/FileExtension，不重写上传组件。
4. 视图先权限/CSRF 验证，再 from_request；查出可访问的编辑实例传 instance。`await form.validate()` 成功后，在 `db_manager.get_session()` 中 `await form.save(commit=True)`，并传同一个 Session。
5. 正常退出上下文后再返回成功 JSON/actions 或 HTML。commit=True 不是提前提交，commit=False 也可能已写文件。
6. Registry 和写 Session 已接入文件生命周期。不要在 Form 保存后立刻删除旧文件，也不要新增数据库回调、Redis 延迟队列或全库文件扫描。
7. 页面表单/Modal 内容调用 form.render，复用当前 Page 的 Form loader。只有真正需要业务后续动作才返回 actions；简单上传成功 message 已能显示在 Form 顶部。

独立 Python/Shell：`bootstrap_service(service)` 后若需要存储，再 `storages.init_app()`；Web/SimpleApplication 已初始化，不重复配置。查找实际文件用 `storages.using(alias).open/exists/stat`，不存在全局 file.url API。

## 当前任务的必要验证

- 事务：成功写入可重新查询；中途异常后不保留同一事务的部分记录。
- fixture：主键更新不是重复新增；一个错误记录让整份业务写入失败；跨 App 引用必须可解析。
- 文件：保存两个不同字段；替换一个不删除另一个；成功提交后旧文件删除；回滚后数据库原名及原文件保留；新文件候选按最终状态清理。
- 非文件路径：普通标题更新/只读不应触发文件状态查询。需要核对性能时只观察本场景 SQL，不为了文档新增生产计数器或测试 reset。
- HTTP：缺文件、未授权、缺 CSRF 各有明确失败；浏览器上传实际选择文件并检查 message/字段错误，不只看 status=200。
- 清理：只删除本次临时文件和数据库，不清理用户 media、真实 Demo 或依赖目录。

批量 SQL 和未加载的数据库级联删除不保证自动文件清理；先向用户说明这条实际限制。不要把当前“核对原记录文件名”的机制描述成支持共享文件的全库引用统计。
