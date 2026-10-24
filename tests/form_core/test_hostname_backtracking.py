"""URL() must check a hostname label in linear time, with the labels it accepts unchanged."""

import asyncio
import time
import unittest

from oldman.web.components.forms._core import Form, StringField
from oldman.web.components.forms._core.validators import URL, HostnameValidation
from tests.form_core.support import DummyPostData


class HostnameBacktrackingTest(unittest.TestCase):
    def test_a_long_run_of_dashes_is_rejected_quickly(self):
        class F(Form):
            site = StringField(validators=[URL()])

        # Upstream's pattern needs several seconds here, and ~1.6x more for every further dash.
        form = F(DummyPostData(site="http://a" + "-" * 40 + "!.com/"))
        started = time.perf_counter()
        self.assertFalse(asyncio.run(form.validate()))
        self.assertLess(time.perf_counter() - started, 1.0)

    def test_labels_keep_their_verdict(self):
        check = HostnameValidation(require_tld=False)
        for label, accepted in (
            ("example", True),
            ("a-b", True),
            ("a--b", True),
            ("a-b-c-d", True),
            ("xn--bcher-kva", True),
            ("under_score", True),
            ("a-", False),
            ("-a", False),
            ("a-b!", False),
            ("a" + "-" * 40 + "!", False),
            ("", False),
        ):
            with self.subTest(label=label):
                self.assertIs(accepted, bool(check(label)))
