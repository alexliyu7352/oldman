# Adapted from WTForms 3.2.2 (tag 3.2.2 of pallets-eco/wtforms).
# Original path: src/wtforms/form.py.
# BSD 3-Clause notice: LICENSES/WTForms-BSD-3-Clause.txt.

# Oldman's form semantics replace WTForms' here, so the framework's Form subclass adds only web
# integration and overrides nothing below: validation is asynchronous and runs the field
# validators, then each `clean_<name>()` and the form's `clean()`; `data` is the raw input and
# `cleaned_data` what validation accepted; `errors` holds every field's complete list, keyed by
# the field name, or by the HTML input name for entries of a list or a nested form;
# `populate_obj()` writes `cleaned_data` only.

import inspect
from collections import OrderedDict
from typing import Any

from oldman.i18n import LazyTranslation

from .meta import DefaultMeta
from .utils import SanicFormData, comes_from_wtforms, unset_value
from .validators import ValidationError

__all__ = ("BaseForm", "Form")

_default_meta = DefaultMeta()


class BaseForm:
    """
    Base Form Class.  Provides core behaviour like field construction,
    validation, and data and error proxying.
    """

    def __init__(self, fields, prefix="", meta=_default_meta):
        """
        :param fields:
            A dict or sequence of 2-tuples of partially-constructed fields.
        :param prefix:
            If provided, all fields will have their name prefixed with the
            value.
        :param meta:
            A meta instance which is used for configuration and customization
            of form behaviors.
        """
        if prefix and prefix[-1] not in "-_;:/.":
            prefix += "-"

        self.meta = meta
        self._prefix = prefix
        self._fields = OrderedDict()
        self.is_bound = False
        self._input_data = {}
        self._cleaned_data = {}
        self._error_message = None
        self._validation_succeeded = False

        if hasattr(fields, "items"):
            fields = fields.items()

        translations = self.meta.get_translations(self)
        if meta.csrf:
            raise TypeError(
                "Oldman forms do not implement WTForms' CSRF protection; protect the view with @csrf_protect() from oldman.web.security.csrf instead."
            )

        for name, unbound_field in fields:
            field_name = unbound_field.name or name
            options = {"name": field_name, "prefix": prefix, "translations": translations}
            field = meta.bind_field(self, unbound_field, options)
            self._fields[name] = field

    def __iter__(self):
        """Iterate form fields in creation order."""
        return iter(self._fields.values())

    def __contains__(self, name):
        """Returns `True` if the named field is a member of this form."""
        return name in self._fields

    def __getitem__(self, name):
        """Dict-style access to this form's fields."""
        return self._fields[name]

    def __setitem__(self, name, value):
        """Bind a field to this form."""
        self._fields[name] = value.bind(form=self, name=name, prefix=self._prefix)

    def __delitem__(self, name):
        """Remove a field from this form."""
        del self._fields[name]

    def process(self, formdata=None, obj=None, data=None, extra_filters=None, **kwargs):
        """Process default and input data with each field.

        :param formdata: Input data coming from the client, usually
            ``request.form`` or equivalent. Should provide a "multi
            dict" interface to get a list of values for a given key.
            A form given formdata is bound: only a bound form validates.
        :param obj: Take existing data from attributes on this object
            matching form field attributes. Only used if ``formdata`` is
            not passed.
        :param data: Take existing data from keys in this dict matching
            form field attributes. ``obj`` takes precedence if it also
            has a matching attribute. Only used if ``formdata`` is not
            passed.
        :param extra_filters: A dict mapping field attribute names to
            lists of extra filter functions to run. Extra filters run
            after filters passed when creating the field. If the form
            has ``filter_<fieldname>``, it is the last extra filter.
        :param kwargs: Merged with ``data`` to allow passing existing
            data as parameters. Overwrites any duplicate keys in
            ``data``. Only used if ``formdata`` is not passed.
        """
        formdata = self.meta.wrap_formdata(self, formdata)
        self.is_bound = formdata is not None
        self._input_data = formdata.to_dict() if isinstance(formdata, SanicFormData) else {}

        if data is not None:
            kwargs = dict(data, **kwargs)

        filters = extra_filters.copy() if extra_filters is not None else {}

        for name, field in self._fields.items():
            field_extra_filters = filters.get(name, [])

            inline_filter = getattr(self, f"filter_{name}", None)
            if inline_filter is not None:
                field_extra_filters.append(inline_filter)

            if obj is not None and hasattr(obj, name):
                data = getattr(obj, name)
            elif name in kwargs:
                data = kwargs[name]
            else:
                data = unset_value

            field.process(formdata, data, extra_filters=field_extra_filters)

    async def is_valid(self) -> bool:
        """Run asynchronous form validation and return whether it passes.

        执行异步表单校验并返回是否通过。
        """
        return await self.validate()

    async def validate(self, extra_validators: dict[str, Any] | None = None) -> bool:
        """Validate the fields, then run each ``clean_<name>()`` and the form's ``clean()``.

        An unbound form (no input) never validates. A field's ``validate`` may return an
        awaitable, as lists and nested forms do; it is awaited. ``clean_<name>()`` runs only for
        a field without errors and its return value is the field's final value; ``clean()`` may
        return a dict merged into ``cleaned_data`` and raises ``ValidationError`` for an error that
        belongs to no single field.

        :param extra_validators:
            If provided, is a dict mapping field names to a sequence of
            callables which will be passed as extra validators to the field's
            `validate` method.
        """
        self._cleaned_data = {}
        self._error_message = None
        self._validation_succeeded = False
        if not self.is_bound:
            for field in self._fields.values():
                field.errors = []
            return False

        await self.prepare_async_fields()
        fields_valid = True
        for name, field in self._fields.items():
            if extra_validators is not None and name in extra_validators:
                extra = extra_validators[name]
            else:
                extra = ()
            valid = field.validate(self, extra)
            if inspect.isawaitable(valid):
                valid = await valid
            if not valid:
                fields_valid = False
        self._set_list_error_message()

        for name, field in self._fields.items():
            # A hidden field only skips rendering as a visible control; its value is data like any
            # other, which is the point of declaring HiddenField("record_id").
            if field.errors or getattr(field, "list_errors", None):
                continue
            self._cleaned_data[name] = field.data
            cleaner = getattr(self, f"clean_{name}", None)
            if cleaner is None:
                continue
            try:
                cleaned_value = await cleaner()
            except ValidationError as exc:
                self.add_error(name, _validation_error_message(exc))
            else:
                self._cleaned_data[name] = cleaned_value
            if field.errors:
                self._cleaned_data.pop(name, None)

        try:
            form_cleaned_data = await self.clean()
        except ValidationError as exc:
            self._error_message = _validation_error_message(exc)
            form_cleaned_data = None
        if isinstance(form_cleaned_data, dict):
            # Merge rather than replace: a subclass returning {"extra": 1} keeps every field's data;
            # a key it returns wins.
            self._cleaned_data.update(form_cleaned_data)
        errors = self.errors
        for name in errors:
            self._cleaned_data.pop(name, None)
        self._validation_succeeded = fields_valid and not errors and self._error_message is None
        return self._validation_succeeded

    async def clean(self) -> dict[str, Any] | None:
        """Run cross-field validation, allowing business subclasses to override it.

        执行跨字段校验，业务子类可覆盖。

        返回 `None` 表示不改动 `cleaned_data`；返回 dict 则把其中的键**合并**进去，
        同名键以返回值为准。跨字段错误用 `raise ValidationError(...)` 报，它会成为表单级
        错误消息。
        """
        return None

    def add_error(self, field_name: str, message: str | LazyTranslation) -> None:
        """Add an error to an actual field, rejecting misspelled or fabricated field names.

        向真实字段添加一条错误，拒绝拼错或伪造的字段名。
        """
        field = self._fields.get(field_name)
        if not field_name or field_name == "__all__" or field is None:
            raise ValueError(f"{field_name!r} is not a real form field")
        if not isinstance(field.errors, list):
            field.errors = list(field.errors)
        field.errors.append(message)

    @property
    def data(self) -> dict[str, Any]:
        """Return the raw input, separately from cleaned_data.

        返回原始输入数据，和 cleaned_data 区分。
        """
        return dict(self._input_data)

    @property
    def cleaned_data(self) -> dict[str, Any]:
        """Return the data validation accepted.

        返回通过验证后的字段数据。
        """
        return dict(self._cleaned_data)

    def populate_obj(self, obj: Any) -> None:
        """Write the cleaned_data fields back to an ordinary object; nested forms fill the objects already there.

        把 cleaned_data 中的字段写回普通对象。
        """
        for field_name, value in self._cleaned_data.items():
            field = self._fields.get(field_name)
            if field is None:
                # A key that clean() added rather than a field.
                setattr(obj, field_name, value)
            else:
                field.write_cleaned_value(obj, field_name, value)

    @property
    def errors(self) -> dict[str, list[str | LazyTranslation]]:
        """Return complete error lists, keyed by field name or, inside lists and nested forms, by input name.

        返回每个真实字段的完整错误列表。
        """
        errors: dict[str, list[str | LazyTranslation]] = {}
        for name, field in self._fields.items():
            for key, messages in field.error_items(name):
                errors[key] = list(messages)
        return errors

    @property
    def error_message(self) -> str | LazyTranslation | None:
        """Return the top-level validation message not attributable to one field.

        返回无法归属到具体字段的顶部校验消息。
        """
        return self._error_message

    async def prepare_async_fields(self) -> None:
        """Prepare fields requiring asynchronous data sources.

        准备需要异步数据源的字段。
        """
        for field in self._fields.values():
            prepare = getattr(field, "prepare_choices", None)
            if prepare is None:
                continue
            await prepare(self)

    def _set_list_error_message(self) -> None:
        """把第一个列表级错误放入表单唯一顶部消息。"""
        for field in self._fields.values():
            list_errors = getattr(field, "list_errors", None)
            if list_errors:
                self._error_message = list_errors[0]
                return


def _validation_error_message(error: ValidationError) -> str | LazyTranslation:
    """保留 ValidationError 中的延迟翻译，其他值规范成文本。"""
    message = error.args[0] if error.args else str(error)
    return message if isinstance(message, (str, LazyTranslation)) else str(message)


class FormMeta(type):
    """
    The metaclass for `Form` and any subclasses of `Form`.

    `FormMeta`'s responsibility is to create the `_unbound_fields` list, which
    is a list of `UnboundField` instances sorted by their order of
    instantiation.  The list is created at the first instantiation of the form.
    If any fields are added/removed from the form, the list is cleared to be
    re-generated on the next instantiation.

    Any properties which begin with an underscore or are not `UnboundField`
    instances are ignored by the metaclass.
    """

    def __init__(cls, name, bases, attrs):
        type.__init__(cls, name, bases, attrs)
        cls._unbound_fields = None
        cls._wtforms_meta = None

    def __call__(cls, *args, **kwargs):
        """
        Construct a new `Form` instance.

        Creates the `_unbound_fields` list and the internal `_wtforms_meta`
        subclass of the class Meta in order to allow a proper inheritance
        hierarchy.
        """
        if cls._unbound_fields is None:
            fields = []
            for name in dir(cls):
                if not name.startswith("_"):
                    unbound_field = getattr(cls, name)
                    if hasattr(unbound_field, "_formfield"):
                        if comes_from_wtforms(unbound_field):
                            raise TypeError(
                                f"{cls.__name__}.{name} is a wtforms {unbound_field.field_class.__name__}; Oldman forms do not use "
                                "WTForms. Import the field from oldman.web.components.forms instead."
                            )
                        fields.append((name, unbound_field))
            # We keep the name as the second element of the sort
            # to ensure a stable sort.
            fields.sort(key=lambda x: (x[1].creation_counter, x[0]))
            cls._unbound_fields = fields

        # Create a subclass of the 'class Meta' using all the ancestors.
        if cls._wtforms_meta is None:
            bases = []
            for mro_class in cls.__mro__:
                if "Meta" in mro_class.__dict__:
                    bases.append(mro_class.Meta)
            cls._wtforms_meta = type("Meta", tuple(bases), {})
        return type.__call__(cls, *args, **kwargs)

    def __setattr__(cls, name, value):
        """
        Add an attribute to the class, clearing `_unbound_fields` if needed.
        """
        if name == "Meta":
            cls._wtforms_meta = None
        elif not name.startswith("_") and hasattr(value, "_formfield"):
            cls._unbound_fields = None
        type.__setattr__(cls, name, value)

    def __delattr__(cls, name):
        """
        Remove an attribute from the class, clearing `_unbound_fields` if
        needed.
        """
        if not name.startswith("_"):
            cls._unbound_fields = None
        type.__delattr__(cls, name)


class Form(BaseForm, metaclass=FormMeta):
    """
    Declarative Form base class. Extends BaseForm's core behaviour allowing
    fields to be defined on Form subclasses as class attributes.

    In addition, form and instance input data are taken at construction time
    and passed to `process()`.
    """

    Meta = DefaultMeta

    def __init__(
        self,
        formdata=None,
        obj=None,
        prefix="",
        data=None,
        meta=None,
        *,
        files=None,
        initial=None,
        **kwargs,
    ):
        """
        :param formdata: Submitted input as a multidict providing ``getlist``.
        :param obj: Take initial values from attributes on this object
            matching form field attributes. Only used if no input is passed.
        :param prefix: If provided, all fields will have their name
            prefixed with the value. This is for distinguishing multiple
            forms on a single page. This only affects the HTML name for
            matching input data, not the Python name for matching
            existing data.
        :param data: Submitted input as a plain mapping (wrapped like Sanic's); pass either this
            or ``formdata``, not both.
        :param meta: A dict of attributes to override on this form's
            :attr:`meta` instance.
        :param files: Uploaded files, looked up before ``data`` for each field.
        :param initial: Initial values by field name, used when the form has no input.
        :param kwargs: Further initial values by field name, overriding ``initial``; also
            ``extra_filters``.
        """
        if data is not None and formdata is not None:
            raise TypeError("Form accepts either data= or formdata=, not both")
        if isinstance(data, SanicFormData):
            bound_formdata = data
        elif data is not None:
            bound_formdata = SanicFormData(data, files)
        elif formdata is not None:
            bound_formdata = formdata
        elif files is not None:
            bound_formdata = SanicFormData(None, files)
        else:
            bound_formdata = None
        self.initial = dict(initial or {})
        self.obj = obj
        self.files = dict(files or {})
        self.prefix = prefix

        meta_obj = self._wtforms_meta()
        if meta is not None and isinstance(meta, dict):
            meta_obj.update_values(meta)
        super().__init__(self._unbound_fields, meta=meta_obj, prefix=prefix)

        for name, field in self._fields.items():
            # Set all the fields to attributes so that they obscure the class
            # attributes with the same names.
            setattr(self, name, field)
        self.process(bound_formdata, obj, data=initial, **kwargs)
        self._set_list_error_message()

    def __setitem__(self, name, value):
        raise TypeError("Fields may not be added to Form instances, only classes.")

    def __delitem__(self, name):
        del self._fields[name]
        setattr(self, name, None)

    def __delattr__(self, name):
        if name in self._fields:
            self.__delitem__(name)
        else:
            # This is done for idempotency, if we have a name which is a field,
            # we want to mask it by setting the value to None.
            unbound_field = getattr(self.__class__, name, None)
            if unbound_field is not None and hasattr(unbound_field, "_formfield"):
                setattr(self, name, None)
            else:
                super().__delattr__(name)

    async def validate(self, extra_validators: dict[str, Any] | None = None) -> bool:
        """Validate the form; a ``validate_<fieldname>`` method runs as the field's last extra validator.

        :param extra_validators: A dict mapping field names to lists of
            extra validator methods to run. Extra validators run after
            validators passed when creating the field. If the form has
            ``validate_<fieldname>``, it is the last extra validator.
        """
        if extra_validators is not None:
            extra = extra_validators.copy()
        else:
            extra = {}

        for name in self._fields:
            inline = getattr(self.__class__, f"validate_{name}", None)
            if inline is not None:
                extra.setdefault(name, []).append(inline)

        return await super().validate(extra)
