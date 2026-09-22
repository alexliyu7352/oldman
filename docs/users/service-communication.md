# 让正在运行的服务相互通信

本章直接运行独立 EPG Dashboard 的“服务通信”示例。它有两个真实后台接收服务：一个页面可以询问指定服务的项目状态，也可以给两个服务发送事件。数据来自 Demo 数据库，不是前端编造的结果。

先区分三件事：NATS/FastStream 用于后台服务的在线事件和 RPC；Taskiq 用于持久排队的后台任务；SSE 用于服务器向浏览器实时输出。一次 RPC 不会自动变成持久任务，也不会自动显示浏览器通知。

## 1. 准备并启动 Demo

工作目录是独立的 `oldman_epg_dashboard`，不是框架源码目录。完整安装见[快速开始](getting-started.md)，以下是它 README 中与本例有关的实际步骤。

```sh
python3 scripts/bootstrap.py
for service in web task_worker task_scheduler nats_a nats_b; do
  test -e "data/${service}_settings.yaml" || cp "data/${service}_settings.example.yaml" "data/${service}_settings.yaml"
done
```

已有文件不会被覆盖。项目迁移会读取所有服务的配置，所以即使只运行通信页面，也先准备五份 YAML；它们必须指向同一数据库和同一个 Auth User 模型。按自己的环境核对 Redis/NATS 地址，不能拿生产库试验。

Demo 默认 NATS 为 127.0.0.1:4222；任务使用 Redis TASKIQ 的 6379/7，Session 等使用各自 alias。先准备 Redis 和 NATS。已安装 nats-server 时，可在独立终端执行：

```sh
nats-server -js -sd data/nats
```

Core 本身不需要 JetStream，但 Demo 默认也开启 Taskiq，因此这台示例服务器启用 JetStream。不要在已有服务占用的端口再次启动；生产认证/TLS 由部署配置，不照搬回环无认证示例。

首次初始化：

```sh
./run.sh web settings sync
./run.sh task_worker settings sync
./run.sh task_scheduler settings sync
./run.sh nats_a settings sync
./run.sh nats_b settings sync
./run.sh db migrate
./run.sh web loaddata demo
./run.sh web createsuperuser
pnpm --dir frontend build
./run.sh web static collect
```

`loaddata demo` 导入真实示例数据；已有数据库按 fixture 规则处理，不要为了看页面反复新建随机记录。更新框架源码后也要按需重新 bootstrap、构建/收集 Demo 资源，旧 static 不会因为 Python 已更新而自动变新。

在三个独立终端分别运行：

```sh
./run.sh nats_a start
./run.sh nats_b start
./run.sh web start
```

run.sh 只是便捷命令入口，不会自动拉起其他服务。普通 Core 示例不需要 Worker/Scheduler；但 Web 若仍启用 taskiq，其发布连接仍需要启用 JetStream 的 NATS。只有 Web 的 taskiq.enabled 和 nats_bus.enabled 都关闭，Web 才不需要 NATS。

默认登录地址 `http://127.0.0.1:17997/login`，使用自己创建的管理员。进入侧栏“服务通信”；监听端口若在 YAML 中改过，以实际配置为准。

## 2. 三页分别看什么

| 页面 | 操作 | 应看到什么 |
| --- | --- | --- |
| `/examples/communication/rpc` | 选择真实项目、monitor_a 或 monitor_b，点击查询 | 对端从数据库读到的名称、状态、进度、任务数，以及对端 PID |
| 同一 RPC 页 | 点击“查询并发布” | 同一个 RPC 结果，另发一条报告事件；计数页的报告总数增加 |
| `/examples/communication/events` | 发送 10 条竞争事件，再手动查询计数 | 两节点竞争处理，总数增加 10；不保证各 5 条 |
| 同一事件页 | 发送 10 条广播，再手动查询 | 两个在线节点各增加 10 |
| `/examples/communication/failures` | 无接收者、慢回复、接收函数异常 | 可读失败说明；慢回复/异常需要 nats_a 在线，调用者等待 0.5 秒 |

打开页面只读选项与配置，不发送消息。发送完成后接收者可能还在处理，再点一次“查询计数”即可；这里没有自动轮询。计数是接收进程内固定三项数据，所有 staff 用户共享，重启归零，不写入数据库。多人同时操作时不要把总数当作自己独占的实验。

停止 nats_b 后再观察，monitor_a 的有效结果仍保留，monitor_b 显示无响应者。慢回复 handler 实际等待两秒，前端 0.5 秒就超时；不是超时后取消了对端。故意异常写入 nats_a 日志，调用者可能只知道没有及时回复，框架不传输远程 Python 异常对象。

按钮使用普通 Form、有序 Actions、staff 权限和 CSRF，不允许浏览器任意填写 NATS subject/服务器地址。没有项目先加载数据；不选择或选择已删除项目会按表单/业务错误处理。关闭 nats_bus 时页面仍可查看，操作禁用。

## 3. 消息从哪里来，怎样发送

可直接对照 [Demo 源码](https://github.com/alexliyu7352/oldman-epg-dashboard)：

| 文件 | 职责 |
| --- | --- |
| `apps/examples/nats_messages.py` | ProjectStatusRequest/Reply、ExampleEvent 和计数消息；双方共用 |
| `apps/examples/nats_example.py` | query_project_status、query_and_publish_status、send_example_events、query_observations |
| `apps/communication/apps.py`、`events.py` | 接收 App 与真实 handler；Web 不安装这个接收 App |
| `services/nats_a.py`、`nats_b.py` | 两个 SimpleApplication；等正常停止，不复制连接/订阅循环 |
| `data/*_settings.example.yaml` | 五份受管理的配置样本；运行文件由使用者在 data 中创建 |
| `apps/examples/forms.py`、`views/communication.py` | 实际数据库选项、固定操作、权限、CSRF、业务错误和局部结果 |
| `templates/pages/examples/communication/` | 三页及普通 Form/结果片段，没有专用通信 TS |

消息像 Session 一样有明确字段，不是手工拼 JSON。以下节选自 nats_messages.py：

```python
from oldman.serializers import MsgspecModel

class ProjectStatusRequest(MsgspecModel):
    """Read an existing project, without enqueuing a task or changing its data."""

    project_id: int
```

发送方法直接传对象，bus 来自公开导入；完整返回类型也在同一消息模块。以下是 nats_example.py 的函数节选：

```python
from oldman.providers.nats import bus
from apps.examples.nats_messages import ProjectStatusRequest, ProjectStatusReply

async def query_project_status(project_id: int, peer_id: str) -> ProjectStatusReply:
    """The selected receiving service, not this caller, queries the database."""
    return await bus.request(
        ProjectStatusRequest(project_id=project_id), "project.status", ProjectStatusReply,
        peer_id=peer_id, request_timeout=3,
    )
```

接收端 events.py 使用 `@bus.subscriber("project.status", peer=True, queue="project-status-readers")` 声明 read_project_status；函数用现有 db_manager.get_read_session 查询 ExampleProject/ExampleTask，返回 ProjectStatusReply。读不到项目返回 found=False，是业务结果，不是网络故障。不要直接调用这个 handler 来假装完成 RPC。

不等回复的事件用 `await bus.publish(ExampleEvent(sequence=sequence), subject)`。Demo 的竞争订阅带 queue，广播订阅不带 queue；没有额外的 broadcast 方法。`@bus.publisher("project.status.read")` 则在被装饰的查询函数返回非 None 后发布这个结果，再把同一对象交给调用者。

## 4. 配置如何对应服务

下面节选自 nats_a 的样本，不是完整可替换 YAML：

```yaml
nats:
  TASKIQ:
    nats_url: nats://127.0.0.1:4222
nats_bus:
  enabled: true
  nats_alias: TASKIQ
  namespace: epg_demo
  consume: true
  peer_id: monitor_a
```

- nats_alias=TASKIQ 只是选取已有地址，**不使用 Taskiq 的连接或队列**。
- nats_b 配置 peer_id=monitor_b，其他通信配置一致。
- Web 的 peer_id=web、consume=false；后台任务配置也只发送，不安装接收 App。
- 接收服务的 settings.apps 包含 oldman.auth、apps.auth、apps.examples、apps.communication，前几个提供真实 User/数据模型，最后一个提供 events。Registry 只加载已安装 App，不扫描其他项目。
- 默认 codec 是 msgpack；选择 msgspec_json 时通信双方一起改并重启。两种都直接发送 bytes，不先生成 JSON 字符串。
- namespace 隔离不同项目/环境的名字，不能替代服务器 ACL。来源 peer_id 也不是身份凭据。

开启后由 Application 在实际异步进程中建立连接，业务不在每个页面里 start/stop。接收 handler 会等业务启动钩子完成后才开始；停止先结束接收，再关闭其数据库等依赖。独立脚本与 Shell 的显式上下文见[接口与生命周期](../developers/providers.md#shellide-与独立连接)。

## 5. 从 Taskiq 任务中调用 RPC

先保持 nats_a 在线，确认 Web 和 Worker 的 nats_bus 均开启，再在独立终端启动：

```sh
./run.sh task_worker start
```

打开 `/examples/tasks/results`，选择项目，点击“任务内 RPC”，随后点击“查询此结果”。实际调用 `apps.examples.tasks.project_rpc`：

```python
@broker.task(queue_name="reports")
async def project_rpc(project_id: int) -> dict[str, object]:
    """Use the Worker-owned Core connection, without changing existing tasks."""
    from apps.examples.nats_example import query_project_status

    reply = await query_project_status(project_id, "monitor_a")
    return {"reply": reply.to_dict(), "worker_pid": os.getpid()}
```

这是 tasks.py 的节选；该文件已从 oldman.tasks.distributed 导入 broker，并导入 os。不要为这一方法创建新 broker 或事件循环。结果有 Worker PID 和接收服务 PID，两者不是同一进程；页面查询仍限制为当前用户自己的任务。

这个立即执行的示例不用启动 Scheduler。nats_a 未运行时任务会失败，原任务结果页显示错误，没有默认重试。Taskiq 负责排队，Core RPC 负责这一次在线询问；持久任务不会让 RPC 目标自动上线。

## 6. 失败应该怎样处理

- **启用后启动失败**：核对地址、namespace、凭证/TLS。默认首次 Core 建连总预算 30 秒，超时或连接错误会使该入口启动失败，不假装“后台已经可用”。
- **无响应者**：检查具体接收服务、peer、namespace 和订阅。发送完成不等于有接收者，广播也没有业务确认。
- **超时**：可能请求没到、回复丢失、处理太慢或 handler 出错。先查接收日志，不把超时理解为“对端什么都没做”，写操作不能盲目重发。
- **断线/缓冲满**：连接建立后的重连由原生客户端负责；缓冲满、永久关闭会抛错。Core 离线期间消息不持久补发；必须以后完成的工作交给 Taskiq。
- **权限/CSRF**：由现有 HTTP 错误链路显示，不伪装成 RPC 业务错误。跨用户任务结果不可读。长时间旧页面或换 Session 后需刷新取得有效 token。

正常停止时，先停止新的任务投递，再让 Worker 收尾，最后关闭接收服务及 Web：

```sh
./run.sh task_worker stop     # 仅当本次启动过
./run.sh nats_a stop
./run.sh nats_b stop
./run.sh web stop
```

若另行运行了 Scheduler，先执行 `./run.sh task_scheduler stop`。不要为了停止 Demo 清空整台 NATS 或 Redis。handler 的正常等待默认 10 秒，随后协作取消并等待 finally；不是任意阻塞业务都能在 10 秒内强制退出的保证。原生 TLS 失败清理和实测依赖限制见[开发者参考](../developers/providers.md#停止失败与保证范围)。
