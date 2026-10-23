# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms), ported from pytest to unittest.
# Original path: tests/validators/test_uuid.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from oldman.web.components.forms._core.validators import UUID, ValidationError
from tests.form_core.support import UpstreamTestCase, raises


class TestUuidValidators(UpstreamTestCase):
    fixture_functions = {}

    def test_valid_uuid_passes(self):
        """
        Valid UUID should pass without raising
        """
        for uuid_val in ["2bc1c94f-0deb-43e9-92a1-4775189ec9f8", "2bc1c94f0deb43e992a14775189ec9f8"]:
            with self.subTest(uuid_val=uuid_val):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                validator = UUID()
                dummy_field.data = uuid_val
                validator(dummy_form, dummy_field)

    def test_bad_uuid_raises(self):
        """
        Bad UUID should raise ValueError
        """
        for uuid_val in [
            "2bc1c94f-deb-43e9-92a1-4775189ec9f8",
            "2bc1c94f-0deb-43e9-92a1-4775189ec9f",
            "gbc1c94f-0deb-43e9-92a1-4775189ec9f8",
            "2bc1c94f 0deb-43e9-92a1-4775189ec9f8",
        ]:
            with self.subTest(uuid_val=uuid_val):
                dummy_form, dummy_field = self.fixtures("dummy_form", "dummy_field")
                validator = UUID()
                dummy_field.data = uuid_val
                with raises(ValidationError):
                    validator(dummy_form, dummy_field)
