# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms).
# Original path: src/wtforms/fields/form.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

from typing import Any

from .. import widgets
from ..utils import unset_value
from .core import Field

__all__ = ("FormField",)


class FormField(Field):
    """
    Encapsulate a form as a field in another form.

    :param form_class:
        A subclass of Form that will be encapsulated.
    :param separator:
        A string which will be suffixed to this field's name to create the
        prefix to enclosed fields. The default is fine for most uses.
    """

    widget = widgets.TableWidget()

    def __init__(self, form_class, label=None, validators=None, separator="-", **kwargs):
        super().__init__(label, validators, **kwargs)
        self.form_class = form_class
        self.separator = separator
        self._obj = None
        # Errors about the nested form as a whole, added by the enclosing form (its clean_<name>() or
        # add_error()); the nested fields' own errors stay in the nested form.
        self._own_errors = []
        if self.filters:
            raise TypeError("FormField cannot take filters, as the encapsulated data is not mutable.")
        if validators:
            raise TypeError("FormField does not accept any validators. Instead, define them on the enclosed form.")

    def process(self, formdata, data: Any = unset_value, extra_filters=None):
        if extra_filters:
            raise TypeError("FormField cannot take filters, as the encapsulateddata is not mutable.")

        if data is unset_value:
            try:
                data = self.default()
            except TypeError:
                data = self.default
            self._obj = data

        self.object_data = data

        prefix = self.name + self.separator
        if isinstance(data, dict):
            self.form = self.form_class(formdata=formdata, prefix=prefix, **data)
        else:
            self.form = self.form_class(formdata=formdata, obj=data, prefix=prefix)

    async def validate(self, form, extra_validators=()):  # pyrefly: ignore[bad-override] -- a container field validates its entries asynchronously; the form awaits it
        if extra_validators:
            raise TypeError("FormField does not accept in-line validators, as it gets errors from the enclosed form.")
        self._own_errors = []
        return await self.form.validate()

    def write_cleaned_value(self, obj, name, value):
        # The nested form writes its own cleaned_data into the object already on ``obj``.
        self.populate_obj(obj, name)

    def populate_obj(self, obj, name):
        candidate = getattr(obj, name, None)
        if candidate is None:
            if self._obj is None:
                raise TypeError("populate_obj: cannot find a value to populate from the provided obj or input data/defaults")
            candidate = self._obj

        self.form.populate_obj(candidate)
        setattr(obj, name, candidate)

    def __iter__(self):
        return iter(self.form)

    def __getitem__(self, name):
        return self.form[name]

    def __getattr__(self, name):
        return getattr(self.form, name)

    @property
    def data(self):  # pyrefly: ignore[bad-override] -- computed from the entries, where a plain field stores it
        # What the enclosing form puts in its cleaned_data: the nested form's cleaned_data once it
        # has validated, its field values before that. The nested form's own `data` is its raw input.
        if self.form._validation_succeeded:
            return self.form.cleaned_data
        return {name: field.data for name, field in self.form._fields.items()}

    @property
    def errors(self):
        return self.form.errors

    @errors.setter
    def errors(self, value):
        # The enclosing form resets every field's errors; for a nested form that means its fields'.
        if value:
            raise TypeError("A FormField's errors come from its nested form; add them with add_error()")
        self._own_errors = []
        for field in self.form:
            field.errors = []

    def add_error(self, message):
        """Reject the nested form as a whole: ``message`` is listed under this field's name in ``errors``."""
        # Defined here, not inherited: `errors` is the nested form's dict, and an unknown attribute
        # would be looked up on the nested form.
        self._own_errors.append(message)

    def error_items(self, name):
        """Report each nested field under its HTML input name; the nested form's top message and errors added to this field under ``name``."""
        for sub_name, subfield in self.form._fields.items():
            for key, messages in subfield.error_items(sub_name):
                yield (subfield.name if key == sub_name else key), messages
        whole = [] if self.form.error_message is None else [self.form.error_message]
        whole.extend(self._own_errors)
        if whole:
            yield name, whole
