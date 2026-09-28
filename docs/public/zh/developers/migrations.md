# 项目数据库迁移

Oldman 统一读取项目配置、加载模型、管理各 App 的迁移目录，再调用 Alembic。生成物仍是可阅读的 Python revision。框架不要求用户手写 alembic.ini、env.py、异步 engine 接线或 version_locations；也不在服务启动时自动修改数据库。

## 命令与范围

在含 pyproject.toml、services/、data/ 的应用项目根运行：

```sh
./run.sh db makemigrations
./run.sh db migrate
./run.sh db status
./run.sh db history
```

| 命令 | 作用 |
| --- | --- |
| `makemigrations` | 对比当前模型与实际数据库，交互选择 App/改名/删除意图，生成一个候选 revision |
| `migrate` | 显示待执行分支，选择全部或某个 App，连同依赖执行 |
| `status` | 只读数据库 owner、内部表状态、每个 App 当前版本/head/待执行项 |
| `history` | 查看迁移源码历史，不连接数据库，但仍需有效项目配置和可加载模型 |
| `downgrade` | 交互选择 App 和目标 revision/base，确认后执行反向操作，可能删除数据 |
| `retire` | 交互移除一个 App 的迁移管理记录，保留实际表，不等于卸载业务代码 |

这些是项目命令，不是 `web db`。目标 App 和危险意图通过真实终端交互选择，不提供 --app、--empty、--rename-table、--yes 或独立 merge 命令。需要问题回答时，管道或非 TTY 会报错；不能把关闭交互安全检查当作部署参数。没有待执行项时正常报告，不强制产生文件或 DDL。

数据库已经初始化、没有恢复或接管等特殊决策时，非交互 migrate 默认执行全部待迁移分支，可用于部署；交互终端则提供范围选择。这不意味着首次使用或状态恢复也能无人确认地执行。

## 项目由哪些服务组成

迁移入口读取 `services/*.py` 中识别出的真实服务及对应 `data/<文件名>_settings.yaml`，不导入或启动这些服务。每个真实服务的默认 YAML 必须存在；测试用其他文件不加入这个集合。

只读取与结构相关的 apps、database.url、app_settings.auth.user_model，不绑定完整运行时 Settings，不初始化 Session、SSE、Redis 或 Web。模型/App 元数据自身的导入仍须遵守加载合同，不能靠 import 启动外部资源。

所有非空 database.url 必须**字符串完全相同**。没有数据库的服务不提供 URL，但其注册 App 仍属于项目 App 并集。这里不解析两个 URL 是否最终指向同一个数据库，也不支持一个项目迁移多个数据库。

`[tool.oldman].migration_apps` 可补充迁移仍需读取、但暂不被服务启用的 App 包；它不是替代真实 Auth 配置的入口。平常只维护服务 apps 即可，不为每个 App 再建立第二份清单。

App 顺序不代表数据库依赖顺序。生成器使用真实表外键分析结构依赖；执行器使用标准 down_revision 和 depends_on 图，不按 YAML 先后猜测执行次序。

## 唯一的数据库维护项目

脚手架在 pyproject.toml 中生成稳定的 `[tool.oldman].project_id` UUID，须随源码提交。一个数据库只有一个迁移维护项目：首次执行迁移时写入 owner，其他 project_id 的项目不能接管其迁移。

API 与 Web 拆成两个代码工程、共用同一数据库时，应选择一个工程完整维护表结构；另一个工程正常访问数据库，但不能独立运行迁移来管理“自己的那几张表”。不要复制 owner UUID 绕过限制，也不要仅修改项目名试图转移所有权。

内部记录使用三张表：

| 表 | 保存内容 |
| --- | --- |
| oldman_migration_owner | 负责维护结构的项目 UUID 和名称 |
| oldman_alembic_version | 标准 Alembic 当前 revision 状态 |
| oldman_schema_registry | 表归属、是否受管及归属变化所在 revision |

这些名称由框架保留，不声明为业务模型，也不要通过 fixture 管理。

## 生成、检查、执行是分开的

1. 修改已注册 App 的模型。
2. 确保数据库已执行现有源码中的全部 migration heads，再运行 makemigrations。全新项目且无任何 revision 时可生成第一份；源码已有迁移而数据库尚未初始化时先 migrate。
3. 多个 App 有变化时交互选择一个；一次只写入该 App 的迁移。按依赖逐项生成和执行，再处理后续 App。
4. 阅读生成文件，检查 upgrade 和 downgrade、约束、默认值及现存数据影响。
5. 单独执行 migrate；在生产部署只执行已提交的迁移，不现场重新生成模型差异。

App 的默认目录是 `<package>/migrations/`，可通过 AppConfig.migrations_module 使用其他相对模块；revision 直接放在该包中，没有每 App 一份 env.py 或额外 versions 层。每 App 有独立分支，初始 revision 的 branch_labels 使用 App label，后续 down_revision 指向本分支前驱。

新增跨 App 外键时会加入对方已应用 head 的 depends_on。目标 App 尚无迁移、未执行到 head 或出现多个 head 时先处理目标 App，不能把缺少依赖当作调整 apps 顺序即可解决。

同一 App 因开发分支产生多个 head，makemigrations 会先询问是否生成标准 merge revision；它只写文件。migrate 不替用户生成 merge，安装第三方包时应选择作者已合并 heads 的版本。

没有结构变化时可交互选择生成空 revision，用于自己编写操作。不要求额外 --empty。框架不自动生成数据转换逻辑，手写数据操作需自行审阅及验证回滚；不要在 migration 中依赖不断变化的业务 ORM 类定义。

迁移写入只允许当前工程源码范围内且可写的 App。安装在 site-packages 或工程外的包只能读取、执行随包迁移；维护第三方 App 时进入其源码工程，不强制写依赖包目录。

## 改名、删除和外部表

整表改名：先只改表名、保持结构，makemigrations 对照旧受管表与新表后询问改名意图；确认后生成 RenameTable 操作并更新归属记录，**不是 DROP 后重建**。改名与复杂结构变化分开处理，无法辨认时不要用“确认删除”蒙混通过。

字段改名：先修改模型字段声明，再运行同一个 makemigrations。一个新增/删除对会询问是否改名；多个候选则让用户选择对应关系。确认改名生成 ALTER/rename，而不是丢弃旧列数据。类型、默认值和约束变化仍须检查生成结果，尤其是现有值不能转换的情况。

真正删除受管表或字段时，需要输入完整表名或 `表名.字段名` 确认；退出、空输入或不匹配不会生成已确认的删除。仅生成文件不删除数据，执行 migrate 才改变数据库。不要把这一步当成可恢复业务数据的回收站。

数据库可以包含其他系统的表：

- 没有当前模型，也没有框架受管记录的表：当作外部表忽略，不自动删除。
- 需要 ORM 访问但不由 Oldman 管结构：模型设置 `Meta.managed = False`；访问权限仍由业务与数据库账号决定。
- 曾由 Oldman 管理，模型改为 managed=False：生成并执行归属释放迁移，保留实体表；不能直接删除模型并假定历史记录一起消失。
- 当前受管模型对应的表已经存在、但未登记：询问 keep external/adopt/cancel。保留外部时先改模型 Meta；选择接管会生成专用 adoption revision。

adoption revision 在空数据库可创建表，在表已存在且与当前模型一致时，经确认跳过 CREATE，只登记归属。表结构不匹配会拒绝，不能假称已同步。其生成的 upgrade/downgrade 带一致性校验，**不要直接编辑这份接管文件的函数体**；额外操作另建普通 revision。

当前受管表不支持显式 SQL schema（Table.schema 必须为 None）；不要把 schema 名与数据库连接 URL、App label 或 Python 包名混为一谈。

## User 扩展的迁移

所有启用 Auth 的服务从 app_settings.auth.user_model 选择同一个具体类；未填写使用默认 User。仅在 migration_apps 中出现 Auth、没有任何真实服务启用 Auth 的配置不成立。

`oldman_user` 的表及核心结构归 Auth；选中的自定义 User 所在 App 管理扩展列、索引和约束。自定义类继承 AbstractUser，不能覆盖框架核心结构。基础迁移和扩展迁移各自随所属 App 保存，扩展外键仍使用 `oldman_user.id`。

新项目先在默认 User 配置下执行 Auth 基础迁移，再注册自定义 User App、切换 user_model，并为扩展部分生成迁移。已有项目在修改模型前先执行现有 heads。不能先把没有初始 revision 的自定义扩展加入全部服务，再假定 migrate 会忽略它只执行 Auth：执行入口会检查所有受管 App 的初始迁移是否齐全。

不要为此建第二张用户表、自动切换数据库表名或复制默认 User 的迁移到业务 App。

## 降级、退出管理与状态恢复

downgrade 展示目标和影响，检查其他已应用 App 是否依赖将被撤销的 revision，再要求确认。它执行 revision 的 downgrade，不保证恢复已被删除的历史数据。降级后的模型若仍是新版本，下次生成可能重新提出升级；按提示切回相应模型版本，这是项目维护者的责任。

retire 保留表，只移除选定 App 的迁移状态/归属；有已应用依赖时可能被阻止。完成后按输出提示，从相关服务配置或 migration_apps 移除该 App。不能先删迁移文件再执行 retire，否则执行器可能无法解析当前数据库版本。

内部状态表全无时，migrate 会显示数据库表数和源码 revision 数，再询问首次使用还是状态丢失；只有部分内部表缺失时进入恢复流程。恢复不是重建业务数据库：

1. 需要当前受管表存在，且当前模型结构与实际表匹配。
2. 展示将恢复的表归属、源码 heads 及保留外部表；未受管模型会询问历史上始终外部还是曾经释放。
3. 用户输入项目名称及 `recover migration state` 明确确认。
4. 只重建框架内部状态并 stamp 到源码 heads，不执行业务 migration DDL。

恢复无法证明手写的数据操作或空 migration 曾经执行。结构不匹配时先由维护者对齐结构或使用可靠备份，再重试；不要选择“首次使用”掩盖误删状态，也不要伪造版本行。

执行 DDL 的原子性取决于数据库。不是所有数据库都能整份 revision 事务回滚；失败后保留原始错误，可能需要检查已执行的部分 SQL。正式变更前备份、审阅并在对应数据库验证，不能用一次 SQLite 示例代替 MySQL/PostgreSQL 的部署验收。
