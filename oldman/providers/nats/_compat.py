# Copyright 2016-2023 The NATS Authors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""Instance-scoped nats-py 2.15.0 fixes; not a general client replacement.

Derived from Client._close in nats/aio/client.py at upstream tag v2.15.0.
Modified by Oldman: preserve cleanup after a failed final write/drain and report
that error afterward. The rest of the upstream sequence is kept mechanically.
The separate request fix retains native multiplexing and cleans only its own
Future after a failed publish. Installing the close fix does not install it.
Dependency upgrades must review these methods before changing the exact version pin.
Full upstream license: LICENSES/nats-py-Apache-2.0.txt (oldman/licenses in wheels).
"""

import asyncio
import ssl
from secrets import token_hex
from types import MethodType
from typing import Any

from nats import errors
from nats.aio.client import Client
from nats.aio.msg import Msg


async def _request_new_style(
    self: Client,
    subject: str,
    payload: bytes,
    timeout: float = 1,
    headers: dict[str, Any] | None = None,
) -> Msg:
    """Keep 2.15.0's request mux, also releasing its Future when publish fails.

    Derived mechanically from Client._request_new_style at v2.15.0. Only the
    publish/wait cleanup boundary changes; tokens and response dispatch stay native.
    """
    if self.is_draining_pubs:
        raise errors.ConnectionDrainingError
    if not self._resp_sub_prefix:
        await self._init_request_sub()
    assert self._resp_sub_prefix
    token = self._nuid.next()
    token.extend(token_hex(2).encode())
    inbox = self._resp_sub_prefix[:]
    inbox.extend(token)
    future: asyncio.Future[Msg] = asyncio.Future()
    future.add_done_callback(lambda f: self._resp_map.pop(token.decode(), None))
    self._resp_map[token.decode()] = future
    try:
        await self.publish(subject, payload, reply=inbox.decode(), headers=headers)
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:  # noqa: UP041 - Preserve the upstream exception contract.
            raise errors.TimeoutError from None
    finally:
        future.cancel()


def install_request_fix(client: Client) -> None:
    """Install only on Core communication clients, independently of the close fix."""
    client._request_new_style = MethodType(_request_new_style, client)


async def _close(self: Client, status: int, do_cbs: bool = True) -> None:
    """Run the pinned upstream close sequence without aborting on its final flush."""
    if self.is_closed:
        self._status = status
        return
    self._status = Client.CLOSED

    # Kick the flusher once again so that Task breaks and avoid pending futures.
    await self._flush_pending()

    # Avoid cancelling the current task when _close is called from within
    # one of these tasks (e.g. _read_loop via _process_op_err), otherwise
    # the cancellation fires during the asyncio.sleep(0) below and the
    # disconnect/close callbacks are never invoked.
    current = asyncio.current_task()

    if self._reading_task is not None and not self._reading_task.cancelled() and self._reading_task is not current:
        self._reading_task.cancel()

    if (
        self._ping_interval_task is not None
        and not self._ping_interval_task.cancelled()
        and self._ping_interval_task is not current
    ):
        self._ping_interval_task.cancel()

    if self._flusher_task is not None and not self._flusher_task.cancelled() and self._flusher_task is not current:
        self._flusher_task.cancel()

    if self._reconnection_task is not None and not self._reconnection_task.done():
        self._reconnection_task.cancel()

        # Wait for the reconnection task to be done which should be soon.
        try:
            if self._reconnection_task_future is not None and not self._reconnection_task_future.cancelled():
                await asyncio.wait_for(
                    self._reconnection_task_future,
                    self.options["reconnect_time_wait"],
                )
        except (asyncio.CancelledError, asyncio.TimeoutError):  # noqa: UP041 - Keep the upstream close sequence.
            pass

    # Relinquish control to allow background tasks to wrap up.
    await asyncio.sleep(0)

    flush_error: Exception | None = None
    # Upstream's abstract Transport.__bool__ has an incorrect inferred return type.
    if self._current_server is not None and self._transport:  # pyright: ignore[reportGeneralTypeIssues]
        # In case there is any pending data at this point, flush before disconnecting.
        if self._pending_data_size > 0:
            try:
                self._transport.writelines(self._pending[:])
                await self._transport.drain()
            except Exception as exc:
                # Final-flush failure must not skip subscription/transport cleanup.
                flush_error = exc
            finally:
                self._pending = []
                self._pending_data_size = 0

    # Cleanup subscriptions since not reconnecting so no need
    # to replay the subscriptions anymore.
    for sub in self._subs.values():
        # Async subs use join when draining already so just cancel here.
        if sub._wait_for_msgs_task and not sub._wait_for_msgs_task.done():
            sub._wait_for_msgs_task.cancel()
        if sub._message_iterator:
            sub._message_iterator._cancel()
        # Sync subs may have some inflight next_msg calls that could be blocking
        # so cancel them here to unblock them.
        if sub._pending_next_msgs_calls:
            for fut in sub._pending_next_msgs_calls.values():
                fut.cancel()
            sub._pending_next_msgs_calls.clear()
    self._subs.clear()

    if self._transport is not None:
        self._transport.close()
        try:
            await self._transport.wait_closed()
        except Exception as e:
            await self._error_cb(e)

    if do_cbs:
        if self._disconnected_cb is not None:
            await self._disconnected_cb()
        if self._closed_cb is not None:
            await self._closed_cb()

    # Set the client_id and subscription prefix back to None
    self._client_id = None
    self._client_ip = None
    self._resp_sub_prefix = None

    # Report after cleanup so a failing error callback cannot leave subscriptions behind.
    if flush_error is not None:
        await self._error_cb(flush_error)


def install_close_fix(client: Client) -> None:
    """Bind the fix only to this managed client; repeated binding does not stack wrappers."""
    client._close = MethodType(_close, client)


async def _require_tls_info(self: Client, info: dict[str, Any], initial_connection: bool = False) -> None:
    """Refuse a plaintext handshake before native code can send CONNECT credentials.

    nats-py 2.15.0 calls this hook for every initial/reconnect INFO, before its
    standard TLS upgrade. The native server discovery processing stays intact.
    """
    if initial_connection and not info.get("tls_required"):
        # Native reconnect reuses Transport and overwrites its writer on the next
        # attempt. Close this rejected plaintext socket before losing ownership.
        if self._transport is not None:
            self._transport.close()
        raise ssl.SSLError("NATS requires a TLS upgrade before sending CONNECT")
    await Client._process_info(self, info, initial_connection=initial_connection)


def install_tls_requirement(client: Client) -> None:
    """Require standard INFO-then-TLS on this explicitly TLS-configured client only."""
    client._process_info = MethodType(_require_tls_info, client)
