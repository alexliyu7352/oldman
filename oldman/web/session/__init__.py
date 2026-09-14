"""Public Web session extension and typed request accessor."""

from __future__ import annotations

import asyncio
from typing import cast

from redis.exceptions import RedisError
from sanic import Request, Sanic
from sanic.middleware import MiddlewareLocation
from sanic.response import BaseHTTPResponse, HTTPResponse, empty

import oldman.conf as conf
from oldman.logging import logger
from oldman.web.session.base import DefaultSessionInterface, SessionData

__all__ = (
    "DefaultSessionInterface",
    "Session",
    "SessionData",
    "get_session_data",
    "session",
)


class Session:
    """Install typed Redis sessions and expose session-management operations."""

    def __init__(
        self,
        app: Sanic | None = None,
        interface: DefaultSessionInterface | type[DefaultSessionInterface] | None = None,
    ) -> None:
        """Optionally install the extension on an existing Sanic application."""
        self.interface: DefaultSessionInterface | None = None
        if app is not None:
            self.init_app(app, interface)

    def init_app(
        self,
        app: Sanic,
        interface: DefaultSessionInterface | type[DefaultSessionInterface] | None = None,
        *,
        session_model: type[SessionData] = SessionData,
    ) -> None:
        """Install middleware and build the default interface from process settings."""
        selected = interface or self._configured_interface(session_model)
        self.interface = selected() if isinstance(selected, type) else selected
        app.ctx.session = self

        async def add_session_to_request(request: Request) -> HTTPResponse | None:
            """Open the request's typed session before handlers run."""
            try:
                await self._require_interface().open(request)
            except asyncio.CancelledError:
                raise
            except RedisError:
                logger.exception("Session Redis read failed")
                return empty(status=503)
            return None

        async def save_session(request: Request, response: BaseHTTPResponse) -> HTTPResponse | None:
            """Persist a changed typed session after the handler returns."""
            try:
                await self._require_interface().save(request, response)
            except asyncio.CancelledError:
                raise
            except RedisError:
                logger.exception("Session Redis write failed")
                return empty(status=503)
            except Exception:
                # Sanic logs and suppresses ordinary response-middleware
                # exceptions, so the extension must replace the successful
                # handler response itself when persistence is invalid.
                logger.exception("Session response persistence failed")
                return empty(status=500)
            return None

        app.register_middleware(add_session_to_request, MiddlewareLocation.REQUEST.name, priority=0)
        app.register_middleware(save_session, MiddlewareLocation.RESPONSE.name)

    @staticmethod
    def _configured_interface(
        session_model: type[SessionData],
    ) -> DefaultSessionInterface:
        """Map the active Session settings into one Redis-lazy interface."""
        config = conf.settings.web.session
        return DefaultSessionInterface(
            expiry=config.expiry,
            prefix=config.prefix,
            user_prefix=config.user_prefix,
            cookie_name=config.cookie_name,
            domain=config.cookie_domain,
            httponly=config.cookie_httponly,
            secure=config.cookie_secure,
            samesite=config.cookie_samesite,
            redis_alias=config.redis_alias,
            session_model=session_model,
        )

    async def login(self, session_data: SessionData) -> str:
        """Create an ordinary login that may coexist with other user sessions."""
        return await self._require_interface().login(session_data)

    async def exclusive_login(self, session_data: SessionData) -> str:
        """Create an exclusive login and revoke the user's other sessions."""
        return await self._require_interface().exclusive_login(session_data)

    async def validate_exclusive_session(self, session_id: str, user_id: int) -> bool:
        """Return whether the SID is the user's only active session."""
        return await self._require_interface().validate_exclusive_session(session_id, user_id)

    async def validate_session(self, session_id: str, user_id: int) -> bool:
        """Return whether an ordinary SID is still active for one user."""
        return await self._require_interface().validate_session(session_id, user_id)

    async def logout(self, session_id: str | None) -> None:
        """Resolve and idempotently delete one stored session."""
        await self._require_interface().logout(session_id)

    async def force_logout_user(self, user_id: int) -> tuple[str, ...]:
        """Delete and return all active session IDs for one user."""
        return await self._require_interface().force_logout_user(user_id)

    async def get_active_session_ids(self, user_id: int) -> tuple[str, ...]:
        """Return all active session IDs for one user."""
        return await self._require_interface().get_active_session_ids(user_id)

    async def is_user_online(self, user_id: int) -> bool:
        """Return whether one user has any active sessions."""
        return await self._require_interface().is_user_online(user_id)

    def update_session_id_to_cookie(
        self,
        response: BaseHTTPResponse,
        new_sid: str,
        session_data: SessionData,
    ) -> None:
        """Write a newly created login SID to a response cookie."""
        self._require_interface().update_session_id_to_cookie(response, new_sid, session_data)

    def get_session_id(self, request: Request) -> str:
        """Return the request SID captured by Session middleware."""
        return self._require_interface().get_session_id(request)

    def _require_interface(self) -> DefaultSessionInterface:
        """Return the installed interface or report incorrect extension use."""
        if self.interface is None:
            raise RuntimeError("Session.init_app() must be called before using the session manager")
        return self.interface

    @staticmethod
    def get_session_manager(request: Request) -> Session:
        """Return the Session extension installed on the request application."""
        manager = getattr(request.app.ctx, "session", None)
        if not isinstance(manager, Session):
            raise RuntimeError("Session is not installed on this application")
        return manager

    @staticmethod
    async def logout_session(request: Request) -> None:
        """Log out the current request and schedule its cookie for deletion."""
        manager = Session.get_session_manager(request)
        await manager._require_interface()._logout_request(request)


def get_session_data[TSessionData: SessionData](request: Request, model: type[TSessionData]) -> TSessionData:
    """Return the request session with a statically precise application type."""
    if not isinstance(model, type) or not issubclass(model, SessionData):
        raise TypeError("model must be a SessionData subclass")
    manager = Session.get_session_manager(request)
    interface = manager._require_interface()
    value = getattr(request.ctx, interface.session_name, None)
    if value is None:
        raise RuntimeError("Session middleware has not initialized this request")
    if not isinstance(value, model):
        raise TypeError(f"Request session is {type(value).__qualname__}, not {model.__qualname__}")
    return cast(TSessionData, value)


# WebApplication installs this process-local extension only when Session is enabled.
session = Session()
