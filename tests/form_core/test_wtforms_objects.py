"""A field or validator still imported from wtforms must fail loudly instead of half-working in an Oldman form."""

import unittest

from oldman.web.components.forms._core import Form, StringField


class _UnboundFieldFromWtforms:
    """Stands in for wtforms.fields.core.UnboundField, which carries the same duck-typed marker."""

    _formfield = True
    creation_counter = 0
    name = None

    class field_class:
        __name__ = "StringField"


_UnboundFieldFromWtforms.__module__ = "wtforms.fields.core"


class _DataRequiredFromWtforms:
    def __call__(self, form, field):
        return None


_DataRequiredFromWtforms.__module__ = "wtforms.validators"


class WtformsObjectsTest(unittest.TestCase):
    def test_a_wtforms_field_on_a_form_names_the_framework_import(self):
        class F(Form):
            title = _UnboundFieldFromWtforms()

        with self.assertRaisesRegex(TypeError, r"F\.title .*wtforms.*oldman\.web\.components\.forms"):
            F()

    def test_a_wtforms_validator_names_the_framework_import(self):
        with self.assertRaisesRegex(TypeError, r"wtforms.*oldman\.web\.components\.forms\.validators"):
            StringField(validators=[_DataRequiredFromWtforms()])

    def test_the_core_s_own_fields_and_validators_are_accepted(self):
        from oldman.web.components.forms._core.validators import DataRequired

        class F(Form):
            title = StringField(validators=[DataRequired()])

        self.assertIn("title", F()._fields)
