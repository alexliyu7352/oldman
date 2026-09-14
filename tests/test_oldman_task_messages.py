"""Task control message protocol tests."""

from __future__ import annotations

import unittest

import msgspec

from oldman.tasks.messages import MessageType, TaskMessage


class TaskMessageProtocolTest(unittest.TestCase):
    """Keep task-control values stable while exposing them as real strings."""

    def test_message_type_has_string_presentation_and_stable_wire_values(self) -> None:
        self.assertEqual(
            ["task_start", "task_stop", "shutdown"],
            [str(message_type) for message_type in MessageType],
        )
        handlers: dict[str, str] = {MessageType.TASK_START: "start"}
        self.assertEqual("start", handlers["task_start"])

        message = TaskMessage(type=MessageType.TASK_START, task_id="task-1")
        json_payload = msgspec.json.decode(message.to_json_bytes())
        msgpack_payload = msgspec.msgpack.decode(message.to_msgpack())

        self.assertEqual("task_start", json_payload["type"])
        self.assertEqual("task_start", msgpack_payload["type"])
        self.assertEqual(
            MessageType.TASK_START,
            TaskMessage.from_msgpack(message.to_msgpack()).type,
        )


if __name__ == "__main__":
    unittest.main()
