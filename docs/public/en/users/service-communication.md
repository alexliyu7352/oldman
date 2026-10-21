# Let running services communicate with each other

This chapter runs the standalone EPG Dashboard's “Service communication” example. Two actual background receiving services let a page query a selected service's project status or send events to both services. Data comes from the demo database, rather than being fabricated in the frontend.

Distinguish three capabilities: NATS/FastStream provides online events and RPC between background services; Taskiq provides durable queued background tasks; SSE streams realtime data from servers to browsers. An RPC does not automatically become a durable task or display a browser notification.

## 1. Prepare and start the Demo

The working directory is an independent `oldman_epg_dashboard`, not the framework source code directory. See [Quick Start](getting-started.md) for complete installation. The following are the actual steps related to this example in its README.

```sh
python3 scripts/bootstrap.py
for service in web task_worker task_scheduler nats_a nats_b; do
  test -e "data/${service}_settings.yaml" || cp "data/${service}_settings.example.yaml" "data/${service}_settings.yaml"
done
```

Existing files are not overwritten. Project migrations read every service's configuration, so prepare all five YAML files even for only the communication pages. They must use the same database and Auth User model. Check Redis/NATS addresses for your environment; do not experiment with production databases.

The default NATS of the Demo is 127.0.0.1:4222; the task uses Redis TASKIQ's 6379/7, and the Session uses their own alias. Prepare Redis and NATS first. When nats-server is installed, you can execute it in a separate terminal:

```sh
nats-server -js -sd data/nats
```

Core itself does not require JetStream, but the Demo also enables Taskiq by default, so this example server enables JetStream. Do not start again on a port occupied by an existing service; production authentication/TLS is configured by deployment and does not copy the loopback without authentication example.

First initialization:

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

`loaddata demo` imports real sample data; existing databases are processed according to fixture rules. Do not repeatedly create random records just to see the page. After updating the framework source code, you must re-bootstrap and build/collect Demo resources as needed. The old static will not automatically become new because Python has been updated.

Run in three separate terminals:

```sh
./run.sh nats_a start
./run.sh nats_b start
./run.sh web start
```

run.sh is just a convenient command entry and will not automatically start other services. The normal Core example does not require Worker/Scheduler; but if the Web still enables taskiq, its published connection still needs to enable JetStream's NATS. The Web does not require NATS only if both taskiq.enabled and nats_bus.enabled of the Web are turned off.

The default sign-in address is `http://127.0.0.1:17997/login`. Use the administrator you created, then choose “Service communication” in the sidebar. If YAML changes the listening port, use the actual setting.

## 2. What to read on each of the three pages?

| Page | Action | What should you see |
| --- | --- | --- |
| `/examples/communication/rpc` | Select the real project, monitor_a or monitor_b, click to query | The name, status, progress, number of tasks read by the peer from the database, and the peer PID |
| The same RPC page | Click "Query and publish" | The same RPC result, another report event is sent; the total number of reports on the count page increases |
| `/examples/communication/events` | Send 10 competing-consumer events, and then manually query the count | Two nodes compete for processing, the total number increases by 10; 5 events each are not guaranteed |
| The same event page | sends 10 broadcasts, and then manually queries | Two online nodes each add 10 |
| `/examples/communication/failures` | No receiver, slow reply, receiving function exception | Readable failure description; slow reply/exception requires nats_a to be online, the caller waits for 0.5 seconds |

Opening a page reads only options and configuration; it sends no messages. Receivers may still be processing after sending finishes; click “Query current counters” again. There is no automatic polling. Three fixed counters live only in receiving processes, shared by all signed-in users, reset on restart, and never written to the database. With concurrent users, totals are not exclusive to your experiment.

After stopping nats_b and observing again, the valid results of monitor_a are still retained, and monitor_b shows no responders. The slow reply handler actually waits for two seconds, and the front end times out in 0.5 seconds; it does not cancel the peer after timeout. Intentional exceptions are written to the nats_a log and the caller may only know that there is no timely reply and the framework does not transmit the remote Python exception object.

Buttons use ordinary Forms, ordered Actions, staff permissions, and CSRF. Browsers cannot supply arbitrary NATS subjects or server addresses. Load data first if there are no projects; a missing selection or a deleted project produces form/business errors. With nats_bus disabled, pages remain viewable but operations are disabled.

## 3. Where does the message come from and how is it sent?

You can directly compare [Demo source code](https://github.com/alexliyu7352/oldman-epg-dashboard):

| File | Responsibilities |
| --- | --- |
| `apps/examples/nats_messages.py` | ProjectStatusRequest/Reply, ExampleEvent and count messages; shared by both parties |
| `apps/examples/nats_example.py` | query_project_status, query_and_publish_status, send_example_events, query_observations |
| `apps/communication/apps.py`, `events.py` | receiving App and real handler; Web does not install this receiving App |
| `services/nats_a.py`, `nats_b.py` | Two SimpleApplications; wait for normal stop, do not copy the connection/subscription cycle |
| `data/*_settings.example.yaml` | Five managed configuration samples; run files are created by the user in data |
| `apps/examples/forms.py`, `views/communication.py` | Actual database options, fixed operations, permissions, CSRF, business errors and partial results |
| `templates/pages/examples/communication/` | Three pages and normal Form/result fragment, no dedicated communication TS |

Like Session, messages have explicit fields, rather than manually assembled JSON. The following is from nats_messages.py:

```python
from oldman.serializers import MsgspecModel

class ProjectStatusRequest(MsgspecModel):
    """Read an existing project, without enqueuing a task or changing its data."""

    project_id: int
```

The send method directly passes the object, and bus comes from the public import; the complete return type is also in the same message module. The following is a function excerpt from nats_example.py:

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

The receiver's events.py declares read_project_status with `@bus.subscriber("project.status", peer=True, queue="project-status-readers")`. It queries ExampleProject/ExampleTask through existing db_manager.get_read_session and returns ProjectStatusReply. A missing project returns found=False, a business result rather than a network failure. Calling this handler directly does not verify RPC.

Use `await bus.publish(ExampleEvent(sequence=sequence), subject)` for events needing no reply. Competing subscriptions in the demo specify queue; broadcast subscriptions omit it. There is no separate broadcast method. `@bus.publisher("project.status.read")` publishes a decorated query function's non-None result, then returns that same object to the caller.

## 4. How to configure corresponding services

The following is an excerpt from nats_a's sample, which is not a complete replaceable YAML:

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

- nats_alias=TASKIQ only selects an existing address; it **does not use Taskiq connections or queues**.
- nats_b configures peer_id=monitor_b, and other communication configurations are consistent.
- Web's peer_id=web, consume=false; the background task configuration is only for sending, and the receiving app is not installed.
- Receiving services install oldman.auth, apps.accounts, apps.examples, and apps.communication through settings.apps. The first Apps provide the actual User/data models, and the last provides events. Registry loads only installed Apps, without scanning other projects.
- The default codec is msgpack; when msgspec_json is selected, both communicating parties will change it together and restart. Both send bytes directly without generating a JSON string.
- namespace is a name that isolates different projects/environments and cannot replace server ACLs. The source peer_id is also not an identity credential.

When enabled, Application connects inside the actual asynchronous process; business code does not start/stop it for each page. Receiving handlers start only after business startup hooks finish. Shutdown ends receiving before closing database and other dependencies. See [Interfaces and lifecycle](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/providers.md#shellide-与独立连接) for explicit contexts in scripts and Shell.

## 5. Call RPC from Taskiq task

First keep nats_a online, confirm that the nats_bus of Web and Worker are both turned on, and then start it in an independent terminal:

```sh
./run.sh task_worker start
```

Open `/examples/tasks/results`, select the project, click "RPC inside a task", and then click "Query this result". Actual call `apps.examples.tasks.project_rpc`:

```python
@broker.task(queue_name="reports")
async def project_rpc(project_id: int) -> dict[str, object]:
    """Use the Worker-owned Core connection, without changing existing tasks."""
    from apps.examples.nats_example import query_project_status

    reply = await query_project_status(project_id, "monitor_a")
    return {"reply": reply.to_dict(), "worker_pid": os.getpid()}
```

This is an excerpt from tasks.py, which already imports broker from oldman.tasks.distributed and imports os. Do not create a new broker or event loop for this method. Results contain both Worker and receiving-service PIDs, which are different processes. Page queries remain limited to the current user's tasks.

This example executes immediately without starting the Scheduler. The task will fail when nats_a is not running. The original task result page displays an error and there is no default retry. Taskiq is responsible for queuing, and Core RPC is responsible for this online query; persistent tasks will not automatically bring the RPC target online.

## 6. How to deal with failure

- **Startup failure after enabling**: check addresses, namespace, and credentials/TLS. Initial Core connection has a total default deadline of 30 seconds. Timeout or connection failure fails startup; do not claim the background service is ready.
- **No responders**: check the specific receiver, peer, namespace, and subscription. Completed sending does not establish a receiver, and broadcasts have no business acknowledgment.
- **Timeout**: the request may not have arrived, the reply may be lost, processing may be slow, or the handler may have failed. Check receiver logs first. Timeout does not mean the peer did nothing; do not blindly retry writes.
- **Disconnection/full buffer**: the native client reconnects after initial connection. A full buffer or permanent close raises errors. Core does not durably replay offline messages; use Taskiq for work that must finish later.
- **Permissions/CSRF**: existing HTTP error handling displays these failures, rather than presenting them as RPC business errors. Results owned by other users are inaccessible. Refresh old pages or after a Session change for a valid token.

When stopping normally, first stop new task delivery, then let the Worker finish, and finally close the receiving service and Web:

```sh
./run.sh task_worker stop     # Only if started in this run
./run.sh nats_a stop
./run.sh nats_b stop
./run.sh web stop
```

If you also ran a Scheduler, stop it first with `./run.sh task_scheduler stop`. Do not clear an entire NATS or Redis instance to stop the demo. Handlers normally have 10 seconds to finish, followed by cooperative cancellation and waiting for finally. This does not guarantee forced termination of arbitrary blocking work within 10 seconds. See the [Developer Reference](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/providers.md#停止失败与保证范围) for native TLS failure cleanup and measured dependency limits.

<!-- source: zh/users/service-communication.md @ db5eb607 -->
