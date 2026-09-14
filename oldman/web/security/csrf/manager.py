import base64
import hashlib
import time
from collections.abc import Mapping
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
    ):
        self.ttl = 3600 if ttl is None else ttl
        self.anonymous_id = anonymous_id
        self.session_name = session_name
        self.check_referer = True if check_referer is None else check_referer
        self.check_url = False if check_url is None else check_url
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
            root_secret = security_config.secret_key
            if root_secret is None:
                raise RuntimeError(
                    "settings.web.security.secret_key is empty; "
                    "run `oldman <service> settings sync`"
                )
            secret = derive_web_security_key(
                root_secret,
                WebSecurityPurpose.CSRF,
            )

        key = hashlib.sha256(secret.encode()).digest()
        fernet_key = base64.urlsafe_b64encode(key)
        self.cipher = Fernet(fernet_key)

        # 挂载到 app.ctx
        app.ctx.csrf = self

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

    def _validate_referer(self, request: Request) -> bool:
        """验证 Referer"""
        if not self.check_referer:
            return True

        referer = request.headers.get("Referer") or request.headers.get("referer")
        if not referer:
            return True  # 宽松模式，允许无 Referer

        # 这里可以添加更多的同源判断逻辑，比如允许子域名等
        # 允许子域名的简单实现
        parsed = urlparse(referer)
        referer_host = parsed.hostname or parsed.netloc.split(":")[0]
        # request.host 可能包含端口，将端口去掉
        request_host = request.host.split(":")[0] if request.host else None
        # 允许完全相同或 referer 为 request 的子域名（例如 referer=app.example.com, request=example.com）
        if not referer_host or not request_host:
            return False
        referer_host = referer_host.lower()
        request_host = request_host.lower()
        if referer_host == request_host:
            return True
        if referer_host.endswith("." + request_host):
            return True
        return False
        return referer_host == request_host

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

    def validate_token(self, request: Request, token: str) -> tuple[bool, str]:
        """验证 CSRF token"""
        # 1. 验证 Referer
        if not self._validate_referer(request):
            return False, "Invalid Referer header"

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
