# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms).
# Original path: src/wtforms/__init__.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

"""Form, field, validator and widget core of Oldman's server-rendered forms.

Internal: applications import from ``oldman.web.components.forms``.
"""

from . import validators, widgets
from .fields.choices import RadioField, SelectField, SelectFieldBase, SelectMultipleField
from .fields.core import Field, Flags, Label
from .fields.datetime import DateField, DateTimeField, DateTimeLocalField, MonthField, TimeField, WeekField
from .fields.form import FormField
from .fields.list import FieldList
from .fields.numeric import DecimalField, DecimalRangeField, FloatField, IntegerField, IntegerRangeField
from .fields.simple import (
    BooleanField,
    ColorField,
    EmailField,
    FileField,
    HiddenField,
    MultipleFileField,
    PasswordField,
    SearchField,
    StringField,
    SubmitField,
    TelField,
    TextAreaField,
    URLField,
)
from .form import Form
from .validators import ValidationError

__all__ = [
    "validators",
    "widgets",
    "Form",
    "ValidationError",
    "SelectField",
    "SelectMultipleField",
    "SelectFieldBase",
    "RadioField",
    "Field",
    "Flags",
    "Label",
    "DateTimeField",
    "DateField",
    "TimeField",
    "MonthField",
    "DateTimeLocalField",
    "WeekField",
    "FormField",
    "FieldList",
    "IntegerField",
    "DecimalField",
    "FloatField",
    "IntegerRangeField",
    "DecimalRangeField",
    "BooleanField",
    "TextAreaField",
    "PasswordField",
    "FileField",
    "MultipleFileField",
    "HiddenField",
    "SearchField",
    "SubmitField",
    "StringField",
    "TelField",
    "URLField",
    "EmailField",
    "ColorField",
]
