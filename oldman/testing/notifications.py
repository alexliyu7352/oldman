"""在真实浏览器里验证持久化通知的完整链路，供每个宿主项目的门禁复用。

Chrome 走 CDP：登录、topbar 下拉、未读计数、标记已读、删除、通知中心分页、SSE 实时推送；
Firefox 走 BiDi，做同一套壳层与 EventSource 冒烟。两边断言的都是框架自己的通知 UI，所以实现放在框架，
项目只提供自己的 URL（`HostContract`）和额外的页面检查（`extra_firefox_steps`）。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oldman.testing.browser import (
    BrowserResult,
    BrowserVerificationError,
    CDPClient,
    ChromePage,
    WebSocket,
    clear_origin,
    configure_viewport,
    navigate,
)

# 门禁断言的是英文界面文案，所以浏览器语言必须固定：不固定的话页面语言跟着开发机的 LANG 走，
# 在 zh_TW 的机器上同一个门禁会看到繁体界面。切换语言那一步仍然会显式改成 zh-Hans 并验证翻译。
GATE_LANGUAGE = "en-US"

# 宿主自己的页面检查；框架已经检查并清空过 console 错误，这一段里出现的错误由它自己判断。
ExtraFirefoxSteps = Callable[["FirefoxBiDi", str, str, dict[str, Any]], None]


@dataclass(frozen=True, slots=True)
class HostContract:
    """URLs owned by one notification host."""

    name: str
    home_path: str
    login_path: str
    center_path: str


PROBE_SOURCE = r'''
import asyncio
import json
import sys

from oldman import bootstrap_service

bootstrap_service("web", config_file=sys.argv[1])

from oldman.auth import get_user_by_username, user_identity
from oldman.auth.apps import app as auth_app
from oldman.db import db_manager
from oldman.i18n import gettext_lazy as _
from oldman.providers.redis import redis_client
from oldman.web.messages import MessageFormat, MessageLevel
from oldman.web.messages.notifications import (
    NotificationPresentation,
    NotificationState,
    notifications,
)
from oldman.web.session import DefaultSessionInterface
from oldman.conf import settings


async def main():
    action = sys.argv[2]
    username = sys.argv[3]
    home_path = sys.argv[4]
    argument = sys.argv[5] if len(sys.argv) > 5 else ""
    try:
        user = await get_user_by_username(
            username,
            auth_settings=auth_app.settings,
            db_manager=db_manager,
        )
        if user is None:
            raise RuntimeError(f"Unknown gate user: {username}")
        user_id = user_identity(user)

        if action == "seed":
            for index in range(int(argument)):
                await notifications.create(
                    user_id=user_id,
                    title=f"Seed notification {index + 1:02d}",
                    body=f"Seed body {index + 1:02d}",
                    presentation=NotificationPresentation.NONE,
                    href=home_path,
                )
        elif action == "create-text":
            row = await notifications.create(
                user_id=user_id,
                title="<b>Persistent title</b>",
                body="<em>Plain body</em>",
                level=MessageLevel.SUCCESS,
                format=MessageFormat.TEXT,
                presentation=NotificationPresentation.TOAST,
                href=home_path,
                icon="ri-notification-3-line",
            )
            print(json.dumps({"notification_id": row.id}))
            return
        elif action == "create-html":
            row = await notifications.create(
                user_id=user_id,
                title="HTML modal title",
                body="<strong data-gate-html>Trusted HTML body</strong>",
                level=MessageLevel.WARNING,
                format=MessageFormat.HTML,
                presentation=NotificationPresentation.MODAL,
                href=home_path,
            )
            print(json.dumps({"notification_id": row.id}))
            return
        elif action == "push-translated":
            delivered = await notifications.push(
                user_id=user_id,
                title=_("User notifications"),
                body=_("New notifications available"),
                level=MessageLevel.INFO,
                presentation=NotificationPresentation.TOAST,
                href=home_path,
            )
            print(json.dumps({"delivered": delivered}))
            return
        elif action == "expire-session":
            config = settings.web.session
            interface = DefaultSessionInterface(
                expiry=config.expiry,
                prefix=config.prefix,
                user_prefix=config.user_prefix,
                cookie_name=config.cookie_name,
                domain=config.cookie_domain,
                httponly=config.cookie_httponly,
                secure=config.cookie_secure,
                samesite=config.cookie_samesite,
                redis_alias=config.redis_alias,
            )
            sessions = await interface.force_logout_user(user_id)
            print(json.dumps({"expired": len(sessions)}))
            return
        elif action != "counts":
            raise RuntimeError(f"Unknown notification gate action: {action}")

        page = await notifications.list_for_user(
            user_id,
            state=NotificationState.ALL,
            page=1,
            page_size=1,
        )
        print(json.dumps({
            "total": page.total,
            "unread": await notifications.unread_count(user_id),
        }))
    finally:
        await db_manager.close()
        await redis_client.close()


asyncio.run(main())
'''


def run_probe(
    project_root: Path,
    config_file: Path,
    action: str,
    username: str,
    host: HostContract,
    argument: str = "",
) -> dict[str, Any]:
    """Run one public notification operation outside the Web worker."""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            PROBE_SOURCE,
            str(config_file),
            action,
            username,
            host.home_path,
            argument,
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    if completed.returncode != 0:
        raise BrowserVerificationError(
            f"Notification probe {action!r} failed: {completed.stderr[-4000:]}"
        )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    try:
        payload = json.loads(lines[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise BrowserVerificationError(
            f"Notification probe {action!r} returned invalid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise BrowserVerificationError(
            f"Notification probe {action!r} returned a non-object"
        )
    return payload


def _wait_for(
    client: CDPClient,
    expression: str,
    message: str,
    *,
    timeout: float = 10,
) -> Any:
    """Poll one browser predicate while collecting protocol events."""
    deadline = time.monotonic() + timeout
    last_value: Any = None
    while time.monotonic() < deadline:
        last_value = client.evaluate(expression)
        if last_value:
            return last_value
        client.pump(0.1)
    raise BrowserVerificationError(f"{message}; last value: {last_value!r}")


def _event_source_probe_script() -> str:
    """Record every real EventSource created by the product page."""
    return r'''
(() => {
  const NativeEventSource = window.EventSource;
  const records = [];
  Object.defineProperty(window, "__oldmanGateEventSources", {
    configurable: false,
    value: records
  });
  class GateEventSource extends NativeEventSource {
    constructor(url, options) {
      super(url, options);
      const record = { url: String(url), opened: false, closed: false };
      records.push(record);
      this.addEventListener("open", () => { record.opened = true; });
      this.addEventListener("error", () => { record.lastReadyState = this.readyState; });
      this.addEventListener("oldman.session.invalidated", () => { record.invalidated = true; });
      this.__oldmanGateRecord = record;
    }
    close() {
      if (this.__oldmanGateRecord) this.__oldmanGateRecord.closed = true;
      return super.close();
    }
  }
  Object.defineProperties(GateEventSource, {
    CONNECTING: { value: NativeEventSource.CONNECTING },
    OPEN: { value: NativeEventSource.OPEN },
    CLOSED: { value: NativeEventSource.CLOSED }
  });
  window.EventSource = GateEventSource;
})();
'''


def _install_event_source_probe(client: CDPClient) -> None:
    client.command(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": _event_source_probe_script()},
    )


def _login(
    client: CDPClient,
    base_url: str,
    host: HostContract,
    username: str,
    password: str,
) -> None:
    """Submit the real host login form and wait for its authenticated shell."""
    navigate(client, f"{base_url}{host.login_path}")
    submitted = client.evaluate(
        f"""
(() => {{
  const form = document.querySelector('form[action="{host.login_path}"]');
  const username = form?.querySelector('[name="username"]');
  const password = form?.querySelector('[name="password"]');
  if (!(form instanceof HTMLFormElement)
      || !(username instanceof HTMLInputElement)
      || !(password instanceof HTMLInputElement)) return false;
  username.value = {json.dumps(username)};
  password.value = {json.dumps(password)};
  username.dispatchEvent(new Event('input', {{ bubbles: true }}));
  password.dispatchEvent(new Event('input', {{ bubbles: true }}));
  form.requestSubmit();
  return true;
}})()
"""
    )
    if submitted is not True:
        raise BrowserVerificationError("The real login form was not available")
    _wait_for(
        client,
        f"location.pathname === {json.dumps(host.home_path)}",
        "Login did not reach the authenticated host",
        timeout=15,
    )
    _wait_for(
        client,
        "document.querySelector('[data-om-user-notification-topbar]') !== null",
        "Authenticated shell did not contain the persistent notification slot",
    )


def _unread_state(client: CDPClient) -> dict[str, Any]:
    value = client.evaluate(
        r'''
(() => {
  const counters = [...document.querySelectorAll('[data-om-user-notification-count]')];
  const previews = [...document.querySelectorAll('[data-om-user-notification-preview]')];
  return {
    counts: counters.map(item => item.textContent?.trim() ?? ""),
    hidden: counters.map(item => item.hidden),
    previews: previews.length
  };
})()
'''
    )
    return value if isinstance(value, dict) else {}


def _wait_for_unread(client: CDPClient, expected: int) -> dict[str, Any]:
    """Wait for every topbar counter and preview to reflect database state."""
    expression = f"""
(() => {{
  const counters = [...document.querySelectorAll('[data-om-user-notification-count]')];
  if (!counters.length) return false;
  if (!counters.every(item => item.textContent?.trim() === {json.dumps(str(expected))})) return false;
  if (!counters.every(item => item.hidden === {str(expected == 0).lower()})) return false;
  return true;
}})()
"""
    _wait_for(client, expression, f"Topbar unread count did not become {expected}")
    return _unread_state(client)


def _click(client: CDPClient, selector: str) -> None:
    clicked = client.evaluate(
        f"""
(() => {{
  const element = document.querySelector({json.dumps(selector)});
  if (!(element instanceof HTMLElement)) return false;
  element.click();
  return true;
}})()
"""
    )
    if clicked is not True:
        raise BrowserVerificationError(f"Browser control was missing: {selector}")


def _wait_for_sweetalert(client: CDPClient, title: str) -> dict[str, Any]:
    value = _wait_for(
        client,
        f"""
(() => {{
  const popup = document.querySelector('.swal2-popup:not(.swal2-hide)');
  const heading = popup?.querySelector('.swal2-title');
  if (!popup || heading?.textContent?.trim() !== {json.dumps(title)}) return false;
  return {{
    title: heading.textContent.trim(),
    titleHasMarkup: heading.querySelector('*') !== null,
    bodyText: popup.querySelector('.swal2-html-container')?.textContent?.trim() ?? '',
    bodyHasStrong: popup.querySelector('[data-gate-html]') !== null,
    cancelVisible: popup.querySelector('.swal2-cancel') instanceof HTMLElement,
    confirmVisible: popup.querySelector('.swal2-confirm') instanceof HTMLElement
  }};
}})()
""",
        f"SweetAlert title did not become {title!r}",
    )
    if not isinstance(value, dict):
        raise BrowserVerificationError("SweetAlert evidence was not an object")
    return value


def _wait_for_toast(client: CDPClient, title: str) -> dict[str, Any]:
    """Wait for one Toastify toast and report how it rendered its title and body.

    `presentation="toast"` 走 `feedback.toast()`，也就是 Toastify，不是 SweetAlert：标题永远是
    textContent，body 只有 `format="html"` 时才是 innerHTML。这里取的证据和弹窗那条一样，方便
    调用方用同一套断言判断"TEXT 有没有被当成 HTML"。
    """
    value = _wait_for(
        client,
        f"""
(() => {{
  const toast = document.querySelector('.toastify.om-toast');
  const heading = toast?.querySelector('.om-toast-title');
  if (!toast || heading?.textContent?.trim() !== {json.dumps(title)}) return false;
  const body = toast.querySelector('.om-toast-body');
  return {{
    title: heading.textContent.trim(),
    titleHasMarkup: heading.querySelector('*') !== null,
    bodyText: body?.textContent?.trim() ?? '',
    bodyHasStrong: toast.querySelector('[data-gate-html]') !== null,
    tone: Array.from(toast.classList).find(name => name.startsWith('om-toast-')) ?? ''
  }};
}})()
""",
        f"Toast title did not become {title!r}",
    )
    if not isinstance(value, dict):
        raise BrowserVerificationError("Toast evidence was not an object")
    return value


def _close_toast(client: CDPClient) -> None:
    """Dismiss the visible toast, accepting one that already timed out.

    Toast 有自动消失时间，弹窗没有：从看到它到这里之间的若干等待步骤可能超过那个时间，所以
    "已经不在了"也是通过，只有"还在但没有关闭控件"才是缺陷。
    """
    closed = client.evaluate(
        r"""
(() => {
  const toast = document.querySelector('.toastify.om-toast');
  if (!toast) return 'gone';
  const control = toast.querySelector('.toast-close');
  if (!(control instanceof HTMLElement)) return false;
  control.click();
  return 'closed';
})()
"""
    )
    if closed is False:
        raise BrowserVerificationError("Toast had no close control")
    _wait_for(
        client,
        "document.querySelector('.toastify.om-toast') === null",
        "Toast did not close",
    )


def _close_sweetalert(client: CDPClient) -> None:
    closed = client.evaluate(
        r'''
(() => {
  const cancel = document.querySelector('.swal2-popup:not(.swal2-hide) .swal2-cancel');
  const close = document.querySelector('.swal2-popup:not(.swal2-hide) .swal2-close');
  const control = cancel instanceof HTMLElement ? cancel : close;
  if (!(control instanceof HTMLElement)) return false;
  control.click();
  return true;
})()
'''
    )
    if closed is not True:
        raise BrowserVerificationError("SweetAlert had no safe close control")
    _wait_for(
        client,
        "document.querySelector('.swal2-popup') === null",
        "SweetAlert did not close",
    )


def _verify_chrome(
    *,
    base_url: str,
    config_file: Path,
    project_root: Path,
    host: HostContract,
    username: str,
    password: str,
    result: BrowserResult,
) -> dict[str, Any]:
    """Run the complete notification behavior contract in real Chrome."""
    interactions: list[str] = []
    run_probe(project_root, config_file, "seed", username, host, "25")
    with ChromePage(result, accept_language=GATE_LANGUAGE) as client:
        configure_viewport(client, 1440, 1000, mobile=False)
        _install_event_source_probe(client)
        clear_origin(client, base_url)
        _login(client, base_url, host, username, password)

        _wait_for(
            client,
            "document.head.querySelectorAll('meta[name=\"oldman-user-events-url\"]').length === 1",
            "The authenticated page did not expose exactly one user-events meta",
        )
        event_sources = _wait_for(
            client,
            "window.__oldmanGateEventSources?.length === 1 && window.__oldmanGateEventSources[0].opened && window.__oldmanGateEventSources",
            "The page did not open exactly one shared EventSource",
            timeout=15,
        )
        if not isinstance(event_sources, list):
            raise BrowserVerificationError("EventSource evidence was not a list")
        initial = _wait_for_unread(client, 25)
        if initial.get("previews") != 5:
            raise BrowserVerificationError("Topbar did not limit persistent previews to five")
        topbar_contract = client.evaluate(
            r'''
(() => {
  const topbar = document.querySelector('[data-om-user-notification-topbar]');
  return {
    checkbox: topbar?.querySelector('[data-om-user-notification-select]') !== null,
    deleteButton: topbar?.querySelector('[data-om-user-notification-delete-selected]') !== null,
    activityOverlaps: topbar?.closest('[data-om-activity-notifications]') !== null
  };
})()
'''
        )
        if topbar_contract != {
            "checkbox": False,
            "deleteButton": False,
            "activityOverlaps": False,
        }:
            raise BrowserVerificationError(f"Topbar ownership drifted: {topbar_contract}")
        interactions.append("unique shared EventSource and persistent topbar preview")

        _click(client, "[data-om-user-notification-preview]")
        _wait_for(
            client,
            f"location.pathname === {json.dumps(host.home_path)}",
            "Persistent preview did not pass through its open endpoint",
        )
        _wait_for_unread(client, 24)
        interactions.append("GET open marks one persistent preview read")

        navigate(client, f"{base_url}{host.center_path}?state=unread&page=1")
        center = _wait_for(
            client,
            r'''
(() => {
  const center = document.querySelector('[data-om-user-notification-center]');
  if (!center) return false;
  return {
    items: center.querySelectorAll('[data-om-user-notification-center-item]').length,
    selectors: center.querySelectorAll('[data-om-user-notification-select]').length,
    hasRead: center.querySelector('[data-om-user-notification-mark-selected-read]') !== null,
    hasDelete: center.querySelector('[data-om-user-notification-delete-selected]') !== null,
    hasAllRead: center.querySelector('[data-om-user-notification-mark-all-read]') !== null,
    hasNext: [...center.querySelectorAll('[data-om-user-notification-pagination] a')]
      .some(link => link.getAttribute('href')?.includes('page=2'))
  };
})()
''',
            "Notification center was not rendered",
        )
        if (
            not isinstance(center, dict)
            or center.get("items") != 20
            or center.get("selectors") != 20
            or not all(
                center.get(name)
                for name in ("hasRead", "hasDelete", "hasAllRead", "hasNext")
            )
        ):
            raise BrowserVerificationError(f"Notification center contract drifted: {center}")
        client.evaluate(
            r'''
(() => {
  const boxes = document.querySelectorAll('[data-om-user-notification-select]');
  for (const box of [...boxes].slice(0, 2)) {
    box.checked = true;
    box.dispatchEvent(new Event('change', { bubbles: true }));
  }
})()
'''
        )
        _wait_for(
            client,
            "document.querySelector('[data-om-user-notification-selection-count]')?.textContent?.trim() === '2'",
            "Center selection count did not update",
        )
        _click(client, "[data-om-user-notification-mark-selected-read]")
        _wait_for_unread(client, 22)
        _wait_for(
            client,
            "document.querySelectorAll('[data-om-user-notification-center-item]').length === 20",
            "Center did not reload after marking selected rows read",
        )
        interactions.append("server-rendered center pagination and selected read")

        first_box = "[data-om-user-notification-select]"
        _click(client, first_box)
        created = run_probe(
            project_root,
            config_file,
            "create-text",
            username,
            host,
        )
        if not isinstance(created.get("notification_id"), int):
            raise BrowserVerificationError("Persistent create probe returned no integer id")
        text_toast = _wait_for_toast(client, "<b>Persistent title</b>")
        if (
            text_toast.get("titleHasMarkup") is not False
            or text_toast.get("bodyText") != "<em>Plain body</em>"
            or text_toast.get("bodyHasStrong") is not False
        ):
            raise BrowserVerificationError(
                f"TEXT notification was interpreted as HTML: {text_toast}"
            )
        if text_toast.get("tone") != "om-toast-success":
            raise BrowserVerificationError(f"Toast did not carry the notification level: {text_toast}")
        _wait_for_unread(client, 23)
        _wait_for(
            client,
            "!document.querySelector('[data-om-user-notification-refresh-center]')?.hidden",
            "Created event did not expose the center refresh control",
        )
        _wait_for(
            client,
            "document.querySelector('[data-om-user-notification-selection-count]')?.textContent?.trim() === '1'",
            "Created event interrupted the user's current selection",
        )
        _close_toast(client)
        _click(client, "[data-om-user-notification-refresh-center]")
        _wait_for(
            client,
            "document.querySelector('[data-om-user-notification-selection-count]')?.textContent?.trim() === '0'",
            "Explicit center refresh did not reset stale selection",
        )
        interactions.append("created toast, strict text rendering, and deferred center refresh")

        _click(client, "[data-om-user-notification-select]")
        _click(client, "[data-om-user-notification-delete-selected]")
        _wait_for_sweetalert(client, "Delete selected")
        _click(client, ".swal2-popup:not(.swal2-hide) .swal2-confirm")
        _wait_for(
            client,
            "document.querySelector('.swal2-popup') === null",
            "Delete confirmation did not close",
        )
        deleted_counts = run_probe(
            project_root, config_file, "counts", username, host
        )
        if deleted_counts != {"total": 25, "unread": 22}:
            raise BrowserVerificationError(
                f"Selected delete changed the wrong rows: {deleted_counts}"
            )
        _click(client, "[data-om-user-notification-mark-all-read]")
        _wait_for_unread(client, 0)
        interactions.append("selected delete and mark-all-read stay recipient scoped")

        run_probe(project_root, config_file, "create-html", username, host)
        html_alert = _wait_for_sweetalert(client, "HTML modal title")
        if (
            html_alert.get("titleHasMarkup") is not False
            or html_alert.get("bodyHasStrong") is not True
            or html_alert.get("bodyText") != "Trusted HTML body"
        ):
            raise BrowserVerificationError(
                f"Explicit HTML notification did not preserve its body boundary: {html_alert}"
            )
        _wait_for_unread(client, 1)
        _click(client, ".swal2-popup:not(.swal2-hide) .swal2-confirm")
        _wait_for(
            client,
            f"location.pathname === {json.dumps(host.home_path)}",
            "Created notification Open action did not reach its target",
        )
        _wait_for_unread(client, 0)
        interactions.append("HTML modal body and persistent Open action")

        before_push = run_probe(
            project_root, config_file, "counts", username, host
        )
        run_probe(
            project_root,
            config_file,
            "push-translated",
            username,
            host,
        )
        push_toast = _wait_for_toast(client, "User notifications")
        if push_toast.get("titleHasMarkup") is not False:
            raise BrowserVerificationError("Push title was not rendered as text")
        _close_toast(client)
        after_push = run_probe(
            project_root, config_file, "counts", username, host
        )
        if after_push != before_push or _unread_state(client).get("counts", [None])[0] != "0":
            raise BrowserVerificationError(
                f"Temporary push changed persistent state: {before_push} -> {after_push}"
            )
        interactions.append("temporary push stays out of the database and persistent badge")

        activity_before = _unread_state(client)
        activity = client.evaluate(
            r'''
(() => {
  const before = document.querySelectorAll('[data-om-activity-notification-item]').length;
  document.dispatchEvent(new CustomEvent('om:notification:add', { detail: {
    title: '<b>Local activity</b>',
    description: 'Form feedback',
    href: '/',
    icon: 'ri-alert-line',
    tone: 'warning'
  }}));
  const items = [...document.querySelectorAll('[data-om-activity-notification-item]')];
  const item = items.at(-1);
  const select = item?.querySelector('[data-om-activity-notification-select]');
  if (!(item instanceof HTMLElement) || !(select instanceof HTMLInputElement)) return false;
  select.click();
  document.querySelector('[data-om-activity-notification-delete-selected]')?.click();
  return {
    before,
    textWasEscaped: item.textContent.includes('<b>Local activity</b>'),
    persistentControlsInside: item.querySelector('[data-om-user-notification-select]') !== null,
    remaining: document.querySelectorAll('[data-om-activity-notification-item]').length
  };
})()
'''
        )
        if (
            not isinstance(activity, dict)
            or activity.get("textWasEscaped") is not True
            or activity.get("persistentControlsInside") is not False
    or activity.get("remaining") != activity.get("before")
            or _unread_state(client) != activity_before
        ):
            raise BrowserVerificationError(f"Activity crossed boundaries: {activity}")
        interactions.append("Form activity remains local and separate")

        _click(client, "[data-om-language-current]")
        _click(client, "[data-lang='zh-Hans']")
        _wait_for(
            client,
            "document.documentElement.lang.toLowerCase() === 'zh-hans'",
            "Language switch did not reach Simplified Chinese",
            timeout=15,
        )
        _wait_for(
            client,
            "window.__oldmanGateEventSources?.filter(item => item.opened && !item.closed).length === 1",
            "Language switch did not retain exactly one active EventSource",
            timeout=15,
        )
        run_probe(
            project_root,
            config_file,
            "push-translated",
            username,
            host,
        )
        translated_toast = _wait_for_toast(client, "用户通知")
        if translated_toast.get("bodyText") != "有新通知":
            raise BrowserVerificationError(
                f"SSE payload used the wrong connection language: {translated_toast}"
            )
        _close_toast(client)
        interactions.append("language-specific SSE translation and one active connection")

        expired = run_probe(
            project_root,
            config_file,
            "expire-session",
            username,
            host,
        )
        if not isinstance(expired.get("expired"), int) or expired["expired"] < 1:
            raise BrowserVerificationError(f"No browser Session was expired: {expired}")
        session_alert = _wait_for_sweetalert(client, "Session expired")
        if "sign in again" not in str(session_alert.get("bodyText", "")).lower():
            raise BrowserVerificationError(
                f"Session invalidation message was incomplete: {session_alert}"
            )
        _wait_for(
            client,
            "window.__oldmanGateEventSources?.some(item => item.invalidated && item.closed)",
            "Session invalidation did not close the EventSource",
            timeout=10,
        )
        interactions.append("session invalidation closes the shared EventSource")

        return {
            "eventSources": client.evaluate("window.__oldmanGateEventSources"),
            "interactions": interactions,
            "persistentCounts": after_push,
        }


class FirefoxBiDi:
    """Minimal WebDriver BiDi client used only for the compatibility smoke."""

    def __init__(self, port: int) -> None:
        self.websocket = WebSocket(f"ws://127.0.0.1:{port}/session")
        self.next_id = 1
        self.console_errors: list[str] = []

    def close(self) -> None:
        self.websocket.close()

    def command(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 15,
    ) -> dict[str, Any]:
        message_id = self.next_id
        self.next_id += 1
        self.websocket.send_json(
            {"id": message_id, "method": method, "params": params or {}}
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = self.websocket.recv_json(
                timeout=max(0.05, deadline - time.monotonic())
            )
            if message is None:
                continue
            if message.get("type") == "event":
                self._event(message)
                continue
            if message.get("id") != message_id:
                continue
            if message.get("type") == "error":
                raise BrowserVerificationError(
                    f"BiDi command {method} failed: {message}"
                )
            return message
        raise BrowserVerificationError(f"Timed out waiting for BiDi command {method}")

    def _event(self, message: dict[str, Any]) -> None:
        if message.get("method") != "log.entryAdded":
            return
        params = message.get("params", {})
        if params.get("level") == "error":
            self.console_errors.append(str(params.get("text") or "Firefox error"))

    def evaluate(self, context: str, expression: str) -> Any:
        response = self.command(
            "script.evaluate",
            {
                "expression": expression,
                "target": {"context": context},
                "awaitPromise": True,
            },
        )
        result = response.get("result", {}).get("result", {})
        return _bidi_value(result)


def _bidi_value(value: object) -> Any:
    """Decode the small remote-value subset used by the Firefox smoke."""
    if not isinstance(value, dict):
        return None
    value_type = value.get("type")
    raw = value.get("value")
    if value_type in {"string", "number", "boolean", "null", "undefined"}:
        return None if value_type in {"null", "undefined"} else raw
    if value_type == "array" and isinstance(raw, list):
        return [_bidi_value(item) for item in raw]
    if value_type == "object" and isinstance(raw, list):
        decoded: dict[str, Any] = {}
        for entry in raw:
            if isinstance(entry, list) and len(entry) == 2:
                key = entry[0] if isinstance(entry[0], str) else _bidi_value(entry[0])
                if isinstance(key, str):
                    decoded[key] = _bidi_value(entry[1])
        return decoded
    return raw


def _find_firefox() -> str:
    for candidate in (os.environ.get("FIREFOX_BIN"), "firefox"):
        if candidate and (resolved := shutil.which(candidate)):
            return resolved
    raise BrowserVerificationError("No Firefox executable found")


def _verify_firefox(
    *,
    base_url: str,
    host: HostContract,
    username: str,
    password: str,
    extra_steps: ExtraFirefoxSteps | None = None,
) -> dict[str, Any]:
    """Verify login, shared meta, topbar, and EventSource in real Firefox.

    `extra_steps(client, context, base_url, evidence)` 里放宿主项目自己的页面检查；框架只负责
    通知外壳这一段。框架先把自己这段的 console 错误检查完并清空，再交给 `extra_steps`：之后出现的
    错误归宿主判断（它可能要容忍某些错误，比如关闭页面时的 SSE 断连），框架不再回头重判一次。
    """
    port = _free_port()
    profile = tempfile.mkdtemp(prefix="oldman-firefox-notification-")
    # 和 Chrome 一侧同一个理由：固定浏览器语言，页面语言才不跟着开发机的 LANG 走。
    Path(profile, "user.js").write_text(
        f'user_pref("intl.accept_languages", "{GATE_LANGUAGE}, en");\n'
        f'user_pref("intl.locale.requested", "{GATE_LANGUAGE}");\n',
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [
            _find_firefox(),
            "--headless",
            "--new-instance",
            "--no-remote",
            "--profile",
            profile,
            "--remote-debugging-port",
            str(port),
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    client: FirefoxBiDi | None = None
    try:
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise BrowserVerificationError(
                    f"Firefox exited before BiDi was ready: {process.returncode}"
                )
            try:
                client = FirefoxBiDi(port)
                break
            except OSError:
                time.sleep(0.1)
        if client is None:
            raise BrowserVerificationError("Firefox BiDi did not become ready")
        client.command("session.new", {"capabilities": {}})
        created = client.command("browsingContext.create", {"type": "tab"})
        context = created.get("result", {}).get("context")
        if not isinstance(context, str):
            raise BrowserVerificationError("Firefox did not create a browsing context")
        client.command(
            "session.subscribe",
            {"events": ["log.entryAdded"], "contexts": [context]},
        )
        client.command(
            "browsingContext.navigate",
            {
                "context": context,
                "url": f"{base_url}{host.login_path}",
                "wait": "complete",
            },
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if client.evaluate(
                context,
                "document.documentElement.dataset.omReady === 'true'",
            ) is True:
                break
            time.sleep(0.1)
        else:
            raise BrowserVerificationError(
                "Firefox login runtime did not become ready"
            )
        submitted = client.evaluate(
            context,
            f"""
(() => {{
  const form = document.querySelector('form[action="{host.login_path}"]');
  const username = form?.querySelector('[name="username"]');
  const password = form?.querySelector('[name="password"]');
  if (!(form instanceof HTMLFormElement)
      || !(username instanceof HTMLInputElement)
      || !(password instanceof HTMLInputElement)) return false;
  username.value = {json.dumps(username)};
  password.value = {json.dumps(password)};
  form.requestSubmit();
  return true;
}})()
""",
        )
        if submitted is not True:
            raise BrowserVerificationError("Firefox could not submit the login form")
        deadline = time.monotonic() + 20
        evidence: Any = None
        while time.monotonic() < deadline:
            evidence = client.evaluate(
                context,
                f"""
(() => {{
  if (location.pathname !== {json.dumps(host.home_path)}
      || document.documentElement.dataset.omReady !== 'true') return false;
  const topbar = document.querySelector('[data-om-user-notification-topbar]');
  const metas = document.head.querySelectorAll('meta[name="oldman-user-events-url"]');
  if (!topbar || metas.length !== 1) return false;
  return {{
    path: location.pathname,
    meta: metas[0].content,
    topbar: true,
    eventSourceSupported: typeof EventSource === 'function'
  }};
}})()
""",
            )
            if evidence:
                break
            time.sleep(0.2)
        if not isinstance(evidence, dict) or evidence.get("eventSourceSupported") is not True:
            raise BrowserVerificationError(
                f"Firefox notification shell smoke failed: {evidence}"
            )
        if client.console_errors:
            raise BrowserVerificationError(
                f"Firefox console errors: {client.console_errors}"
            )
        # 交接点：框架这段干净了，之后的 console 错误由宿主的 extra_steps 自己判断。
        client.console_errors.clear()
        if extra_steps is not None:
            extra_steps(client, context, base_url, evidence)
        return evidence
    finally:
        if client is not None:
            client.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        shutil.rmtree(profile, ignore_errors=True)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def run_verification(
    *,
    browser: str,
    base_url: str,
    config_file: Path,
    project_root: Path,
    host: HostContract,
    username: str,
    password: str,
    extra_firefox_steps: ExtraFirefoxSteps | None = None,
) -> tuple[int, dict[str, Any]]:
    """Run one selected real browser and return a strict JSON record."""
    result = BrowserResult()
    evidence: dict[str, Any] = {}
    failure = ""
    try:
        if browser == "chrome":
            evidence = _verify_chrome(
                base_url=base_url,
                config_file=config_file,
                project_root=project_root,
                host=host,
                username=username,
                password=password,
                result=result,
            )
        else:
            evidence = _verify_firefox(
                base_url=base_url,
                host=host,
                username=username,
                password=password,
                extra_steps=extra_firefox_steps,
            )
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"

    payload = {
        "badResponses": result.bad_responses,
        "browser": browser,
        "consoleErrors": result.console_errors,
        "evidence": evidence,
        "failure": failure,
        "host": host.name,
        "ok": not failure and result.ok,
        "pageErrors": result.page_errors,
    }
    return (0 if payload["ok"] else 1), payload


def notification_gate_main(
    *,
    host: HostContract,
    project_root: Path,
    argv: list[str] | None = None,
    extra_firefox_steps: ExtraFirefoxSteps | None = None,
) -> int:
    """门禁入口：解析运行参数，跑选定的浏览器，打印一条可机读的结果。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", choices=("chrome", "firefox"), required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args(argv)
    return_code, payload = run_verification(
        browser=args.browser,
        base_url=args.url.rstrip("/"),
        config_file=args.config.resolve(),
        project_root=project_root.resolve(),
        host=host,
        username=args.username,
        password=args.password,
        extra_firefox_steps=extra_firefox_steps,
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return return_code


__all__ = [
    "ExtraFirefoxSteps",
    "FirefoxBiDi",
    "HostContract",
    "notification_gate_main",
    "run_verification",
]
