# Security boundaries and rate limiting

This chapter explains existing security responsibilities. A configured key does not establish whole-site security. See [Web requests, templates, and permissions](web.md) for sign-in, Session, CSRF, and error negotiation, and [Deployment and Operations](../users/deployment.md) for deployment checks.

## Credentials, sessions, and trusted HTML

- Passwords use the configured User's password methods and Auth services. Do not store raw passwords in ordinary database fields or logs.
- Authentication identifies callers; staff/superuser provide coarse framework permissions. Business queries still enforce object ownership and tenant scope. Only superusers manage staff/superuser accounts: others must not create/edit/delete/activate/deactivate them, change their passwords, or grant staff/superuser flags to any account.
- Sessions and access tokens are sign-in snapshots of password validity and active/staff/superuser flags. Framework password changes (self-service, administrator, recovery, CLI `changepassword`, `createsuperuser --update`) and Admin deactivation/deletion/flag changes invalidate all user Sessions/access tokens. Use `revoke_user_logins` with requests and `end_user_logins` without them. Custom user management views must do likewise. Compare `oldman.auth.user_access_flags(user)` before/after saving to detect flag changes.
- CSRF protects Cookie-based browser writes. It replaces neither sign-in nor object permissions and is not automatic authentication for every API.
- Trusted HTML may appear in explicitly defined Table/message/notification bodies. Applications choose trusted templates and escape inserted untrusted values. Do not manually HTML-escape plain text before assigning textContent.
- Attachment paths are Storage logical names. Do not pass client-supplied local paths directly to the filesystem. Upload extensions establish neither content authenticity nor safety.

## Shared security keys

```python
from oldman.web.security import (
    WebSecurityPurpose,
    configured_web_security_key,
    derive_web_security_key,
)
```

`configured_web_security_key(purpose)` reads global `settings.web.security.secret_key` and derives URL-safe purpose-specific keys. Empty roots fail explicitly and request settings sync, without temporary generated replacements.

`derive_web_security_key(root_secret, purpose)` reads no settings. Roots require at least 32 characters; purpose must be WebSecurityPurpose, currently CSRF, SELECT_BINDING, or FLASH. Purposes have different signing values. Do not borrow unrelated purposes for business protocols or send root keys to browsers.

Root rotation invalidates dependent existing tokens/signatures. Coordinate service settings and client token renewal. Workers use the same persistent configuration; do not generate separate random worker secrets.

## Password reset tokens

`oldman.auth.password_reset.PasswordResetTokenGenerator` follows Django: a key derived from `web.security.secret_key` signs user ID, current password hash, last sign-in time, email, and issuance time with HMAC-SHA256. Tokens look like `<base36-timestamp>-<32-character-digest>`. No database storage is used; password changes, subsequent sign-in, expiry (`auth.password_reset.expiry`, default 24 hours), or tampering invalidates them. `encode_user_id()` generates the link's user identifier; `decode_user_id()` returns None for invalid input.

Web `oldman.web.auth.PasswordResetFlow` connects requests, email, validation, password changes, and ending other sessions. Admin `/password-reset` uses this flow. It takes one `base_path`: requests at the base, “Check your email” at `<base_path>/sent`, email confirmation at `<base_path>/<uidb64>/<token>`, completion at `<base_path>/done`. These fixed subpaths are available through `request_path`, `sent_path`, `done_path`, and `confirm_path(uidb64, token)`. Dashboards pass `web.account.password_reset_url`, also used by sign-in's “Forgot password?” link (see [Web requests, templates, and permissions](web.md#ready-made-account-flows)); if unset, no reset flow is installed.

```python
account = settings.web.account
flow = PasswordResetFlow(
    base_path=account.password_reset_url,
    login_path=account.login_url,
    home_path=account.login_redirect_url,
)
flow.register_routes(template_prefix="pages/password_reset")
```

`settings` comes from project `config.settings`; execute this only when `account.password_reset_url` is not None. Emails use `core.site_name`, falling back to `core.app_name`. Override with `site_name=` if needed; built-in Admin passes `site_title`.

`register_routes()` installs six views: request page/submission, sent page, new-password page/submission, and completion. It includes CSRF, `no-store`/`Referrer-Policy: same-origin` (token URLs stay out of cross-site Referer while local forms retain real Origin), 429 `Retry-After`, and signed-in redirects to `home_path`. Do not reimplement them. `template_prefix` requires request/sent/confirm/invalid/done.html. Templates receive `csrf_token`, `login_url`, `request_url`, `expiry_hours`; request/confirmation also receive `form`/`action`, confirmation gets `username`, and rate-limited requests get `rate_limited`. For custom context such as Admin menus, replace default rendering with `render=`, signature `async def render(request, page, /, **context)`; pass only one of those two options. `name_prefix=` controls route names. Without the first argument, routes register through `oldman.web.router`; explicit instances remain supported, as used by Admin. Requests use fixed-window limits below: excess IP requests get 429, excess email requests silently send nothing, avoiding account enumeration through limits. IPs use `request.client_ip`; configure `web.proxies_count` behind proxies (see [Web requests, templates, and permissions](web.md#client-addresses-and-proxies)) or all visitors share one proxy bucket. Sending uses an in-process background task (`request.app.ctx.tasks.spawn()`), without waiting for SMTP. Mail failures only log and do not change responses, so timing/status reveal no account existence.

## Request rate limiting

This is public API usage, not site-wide limiting installed in the demo. Applications supply namespace, subject, and path for their endpoints. Settings or limiter construction alone do not intercept requests.

```python
from oldman.providers.redis import redis_client
from oldman.web.security.rate_limiter import RedisFixedWindowRateLimiter

limiter = RedisFixedWindowRateLimiter(
    redis_client.using("DEFAULT"),
    namespace="taskboard:production:http-limit",
)
```

Place this in a business module loaded after bootstrap. Construction does not connect to Redis. Applications use a verified user ID or trusted IP as subject:

```python
limited = await limiter.is_rate_limited(
    subject=user_id,
    path="/reports/export",
    limit=10,
    period=60,
)
```

Here user_id comes from verified identity and the excerpt runs in an async view. True means this window's limit was exceeded. Every call counts: ten allowed, the eleventh rejected. period must be positive and limit nonnegative. Windows use server time rather than sliding windows; boundary bursts are possible.

It registers no middleware or HTTP responses. Views return 429 based on decisions. Redis failures propagate; business code chooses rejection/fallback rather than silently assuming permission. Namespaces isolate projects/environments; keep server clocks reasonably synchronized.

## Combined fingerprint and IP policies

`FingerprintIPRateLimiter(client, *, fail_open=True)` uses one Redis Lua evaluation for fingerprint/IP counts, relationships, and blacklists. Call `await limiter.check(fingerprint, ip, endpoint, config)` with `settings.web.security.fingerprint`. endpoint selects rate_limits or falls back to default.

It returns `FingerprintRateLimitDecision`: allowed, reason, fingerprint_count, ip_count, and anomalies. Default fail_open allows Redis failures; set false explicitly for rejection and handle visible errors. Count, relationship, blacklist, and log keys all use `<core.namespace>:fingerprint:`. Services sharing Redis use different namespaces for isolation or the same namespace for a shared blacklist.

`get_fingerprint_from_front(encrypted_b64, aes_secret_key, max_diff)` parses browser AES-GCM through `AESGcmDecrypt.decrypt()`. Success returns `(visitor_id, "success")`; failures return an empty ID and reason. Wire format is Base64 of a 12-byte IV, ciphertext, and 16-byte tag. Decoded business fields are vid and millisecond ts. Callers still bound request size and handle failures; this is not a full request schema validator. `validate_payload` checks `vid`/`ts` types, returning reasons such as `invalid_timestamp` rather than raising for forged types.

### Cryptographic primitives versus business behavior

AES-GCM lives in `oldman.utils.crypto`; `AESGcmDecrypt` handles only the browser wire format:

- `aes_gcm_encrypt(plaintext: bytes, key: bytes) -> bytes` returns `IV || ciphertext || tag` with a fresh random IV.
- `aes_gcm_decrypt(payload: bytes, key: bytes) -> (ok, reason, plaintext)`. **Failures include reasons**:
  `data_too_short`、`authentication_failed:…`、`decryption_error:…`。
  Callers need to distinguish encryption with a different key from truncated transmission; they imply different conclusions about senders.
- `AESGcmDecrypt.decrypt(encrypted_b64, aes_secret_key)` adds a Base64 envelope and JSON parsing,
  with additional reasons `invalid_encoding:…` and `invalid_json`.

`generate_secure_token(length=10)` returns **exactly `length` characters** from an alphabet excluding confusing I, L, O, 0, and 1.

Browsers reuse encrypted payloads for `ttlMs` (default 240000ms); servers check timestamp age using `timestamp_max_diff`
(default 300000ms). **`ttlMs` must be noticeably less than `timestamp_max_diff`**:
if equal, requests in the payload's last milliseconds cross the tolerance after network delay and get 403,
while clients still consider the payload valid and resend it, causing intermittent hard-to-reproduce 403s. Clock drift widens this window.
Reduce frontend `ttlMs` whenever reducing `timestamp_max_diff`. `tests/test_oldman_web_security.py`
guards the margin between these defaults.

`validate_payload(payload, max_diff)` requires a parsed dictionary and computable millisecond timestamp, returning `(valid, reason, visitor_id)`. `log_fake_fingerprint_attempt(ip, reason)` writes to **Redis holding Web security state** (selected by `oldman.web.security.store.security_redis_alias()`, following `web.session.redis_alias`) and may blacklist IPs. The limiter reads that same connection to observe these blacklists. `get_stats(fingerprint)` returns statistics JSON **without its own authentication decorator**. Expose results only through protected administrative endpoints.

Fingerprints browsers help generate are not user credentials. These tools do not cover all routes merely because settings exist. They need business wiring and replace neither passwords, Session, CSRF, nor server permission checks.

<!-- source: zh/developers/security.md @ 05bb4d84 -->
