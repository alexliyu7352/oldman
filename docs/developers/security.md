# 安全边界与限流接口

本章说明已有安全机制的职责，不把“配置了一个密钥”描述为整站已安全。登录、Session、CSRF 和错误协商见 [Web 参考](web.md)；部署检查见[运行指南](../users/deployment.md)。

## 凭据、会话和可信 HTML

- 密码使用配置选定 User 的密码方法及 Auth 服务，不把原始密码写入数据库普通字段或日志。
- 认证是身份检查，staff/superuser 是框架提供的粗粒度权限；对象归属和租户范围仍由业务查询验证。
- Session 是 Redis 中的登录快照。权限或密码改变不等于所有既有 Session 自动失效；需要撤销时显式执行 Session 操作。
- CSRF 保护浏览器基于 Cookie 的写请求，不替代登录和对象权限，也不是对所有 API 的自动认证。
- 可信 HTML 可以用于有明确协议的 Table、消息或通知正文；应用负责选择可信模板，并转义插入其中的不可信用户值。纯文本字段不要先手工 HTML 转义再交给 textContent。
- 附件路径是 Storage 逻辑名，不把客户端提供的本地路径直接交给文件系统。上传扩展名不是文件内容的真实性或安全证明。

## 统一安全密钥

```python
from oldman.web.security import (
    WebSecurityPurpose,
    configured_web_security_key,
    derive_web_security_key,
)
```

`configured_web_security_key(purpose)` 读取全局 `settings.web.security.secret_key`，按用途派生 URL-safe 密钥。空根密钥明确报错，要求先 settings sync；不会临时生成不同值。

`derive_web_security_key(root_secret, purpose)` 不读取配置。根字符串至少 32 字符；purpose 必须是 WebSecurityPurpose，当前包括 CSRF、SELECT_BINDING、FLASH。不同用途不共用同一个签名值。不要为业务新协议借用不相关用途，更不要把根密钥发给浏览器。

轮换根密钥会使依赖它的既有令牌/签名不再有效，应协调服务配置和客户端重新获取令牌。各 worker 使用相同持久配置，不能按 worker 随机生成。

## 请求限流

下面是公开接口用法，不是 Demo 已经安装的全站限流。namespace、subject 和 path 由应用按自己的接口填写；仅有配置或创建 limiter 不会自动拦截请求。

```python
from oldman.providers.redis import redis_client
from oldman.web.security.rate_limiter import RedisFixedWindowRateLimiter

limiter = RedisFixedWindowRateLimiter(
    redis_client.using("DEFAULT"),
    namespace="taskboard:production:http-limit",
)
```

这段放在 bootstrap 后加载的业务模块；构造时不主动连接 Redis。应用将已确定的用户 ID 或可信 IP 作为 subject：

```python
limited = await limiter.is_rate_limited(
    subject=user_id,
    path="/reports/export",
    limit=10,
    period=60,
)
```

这里的 user_id 来自已验证身份；片段放在异步视图中。返回 true 表示本窗口次数已超过限制。每次调用都会计数，前十次允许，第十一次拒绝；period 必须大于零，limit 不得为负。窗口按服务器时间划分，不是滑动窗口，临界处可能突发。

它不自动注册中间件或返回 HTTP 响应。视图据结果返回 429；Redis 异常向上传递，由业务选择是否拒绝或降级，不能默默假设允许。namespace 用于隔离项目和环境；服务端时钟也应保持合理同步。

## 指纹与 IP 联合策略

`FingerprintIPRateLimiter(client, *, fail_open=True)` 通过 Redis Lua 一次判断指纹/IP 计数、关联关系和黑名单。使用 `await limiter.check(fingerprint, ip, endpoint, config)`；config 为 `settings.web.security.fingerprint`，endpoint 命中 rate_limits 配置，否则使用 default。

返回 `FingerprintRateLimitDecision`：allowed、reason、fingerprint_count、ip_count、anomalies。默认 fail_open 意味着 Redis 故障时允许；需要拒绝时显式设置 false，并处理可见错误。它没有可配置的项目 key 前缀，部署时用独立 Redis 数据库隔离该策略的固定 key；不要把这些 key 与普通 SSE channel 的隔离规则混淆。

`get_fingerprint_from_front(encrypted_b64, aes_secret_key, max_diff)` 使用 `AESGcmDecrypt.decrypt()` 解析浏览器 AES-GCM 数据，成功返回 `(visitor_id, "success")`，失败返回空 ID 与原因。传输格式是 Base64 编码的 12 字节 IV、密文和 16 字节 tag；解密后的业务字段为 vid 和毫秒 ts。调用者仍需控制请求大小、输入类型和失败处理；该工具不是完整请求 schema 校验器。

`validate_payload(payload, max_diff)` 要求已解析字典及可计算的毫秒时间戳，返回 `(有效, 原因, visitor_id)`。`log_fake_fingerprint_attempt(ip, reason)` 写入默认 Redis 并可能拉黑 IP；`get_stats(fingerprint)` 返回统计 JSON，**自身没有鉴权装饰器**。只有受保护的管理接口才能调用后公开结果。

浏览器能参与生成的指纹不是用户身份凭证。这些工具也不会因 settings 存在就自动覆盖所有路由；需要具体业务接线，不替代密码、Session、CSRF 或服务器权限判断。
