import base64
import hashlib
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from cryptography.fernet import Fernet

import oldman.conf as conf
from oldman.serializers import MsgspecModel
from oldman.web.request import Request
from oldman.web.routing import WebApp
from oldman.web.security.csrf.csrf_extension import CsrfExtension
from oldman.web.security.keys import (
    WebSecurityPurpose,
    derive_web_security_key,
)


class Payload(MsgspecModel):
    sid: str
    exp: int
    url: str


class StatelessCSRFManager:
    """
    无状态 CSRF Token 管理器

    Token 组成: {session_id/anonymous, expire_time, url_hash} -> 对称加密
    验证: 解密 -> 检查 Referer -> 检查有效期 -> 检查 session_id
    """

    def __init__(
        self,
        app: WebApp | None = None,
        secret_key: str | None = None,
        ttl: int | None = None,
        anonymous_id: str = "anonymous",
        session_name: str = "session",
        check_referer: bool | None = None,
        check_url: bool | None = None,
        enforce: bool | None = None,
    ):
        self.ttl = 3600 if ttl is None else ttl
        self.anonymous_id = anonymous_id
        self.session_name = session_name
        self.check_referer = True if check_referer is None else check_referer
        self.check_url = False if check_url is None else check_url
        self.enforce = False if enforce is None else enforce
        self._enforce_overridden = enforce is not None
        self._ttl_overridden = ttl is not None
        self._check_referer_overridden = check_referer is not None
        self._check_url_overridden = check_url is not None
        self.cipher: Fernet | None = None

        if app:
            self.init_app(app, secret_key)

    def init_app(self, app: WebApp, secret_key: str | None = None):
        """初始化应用"""
        secret = secret_key
        if secret is None:
            security_config = conf.settings.web.security
            csrf_config = security_config.csrf
            if not self._ttl_overridden:
                self.ttl = csrf_config.ttl
            if not self._check_referer_overridden:
                self.check_referer = csrf_config.check_referer
            if not self._check_url_overridden:
                self.check_url = csrf_config.check_url
            if not self._enforce_overridden:
                self.enforce = csrf_config.enforce
            root_secret = security_config.secret_key
            if root_secret is None:
                raise RuntimeError("settings.web.security.secret_key is empty; run `oldman <service> settings sync`")
            secret = derive_web_security_key(
                root_secret,
                WebSecurityPurpose.CSRF,
            )

        key = hashlib.sha256(secret.encode()).digest()
        fernet_key = base64.urlsafe_b64encode(key)
        self.cipher = Fernet(fernet_key)

        # 挂载到 app.ctx
        app.ctx.csrf = self

        if self.enforce:
            self.register_enforcement(app)

        # 注册中间件
        async def inject_csrf_token(request: Request):
            """为每个请求注入 csrf_token"""
            request.ctx.csrf_token = self.generate_token(request)

        # app.register_middleware(inject_csrf_token, MiddlewareLocation.REQUEST.name)
        app.register_listener(self.before_server_start, "before_server_start")

    async def _setup_jinja2(self, app: WebApp):
        """注册 Jinja2 CSRF 扩展"""
        """配置 Jinja2 环境，添加 i18n 扩展"""
        jinja_env = app.ext.environment
        jinja_env.add_extension(CsrfExtension)
        jinja_env.globals.setdefault("csrf_token_for", csrf_token_for)

    def _get_session_id(self, request: Request) -> str:
        """
        获取 session_id

        request.ctx 是 SimpleNamespace，直接访问属性
        """
        # 直接访问属性，如果不存在会抛出 AttributeError
        try:
            session = request.ctx.session
            # session 可能是字典或对象，统一处理
            if isinstance(session, dict):
                sid = session.get("sid")
                user_id = session.get("user_id")
            else:
                sid = getattr(session, "sid", None)
                user_id = getattr(session, "user_id", None)
            identity = sid if sid else user_id
            return self.anonymous_id if identity is None or identity == "" else str(identity)
        except AttributeError:
            return self.anonymous_id

    def _get_url_hash(self, url: str) -> str:
        """生成 URL 哈希"""
        return hashlib.md5(url.encode()).hexdigest()[:16]

    def generate_token(self, request: Request) -> str:
        """
        生成 CSRF token

        Token 结构: {session_id, expire_time, url_hash} -> 加密
        """
        session_id = self._get_session_id(request)
        expire_time = int(time.time()) + self.ttl
        url_hash = self._get_url_hash(request.path)

        payload = Payload(
            sid=session_id,
            exp=expire_time,
            url=url_hash,
        )
        encrypted = self._require_cipher().encrypt(payload.to_msgpack())
        return encrypted.decode("utf-8")

    def _decrypt_token(self, token: str) -> Payload | None:
        """解密 token"""
        cipher = self._require_cipher()
        try:
            encrypted_bytes = token.encode("utf-8")
            decrypted = cipher.decrypt(encrypted_bytes)
            return Payload.from_msgpack(decrypted)
        except Exception:
            return None

    @staticmethod
    def _url_host(value: str | None) -> str | None:
        """Host of an Origin or Referer value; None for empty, "null", or unparseable.

        `null` is a real Origin value browsers send for opaque/cross-site navigations
        (a page with `referrer-policy: no-referrer` downgrades a cross-site POST's Origin
        to exactly this), so it must resolve to "no host", never to a match.
        """
        if not value or value == "null":
            return None
        host = urlparse(value).hostname
        return host.lower() if host else None

    def _validate_same_origin(self, request: Request) -> bool:
        """Reject a cross-origin state-changing request using Origin, then Referer.

        Origin is the primary check: browsers send it on every unsafe-method request and
        `referrer-policy` cannot suppress it (only the Referer), so it is present exactly
        when the Referer is not. It is compared for an exact host match against the request
        host — a foreign host, a `null` value, or a missing host is a cross-site request.

        Referer is the fallback for the rare request that carries no Origin. When neither
        is present the request is rejected: a browser issuing a real form POST always sends
        at least Origin, so "both absent" is not a shape a same-site form produces.
        """
        if not self.check_referer:
            return True

        request_host = request.host.split(":")[0].lower() if request.host else None
        if not request_host:
            return False

        headers = request.headers or {}
        origin = headers.get("Origin") or headers.get("origin")
        if origin is not None:
            return self._url_host(origin) == request_host

        referer = headers.get("Referer") or headers.get("referer")
        if referer:
            return self._url_host(referer) == request_host

        return False

    def get_token_from_request(self, request: Request) -> str | None:
        """从请求中提取 CSRF token"""
        # 1. 表单数据
        form = request.form
        token = form.get("csrfmiddlewaretoken") if form is not None else None
        if token:
            return token

        # 2. 请求头
        token = request.headers.get("X-CSRFToken") or request.headers.get("X-CSRF-Token")
        if token:
            return token

        # 3. JSON body. Sanic's request.json property eagerly parses the body,
        # so do not touch it for form submissions without a JSON content type.
        content_type = str(request.headers.get("content-type", "")).partition(";")[0].strip().lower()
        if content_type == "application/json" or content_type.endswith("+json"):
            payload = request.json
            token = payload.get("csrfmiddlewaretoken") if isinstance(payload, Mapping) else None
            if token:
                return token

        return None

    SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

    def register_enforcement(self, app: WebApp) -> None:
        """Validate every unsafe-method request, except handlers marked csrf_exempt.

        Without this, protection is opt-in per route: a handler that simply forgets
        `@csrf_protect` is unprotected and nothing says so, and `csrf_exempt` had nothing
        to exempt it from — it set an attribute no code ever read. Enabling enforcement
        inverts that, so forgetting is safe and exempting is deliberate.

        Off by default: turning it on covers routes that are unprotected today, including
        API and webhook endpoints that authenticate by token rather than by session, so a
        deployment has to mark those `csrf_exempt` first.
        """
        from sanic.middleware import MiddlewareLocation

        from oldman.web.security.csrf.decorators import enforce_csrf

        async def validate_unsafe_request(request: Request) -> None:
            """Reject a state-changing request that carries no valid CSRF token."""
            if request.method.upper() in self.SAFE_METHODS:
                return
            handler = getattr(getattr(request, "route", None), "handler", None)
            if getattr(handler, "_csrf_exempt", False):
                return
            enforce_csrf(self, request)

        # Registered after the session middleware, because validation binds the token to
        # the session this request carries.
        app.register_middleware(validate_unsafe_request, MiddlewareLocation.REQUEST.name)

    def validate_token(self, request: Request, token: str) -> tuple[bool, str]:
        """验证 CSRF token"""
        # 1. 同源检查：Origin 优先，Referer 回退（no-referrer 关不掉 Origin）
        if not self._validate_same_origin(request):
            return False, "Cross-origin request blocked"

        # 2. 解密
        payload = self._decrypt_token(token)
        if not payload:
            return False, "Invalid token format"

        # 3. 验证有效期
        expire_time = payload.exp
        if time.time() > expire_time:
            return False, "Token expired"

        # 4. 验证 URL（可选）
        if self.check_url:
            url_hash = self._get_url_hash(request.path)
            token_url_hash = payload.url
            if url_hash != token_url_hash:
                return False, "Token URL mismatch"

        # 5. 验证 session_id
        current_session_id = self._get_session_id(request)
        token_session_id = payload.sid or self.anonymous_id

        if current_session_id != self.anonymous_id and current_session_id != token_session_id:
            return False, "Session ID mismatch"

        return True, "Valid"

    def _require_cipher(self) -> Fernet:
        if self.cipher is None:
            raise RuntimeError("StatelessCSRFManager.init_app() must be called before token operations")
        return self.cipher

    async def before_server_start(self, app):
        await self._setup_jinja2(app)


def csrf_token_for(request: Any) -> str:
    """A page-level token for the installed manager, e.g. the `csrf-token` meta tag; empty without a manager."""
    manager = getattr(getattr(getattr(request, "app", None), "ctx", None), "csrf", None)
    generate = getattr(manager, "generate_token", None)
    return str(generate(request)) if callable(generate) else ""
