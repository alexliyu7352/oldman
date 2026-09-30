"""Building blocks for server maintenance and deployment tools.

Configuration file edits that can run again and again, the operating system's identification, and
systemd units (`oldman.ops.systemd`). systemctl runs through `oldman.processes.run_foreground`, on the
tool's terminal, so `sudo` can ask for a password; what to change, and whether a command needs
`sudo`, is the tool's own business.
See docs/public/zh/developers/ops.md.
"""

from oldman.ops import systemd
from oldman.ops.files import edit_marked_block, os_release, read_directive, set_directive

__all__ = ["edit_marked_block", "os_release", "read_directive", "set_directive", "systemd"]
