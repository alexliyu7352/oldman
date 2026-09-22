"""The one rule for a link a message may point at.

The rule itself lives in `oldman.utils.http`: it is not specific to messages, and `oldman.web.api`
needs it too — it cannot import from here, because `oldman.web.messages.actions` already imports
`oldman.web.api.ResponseAction` and that would close a cycle. This module stays as the import path
the messages subsystem has always used.
"""

from __future__ import annotations

from oldman.utils.http import DANGEROUS_SCHEMES, is_safe_link, is_same_site_path

__all__ = ["DANGEROUS_SCHEMES", "is_safe_link", "is_same_site_path"]
