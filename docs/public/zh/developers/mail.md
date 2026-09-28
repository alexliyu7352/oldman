# 邮件

`oldman.mail` 负责发出邮件：形状照 Django 的 `django.core.mail`，全部是协程；消息用标准库 `email.message.EmailMessage` 组装，SMTP 传输用 [aiosmtplib](https://github.com/cole/aiosmtplib)。它只管"把一封或一批消息交给后端"，不排队、不重试、不管收信。

## 配置

根配置 `mail`，Web 和任务进程共用：

```yaml
mail:
  backend: oldman.mail.backends.smtp.SMTPEmailBackend
  default_from_email: "Oldman <noreply@example.com>"
  subject_prefix: "[Oldman] "
  admins:
    - ops@example.com
  smtp:
    host: smtp.example.com
    port: 587
    username: mailer
    password: "..."
    use_tls: true
    timeout: 10
```

| 字段 | 默认 | 含义 |
| --- | --- | --- |
| `backend` | `oldman.mail.backends.console.ConsoleEmailBackend` | 后端类的导入路径；默认把邮件打印到标准输出，生产环境显式改成 smtp |
| `default_from_email` | `webmaster@localhost` | 消息没有指定发件人时使用 |
| `subject_prefix` | `[Oldman] ` | 只加在 `mail_admins()` 的主题前面，和 Django 一样 |
| `admins` | 空 | `mail_admins()` 的收件人；为空时该函数什么也不发 |
| `file_path` | 空 | filebased 后端写 `.eml` 文件的目录 |
| `smtp.host` / `port` | `localhost` / `25` | SMTP 服务器 |
| `smtp.username` / `password` | 空 | 为空时不登录 |
| `smtp.use_tls` | `false` | 连接后用 STARTTLS 升级（通常配 587） |
| `smtp.use_ssl` | `false` | 一开始就是 TLS 连接（通常配 465）；和 `use_tls` 互斥 |
| `smtp.timeout` | `10` | 连接和每条命令的超时秒数 |
| `smtp.local_hostname` | 空 | EHLO 报出的主机名 |

密码和数据库、Redis 密码一样写在 YAML 里，settings 只读 YAML。`settings sync` 会把这一组连注释一起补进已有的配置文件。

内置后端：

| 后端 | 用途 |
| --- | --- |
| `oldman.mail.backends.smtp.SMTPEmailBackend` | 真正发送；一次 `send_messages()` 用一条连接，`async with` 里可以跨多次调用复用 |
| `oldman.mail.backends.console.ConsoleEmailBackend` | 打印到 `stream`（默认标准输出），每封后面一行分隔线；开发默认 |
| `oldman.mail.backends.filebased.FileEmailBackend` | 每封写成 `<时间戳>-<序号>.eml`，目录来自 `mail.file_path` 或 `file_path` option |
| `oldman.mail.backends.locmem.LocmemEmailBackend` | 追加到 `oldman.mail.outbox`，测试用 |
| `oldman.mail.backends.dummy.DummyEmailBackend` | 只计数，不发送 |

## 发送

```python
from oldman.mail import send_mail

await send_mail(
    "Welcome",
    "Plain text body",
    None,                      # None 取 mail.default_from_email
    ["ada@example.com"],
    html_message="<p>HTML body</p>",
)
```

返回值是后端接受的消息数。没有收件人的消息不发送并返回 0。`fail_silently=True` 只吞后端抛出的传输异常（连接失败、认证失败、被拒收），模板缺失、地址类型错误这类程序错误照样抛。

同类辅助函数：`send_mass_mail([(subject, body, from_email, recipients), ...])` 用一条连接发多封；`mail_admins(subject, body)` 发给 `mail.admins`，主题自动加前缀。

## 消息对象

```python
from oldman.mail import EmailMultiAlternatives

message = EmailMultiAlternatives(
    subject="Report",
    body="See attachment",
    from_email="Reports <reports@example.com>",
    to=["ada@example.com"],
    cc=["lead@example.com"],
    bcc=["audit@example.com"],
    reply_to=["support@example.com"],
    headers={"X-Report": "weekly"},
)
message.attach_alternative("<p>See attachment</p>", "text/html")
message.attach("report.csv", "a,b\n1,2\n", "text/csv")   # 文本内容只能配 text/* 类型
message.attach_file("/tmp/chart.png")                      # 类型按文件名猜，猜不到用 application/octet-stream
await message.send()
```

`to`、`cc`、`bcc`、`reply_to` 必须是列表或元组，传字符串会抛 `TypeError`。Bcc 只进 SMTP 信封，不出现在邮件头。`message()` 返回标准库的 `EmailMessage`，Date 和 Message-ID 自动补上，`headers` 里同名的头覆盖默认值。

`get_connection(backend=None, fail_silently=False, **options)` 直接拿后端；批量发送时：

```python
from oldman.mail import get_connection

async with get_connection() as connection:
    await connection.send_messages(messages)
```

## 模板邮件

Django 没有内置这一层，找回密码这类流程需要，所以框架提供 `send_templated_mail`。约定三个模板，前两个必须有：

- `<name>.subject.txt`：主题，渲染后折成一行；
- `<name>.txt`：纯文本正文；
- `<name>.html`：可选，存在时作为 HTML 备选一起发。

```python
from oldman.mail import send_templated_mail

await send_templated_mail(
    "mail/welcome",
    {"name": user.display_name},
    to=[user.email],
    language=user.language,
)
```

模板走框架的 Jinja 环境，项目 `templates/` 目录里的同名文件覆盖框架内置的；`.txt` 不转义，`.html` 转义，和页面模板一致。`language` 传语言代码时，渲染期间绑定该语言的翻译目录，模板里的 `{{ _("...") }}` 按收件人的语言输出，不受当前请求语言影响；这依赖 Web i18n 已初始化。`render_mail()` 只渲染不发送，返回 `RenderedMail(subject, body, html)`。

## 什么时候发

`send_mail` 是协程，请求处理里直接 `await`：SMTP 有超时（默认 10 秒），失败抛异常。不想让响应等邮件，就交给进程内的后台任务管理器（Web 服务的 `task_manager`）；真正的排队和重试走 [Taskiq](distributed-tasks.md)，把 `send_mail` 包进一个任务即可，邮件层不自己造队列。

## 测试

单元测试用 locmem 后端和 `use_mail_config()`，不需要 bootstrap：

```python
from oldman import mail
from oldman.conf.schemas import MailConfig
from oldman.mail import use_mail_config

with use_mail_config(MailConfig(backend="oldman.mail.backends.locmem.LocmemEmailBackend")):
    await send_mail(...)
assert mail.outbox[0].subject == "..."
```

框架自己的 SMTP 后端用 aiosmtpd 起本地服务做真实收发测试（`tests/test_oldman_mail_smtp.py`），项目一般不需要重复。

## 验证生产配置

```bash
oldman web mail sendtest ops@example.com
```

它按该服务的配置发一封测试邮件，打印后端接受的数量；console 后端会把邮件本身打印出来。这是 Django `sendtestemail` 的对应物。

## 增加后端

继承 `oldman.mail.BaseEmailBackend`，实现 `send_messages(messages) -> int`；持有连接的后端再实现 `open()`（新建连接时返回 True）和 `close()`。构造参数对应 `get_connection(**options)`。把类路径写进 `mail.backend` 即可，其他代码不用改。
