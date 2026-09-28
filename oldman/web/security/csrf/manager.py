import base64
import hashlib
import re
import secrets
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from cryptography.fernet import Fernet

import oldman.conf as conf
from oldman.serializers import MsgspecModel
from oldman.web.authentication import user_from_session
from oldman.web.request import Request, request_sends_json
from oldman.web.routing import WebApp
from oldman.web.security.csrf.csrf_extension import CsrfExtension
from oldman.web.security.keys import (
    WebSecurityPurpose,
    derive_web_security_key,
)
from oldman.web.template_globals import template_globals


class Payload(MsgspecModel):
    #: What the token is bound to: see StatelessCSRFManager._binding.
    sid: str
    exp: int
    url: str
    #: For a token issued to a signed-in session, also the browser's CSRF cookie (`cookie:<id>`),
    #: which outlives the session: see StatelessCSRFManager.validate_token.
    browser: str | None = None


#: How long the anonymous visitor's id cookie lives, as Django's CSRF cookie: it is only a random
#: id kept by the browser, and a long life keeps a page left open from outliving it.
CSRF_COOKIE_MAX_AGE = 365 * 24 * 3600
#: secrets.token_urlsafe(24): 32 URL-safe characters.
_COOKIE_ID = re.compile(r"[A-Za-z0-9_-]{32}")


class StatelessCSRFManager:
    """
    无状态 CSRF Token 管理器

    Token 组成: {绑定对象, expire_time, url_hash} -> 对称加密
    验证: 同源检查 -> 解密 -> 检查有效期 -> 检查绑定对象

    绑定对象(见 _binding):已登录绑定会话中间件记下的 SID;匿名访客绑定 CSRF cookie 里的随机 id,
    这个 cookie 由会话中间件按会话 cookie 的策略写出(Session.send_cookie)。已登录时签发的 token
    也记下这个 cookie:会话结束(过期、退出、被强制下线)后请求变成匿名,仍能认出是同一个浏览器。
    没经过会话中间件的请求(没开 Session 的服务)没有能写 cookie 的一方,匿名 token 不绑定,只靠同源检查。
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
        cookie_name: str | None = None,
    ):
        self.ttl = 3600 if ttl is None else ttl
        self.cookie_name = "csrf_id" if cookie_name is None else cookie_name
        self._cookie_name_overridden = cookie_name is not None
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
            if not self._cookie_name_overridden:
                self.cookie_name = csrf_config.cookie_name
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
        template_globals(jinja_env).setdefault("csrf_token_for", csrf_token_for)

    def _binding(self, request: Request, *, issue: bool) -> str | None:
        """What a token for this request is bound to; None when an anonymous visitor has no id yet.

        - A signed-in session: the SID the Session middleware captured, which a forged request
          cannot choose; a new login gets a new SID, so another session's tokens do not pass.
          A hand-built request that no Session middleware opened has only its user id.
        - An anonymous visitor on a request the Session middleware opened: the random id in the
          CSRF cookie, as Django does (see _browser_binding).
        - No Session middleware: `anonymous_id`, which binds nothing. Nothing could write the
          cookie, and such a service has no browser login a forged request could ride on.
        """
        from oldman.web.session import Session

        ctx = getattr(request, "ctx", None)
        sessions = getattr(getattr(getattr(request, "app", None), "ctx", None), "session", None)
        sid = sessions.opened_session_id(request) if isinstance(sessions, Session) else None
        user = user_from_session(getattr(ctx, "session", None))
        if user.is_authenticated:
            return f"session:{sid}" if sid is not None else f"user:{user.id}"
        if sid is None or not isinstance(sessions, Session):
            return self.anonymous_id
        return self._browser_binding(request, issue=issue)

    def _browser_binding(self, request: Request, *, issue: bool) -> str | None:
        """The random id in this browser's CSRF cookie, on a request the Session middleware opened.

        With `issue`, a browser without a valid one gets a new id, sent by the Session middleware
        with the session cookie's policy; one per request. None when there is none and `issue` is off.
        """
        from oldman.web.session import Session

        sessions = getattr(getattr(getattr(request, "app", None), "ctx", None), "session", None)
        assert isinstance(sessions, Session)
        cookie_id = request.cookies.get(self.cookie_name)
        if not isinstance(cookie_id, str) or not _COOKIE_ID.fullmatch(cookie_id):
            cookie_id = getattr(getattr(request, "ctx", None), "csrf_cookie_id", None)
            if cookie_id is None:
                if not issue:
                    return None
                cookie_id = secrets.token_urlsafe(24)
                request.ctx.csrf_cookie_id = cookie_id
                sessions.send_cookie(request, self.cookie_name, cookie_id, max_age=CSRF_COOKIE_MAX_AGE)
        return f"cookie:{cookie_id}"

    def _get_url_hash(self, url: str) -> str:
        """生成 URL 哈希"""
        return hashlib.md5(url.encode()).hexdigest()[:16]

    def generate_token(self, request: Request) -> str:
        """
        生成 CSRF token

        Token 结构: {session_id, expire_time, url_hash} -> 加密
        """
        binding = self._binding(request, issue=True)
        assert binding is not None  # issue=True always yields one
        # A signed-in session's token also names the browser, so it is still recognized once the
        # session has ended and the request comes in anonymous.
        browser = self._browser_binding(request, issue=True) if binding.startswith("session:") else None
        # The page now holds a token for one visitor or one session; cache_response must not
        # serve it to anyone else.
        request.ctx.csrf_token_issued = True
        expire_time = int(time.time()) + self.ttl
        url_hash = self._get_url_hash(request.path)

        payload = Payload(
            sid=binding,
            exp=expire_time,
            url=url_hash,
            browser=browser,
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
        if request_sends_json(request):
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

        # 5. 验证绑定对象:已登录比对 SID,匿名比对 CSRF cookie;没有会话中间件时不绑定。
        #    已登录时签发的 token 还记着浏览器的 CSRF cookie:会话结束(过期、退出、被强制下线)后,同一个
        #    浏览器的请求以匿名身份通过,交给视图的登录检查跳登录页,而不是 CSRF 错误。已登录的请求只比对
        #    SID(浏览器绑定是 cookie:,永远不等于 session:),同一浏览器重新登录后旧 token 照样失效。
        current = self._binding(request, issue=False)
        if current != self.anonymous_id and (current is None or current not in (payload.sid, payload.browser)):
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
