# JSON 数据导入与导出

fixture 用于示例数据、开发测试数据及明确的小批数据搬运，不是数据库备份、结构迁移、Excel 工具或自动填充业务数据的种子服务。先用 [db migrate](migrations.md) 准备表，再导入 JSON。

## 入口属于服务

下面直接使用 [EPG Demo](../users/tutorial-tasks.md#4-导入可重复的真实数据) 的服务和模型。在 Demo 根目录执行；导出前核对输出路径不会覆盖要保留的文件：

```sh
./run.sh web dumpdata examples.ExampleProject --output /tmp/projects.json
./run.sh web dumpdata examples --output /tmp/examples.json
./run.sh web loaddata /tmp/examples.json
./run.sh web loaddata demo
```

命令由框架提供，不必编写 App commands.py。它们加载当前服务的配置和 App 模型，但不启动监听；只访问本服务注册模型，不是项目全部服务的 App 并集。与项目级 db 命令的范围不同。

选择器为 App label 或精确的 `label.ModelClassName`，不是数据库表名，模型类名区分大小写。没有 --output 时 stdout 是纯 JSON，可以重定向；日志不应混入 fixture。--output 路径父目录必须存在，已有文件会被覆盖，执行前自己核对。

loaddata 先把参数当现有文件路径；不存在且是无后缀的简单名字时，在已安装 App 的 fixtures/<名字>.json 中查找。多个 App 同名会报歧义，需显式路径；传 `demo.json` 不会再自动搜索所有 App。

## 格式

下面是 Demo 的 apps/examples/fixtures/demo.json 第一条记录组成的单记录列表，完整导入优先使用原文件：

```json
[
  {
    "model": "examples.ExampleLogo",
    "pk": 1,
    "fields": {
      "name": "Atlas US",
      "slug": "atlas-us",
      "country_code": "US",
      "svg_path": "/static/examples/logos/atlas.svg",
      "is_available": true
    }
  }
]
```

根必须是数组；每条恰有 model、pk、fields，不能添加其他顶层属性。fields 用模型的映射属性名，不写主键，也不写 relationship 对象。外键使用真实列值，例如 team_id=12，不嵌套整个 team。

规则：

- 只处理已注册、managed=True、单列主键的映射模型。复合主键、独立关联 Table 或未受管模型不通过此工具导出导入。
- 同一文件不能出现重复 model+pk；未知模型、未知字段、错误类型直接报错，不静默忽略。
- 按 model+pk 创建或更新。已存在记录只更新 fields 中提供的字段；缺少字段不会被自动清空。
- 新记录缺少必填字段时由模型默认值或数据库约束决定结果。不要把“缺字段不提前报错”理解成能插入任意不完整数据。
- 没有出现在文件中的已有记录保留，不清空表，不做删除同步。
- 整个文件在一个写事务内执行；中间唯一约束或其他写入错误会回滚该文件的业务修改。

字段类型按 SQLAlchemy 列恢复：字符串、整数、布尔、有限浮点数、日期/时间/日期时间、Decimal、UUID、Enum、JSON。时间使用 ISO 文本，Decimal 和 UUID 用字符串；布尔不是整数，不能以 true 冒充主键 1。不支持 bytes/BLOB、自定义类型的任意猜测转换。真实文件内容不打包在 JSON 中，文件列仅导出逻辑名称。

## 外键、顺序与范围

导出按所选模型的外键依赖排列，同模型按主键排序，输出 UTF-8 JSON。选择单个 App 不会递归导出所有依赖 App 的数据；接收方必须已有被引用记录，或把需要的记录明确放入同一 fixture。

导入先验证文件和外键目标，再排列新增记录的依赖；既可以引用同文件记录，也可以引用数据库中已有记录。缺失引用和无法排序的新增循环关系会报错，不临时关闭外键约束。PostgreSQL 新导入显式整数主键后推进相应序列；SQLite/MySQL 使用数据库自身行为。序列号不是必须连续，回滚也不能保证它回到原值。

导入通过 ORM 写 Session 执行，不调用 ModelForm 清洗、ModelAdmin.save_model 或密码创建命令。密码字段不会自动把明文转成密码哈希；创建账户优先使用 createsuperuser/changepassword。文件列变动可能触发模型文件清理，必须先理解 [Storage 的独占文件约束](storage.md#模型文件的替换与删除)，不能把导入当作无副作用复制字符串。

全部 JSON 和选定导出记录会放入内存；这不是面向巨量数据的流式备份工具。开发者应限定模型范围，并妥善保护包含个人资料、密码哈希或私有路径的导出文件。

## Python 入口

`oldman.db.fixtures` 公开：

- `await dump_data(registry, database_manager, selector) -> str`
- `resolve_fixture_path(registry, value: str | Path) -> Path`
- `await load_data(registry, database_manager, fixture_path: Path) -> int`

registry 来自 `bootstrap_service("web").apps` 或现有服务上下文，不能手造模型清单来绕过服务范围。返回计数是文件记录数，不是“实际新增行数”。需要一次性脚本时，在业务模块导入前 bootstrap，运行完成后关闭自己使用的数据库资源。

可操作的数据准备步骤见 [Demo 数据教程](../users/tutorial-tasks.md)，上传及文件列消费见[数据与文件](../users/data-and-files.md)。
