# `oldman.web.components.forms`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

Backend Form component package entry point.

Import with `from oldman.web.components.forms import <name>`.

## `Actions`

class · defined in `oldman.web.components.forms.layouts`

```python
class Actions
```

Declare bottom form-action buttons.

Members:

- `submit: str | LazyTranslation = _SAVE_LABEL`
- `cancel_url: str | None = None`
- `cancel_label: str | LazyTranslation = _CANCEL_LABEL`

## `AjaxAutocompleteField`

class · defined in `oldman.web.components.forms.fields`

```python
class AjaxAutocompleteField(RemoteChoiceValidationMixin, StringField)
```

Convenience remote Autocomplete field submitting IDs while displaying labels.

Constructor:

```python
AjaxAutocompleteField(*args: Any, provider: str, endpoint: str | None=None, route_name: str | None=None, page_size: int=20, dependent_fields: Sequence[str]=(), label_mode: Literal['text', 'html']='text', route_kwargs: dict[str, object] | None=None, **kwargs: Any) -> None
```

Members:

- `def initial_choice(value: Any, label: Any) -> None` — Display initial edit values with the ID in the field and a user-facing label in the input.

## `AjaxAutocompleteWidget`

class · defined in `oldman.web.components.forms.widgets`

```python
class AjaxAutocompleteWidget
```

WTForms widget for remote Autocomplete providers.

Constructor:

```python
AjaxAutocompleteWidget(*, provider: str, endpoint: str | None=None, route_name: str | None=None, page_size: int=20, dependent_fields: Sequence[str]=(), label_mode: Literal['text', 'html']='text', route_kwargs: dict[str, object] | None=None) -> None
```

Members:

- `def bind_attrs(field: Field, form: Any) -> dict[str, Any]` — Generate data attributes required by the browser Autocomplete component.
- `def resolve_endpoint(form: Any) -> str` — Return the remote autocomplete provider endpoint.
- `async def render_async(field: Field, form: Any, **kwargs: Any) -> Markup` — Render an autocomplete control through a template.

## `AjaxSelectField`

class · defined in `oldman.web.components.forms.fields`

```python
class AjaxSelectField(RemoteChoiceValidationMixin, SelectField)
```

Convenience field for remote Select providers.

Constructor:

```python
AjaxSelectField(*args: Any, provider: str, endpoint: str | None=None, route_name: str | None=None, page_size: int=20, dependent_fields: Sequence[str]=(), enhance_choices: bool=False, label_mode: Literal['text', 'html']='text', route_kwargs: dict[str, object] | None=None, coerce: Any=int, **kwargs: Any) -> None
```

Members:

- `def process_formdata(valuelist: list[Any]) -> None` — Accept cleared remote selects as None, leaving requiredness to validators.
- `def initial_choice(value: Any, label: Any) -> None` — Display the current value on the initial edit page.

## `AjaxSelectMultipleField`

class · defined in `oldman.web.components.forms.fields`

```python
class AjaxSelectMultipleField(RemoteChoiceValidationMixin, SelectMultipleField)
```

Convenience field for remote multiple-selection providers.

Constructor:

```python
AjaxSelectMultipleField(*args: Any, provider: str, endpoint: str | None=None, route_name: str | None=None, page_size: int=20, dependent_fields: Sequence[str]=(), enhance_choices: bool=False, tags: bool=False, label_mode: Literal['text', 'html']='text', route_kwargs: dict[str, object] | None=None, coerce: Any=int, **kwargs: Any) -> None
```

Members:

- `def process_formdata(valuelist: list[Any]) -> None` — Accept cleared remote multiple selections, dropping empty values to produce an empty list.
- `def initial_choices(choices: Sequence[tuple[Any, Any]]) -> None` — Display initial multiple selections in input order, skipping empty values.

## `AjaxSelectWidget`

class · defined in `oldman.web.components.forms.widgets`

```python
class AjaxSelectWidget(SelectWidget)
```

WTForms widget for remote Select providers.

Constructor:

```python
AjaxSelectWidget(*, provider: str, endpoint: str | None=None, route_name: str | None=None, page_size: int=20, dependent_fields: Sequence[str]=(), enhance_choices: bool=False, tags: bool=False, label_mode: Literal['text', 'html']='text', route_kwargs: dict[str, object] | None=None) -> None
```

Members:

- `def bind_attrs(field: Field, form: Any) -> dict[str, Any]` — Generate data attributes required by the browser Select component.
- `def resolve_endpoint(form: Any) -> str` — Return the remote provider endpoint, prioritizing an explicit URL over reverse route-name lookup.
- `async def render_async(field: Field, form: Any, **kwargs: Any) -> Markup` — Render a remote select control through a template.

## `BooleanField`

class · defined in `oldman.web.components.forms._core.fields.simple`

```python
class BooleanField(Field)
```

Represents an ``<input type="checkbox">``. Set the ``checked``-status by using the

Constructor:

```python
BooleanField(label=None, validators=None, false_values=None, **kwargs)
```

Members:

- `def process_data(value)`
- `def process_formdata(valuelist)`

## `CheckboxGroupField`

class · defined in `oldman.web.components.forms.fields`

```python
class CheckboxGroupField(SelectMultipleField)
```

Several values from fixed choices, shown as a list of checkboxes instead of a list box.

## `CheckboxWidget`

class · defined in `oldman.web.components.forms.widgets`

```python
class CheckboxWidget(CheckboxInput)
```

Boolean field as a 16px checkbox row: box on the left, label and help text beside it.

## `ColorField`

class · defined in `oldman.web.components.forms._core.fields.simple`

```python
class ColorField(StringField)
```

Represents an ``<input type="color">``.

## `ColorPickerField`

class · defined in `oldman.web.components.forms.fields`

```python
class ColorPickerField(StringField)
```

Store normalized six-digit RGB or eight-digit RGBA hex colors.

Constructor:

```python
ColorPickerField(*args: Any, allow_alpha: bool=True, **kwargs: Any) -> None
```

Members:

- `def process_formdata(valuelist: list[Any]) -> None` — Emit lowercase hex consistently for stable model/browser comparisons.
- `def pre_validate(form: BaseForm) -> None` — Reject non-hex browser or client submissions.

## `ColorPickerWidget`

class · defined in `oldman.web.components.forms.widgets`

```python
class ColorPickerWidget
```

Emit a native color input declaring optional progressive Pickr enhancement.

Constructor:

```python
ColorPickerWidget(*, allow_alpha: bool=True) -> None
```

Members:

- `async def render_async(field: Field, form: Any, **kwargs: Any) -> Markup` — Use the native input without scripts and a hidden field for full HEXA values after mounting.

## `DateField`

class · defined in `oldman.web.components.forms._core.fields.datetime`

```python
class DateField(DateTimeField)
```

Same as :class:`~wtforms.fields.DateTimeField`, except stores a

Constructor:

```python
DateField(label=None, validators=None, format: str | list[str]='%Y-%m-%d', **kwargs)
```

Members:

- `def process_formdata(valuelist)`

## `DateTimeField`

class · defined in `oldman.web.components.forms._core.fields.datetime`

```python
class DateTimeField(Field)
```

A text field which stores a :class:`datetime.datetime` matching one or

Constructor:

```python
DateTimeField(label=None, validators=None, format: str | list[str]='%Y-%m-%d %H:%M:%S', **kwargs)
```

Members:

- `def process_formdata(valuelist)`

## `DateTimeLocalField`

class · defined in `oldman.web.components.forms._core.fields.datetime`

```python
class DateTimeLocalField(DateTimeField)
```

Same as :class:`~wtforms.fields.DateTimeField`, but represents an

Constructor:

```python
DateTimeLocalField(*args, **kwargs)
```

## `DateTimePickerWidget`

class · defined in `oldman.web.components.forms.widgets`

```python
class DateTimePickerWidget
```

An explicitly enabled Oldman flatpickr date/time widget.

Constructor:

```python
DateTimePickerWidget(*, date_format: str='Y-m-d\\TH:i', enable_time: bool=True, provider: str='flatpickr', input_type: str='text', extra_attrs: dict[str, Any] | None=None) -> None
```

Members:

- `def bind_attrs(field: Field, form: Any) -> dict[str, Any]` — Generate data attributes required by the browser DateTimePicker component.

## `DecimalField`

class · defined in `oldman.web.components.forms._core.fields.numeric`

```python
class DecimalField(LocaleAwareNumberField)
```

A text field which displays and coerces data of the `decimal.Decimal` type.

Constructor:

```python
DecimalField(label=None, validators=None, places: Any=unset_value, rounding: Any=None, **kwargs)
```

Members:

- `def process_formdata(valuelist)`

## `DecimalRangeField`

class · defined in `oldman.web.components.forms._core.fields.numeric`

```python
class DecimalRangeField(DecimalField)
```

Represents an ``<input type="range">``.

## `EmailField`

class · defined in `oldman.web.components.forms.fields`

```python
class EmailField(HTML5EmailField)
```

An `<input type="email">` that stores the address normalized (stripped, lowercased) and checks its shape.

Constructor:

```python
EmailField(*args: Any, **kwargs: Any) -> None
```

Members:

- `def process_formdata(valuelist: list[Any]) -> None`
- `def pre_validate(form: BaseForm) -> None` — Reject a malformed or oversized address; emptiness is left to DataRequired/Optional.

## `Field`

class · defined in `oldman.web.components.forms._core.fields.core`

```python
class Field
```

Field base class

Constructor:

```python
Field(label: Any=None, validators: Any=None, filters: Any=(), description: Any='', id: str | None=None, default: Any=None, widget: Any=None, render_kw: Any=None, name: Any=None, _form: Any=None, _prefix: str='', _translations: Any=None, _meta: Any=None)
```

Members:

- `errors: Any = ()`
- `process_errors: Any = ()`
- `data: Any`
- `widget: Any = None`
- `classmethod def check_validators(validators)`
- `def gettext(string)` — Get a translation for the given message.
- `def ngettext(singular, plural, n)` — Get a translation for a message which can be pluralized.
- `def validate(form, extra_validators=())` — Validates the field and returns True or False. `self.errors` will
- `def pre_validate(form)` — Override if you need field-level validation. Runs before any other
- `def post_validate(form, validation_stopped)` — Override if you need to run any field-level validation tasks after
- `def process(formdata, data: Any=unset_value, extra_filters=None)` — Process incoming data, calling process_data, process_formdata as needed,
- `def process_data(value)` — Process the Python data applied to this field and store the result.
- `def process_formdata(valuelist)` — Process data received over the wire from a form.
- `def add_error(message)` — Add ``message`` to this field's errors, as the form's ``add_error()`` does.
- `def error_items(name)` — The (key, messages) pairs this field adds to its form's ``errors``: its own list, under ``name``.
- `def write_cleaned_value(obj, name, value)` — Write this field's cleaned value onto ``obj``, as the form's ``populate_obj()`` does.
- `def populate_obj(obj, name)` — Populates `obj.<name>` with the field's data.

## `FieldGroup`

class · defined in `oldman.web.components.forms.layouts`

```python
class FieldGroup
```

Declare a titled field group with an optional description, rendered as a fieldset within the same form.

Constructor:

```python
FieldGroup(title: str | LazyTranslation, *items: object, description: str | LazyTranslation='') -> None
```

Members:

- `title: str | LazyTranslation`
- `items: tuple[object, ...]`
- `description: str | LazyTranslation = ''`

## `FieldLayout`

class · defined in `oldman.web.components.forms.layouts`

```python
class FieldLayout
```

Form field-layout definitions.

Members:

- `name: str`
- `width: str = 'md:col-span-12'`
- `advanced: bool = False`
- `range_end: str | None = None`
- `range_label: str | LazyTranslation | None = None`

## `FieldList`

class · defined in `oldman.web.components.forms._core.fields.list`

```python
class FieldList(Field)
```

Encapsulate an ordered list of multiple instances of the same field type,

Constructor:

```python
FieldList(unbound_field, label=None, validators=None, min_entries=0, max_entries=None, separator='-', default=(), **kwargs)
```

Members:

- `def process(formdata, data: Any=unset_value, extra_filters=None)`
- `async def validate(form, extra_validators=())` — Validate this FieldList.
- `def error_items(name)` — Report each entry under its HTML input name, and the list's own validators' messages under ``name``.
- `def write_cleaned_value(obj, name, value)`
- `def populate_obj(obj, name)`
- `def append_entry(data: Any=unset_value)` — Create a new entry with optional default data.
- `def pop_entry()` — Removes the last entry from the list and returns it.
- `property data`

## `FieldRenderer`

class · defined in `oldman.web.components.forms.renderers`

```python
class FieldRenderer
```

Unthemed field renderer managing field context and widget attributes.

Constructor:

```python
FieldRenderer(form: Any) -> None
```

Members:

- `async def render(field: Any) -> Markup` — Render one field's HTML.
- `async def render_radio_field(field: RadioField) -> Markup` — Render RadioField as a normally laid-out native radio group.
- `async def render_checkbox_group_field(field: CheckboxGroupField) -> Markup` — Render a CheckboxGroupField as native checkboxes; grouped choices get a heading per group.
- `async def render_json_list_field(field: JSONListField) -> Markup` — Render scalar-list rows and an empty template for browser cloning.
- `async def render_password_field(field: PasswordField) -> Markup` — Render a password field with shared visibility controls.
- `def password_toggle_enabled(field: PasswordField) -> bool` — Return whether the field enables shared password-visibility controls.
- `def boolean_presentation(field: BooleanField) -> str` — Return boolean presentation, prioritizing widget settings over renderer defaults.
- `async def render_boolean_field(field: BooleanField) -> Markup` — Render booleans as checkbox rows, switch rows, or switch cards.
- `async def render_widget(field: Field, **extra_attrs: Any) -> Markup` — Render field widgets, using replaceable templates for remote components.
- `def template_name(name: str) -> str` — Return the current field renderer's template path.
- `async def render_range_field(start: Field, end: Field, *, label: object=None) -> Markup` — Render a grid range with a label defaulting to the start field's label and two adjacent controls.
- `async def render_filter_search(field: Field) -> Markup` — Render an inline-filter search input without a prefix, filling remaining width.
- `async def render_filter_control(field: Field) -> Markup` — Render an inline-filter control with its label as a left prefix.
- `async def render_filter_range(start: Field, end: Field, *, label: object=None) -> Markup` — Render an inline-filter range with one prefix defaulting to the start label and two inputs.
- `async def render_help(field: Field) -> Markup` — Render field help text.
- `async def render_field_errors(field: Field, *, error_id: str | None=None) -> Markup` — Render field-level errors.
- `def widget_attrs(field: Field) -> dict[str, Any]` — Return control attributes according to field type.
- `def widget_base_class(field: Field) -> str` — Return default unthemed control classes.
- `def invalid_class() -> str` — Return field-error state classes.

## `FileExtension`

class · defined in `oldman.web.components.forms.fields`

```python
class FileExtension
```

Restrict the final extension in uploaded filenames.

Constructor:

```python
FileExtension(extensions: Collection[str], message: str | LazyTranslation | None=None) -> None
```

## `FileField`

class · defined in `oldman.web.components.forms._core.fields.simple`

```python
class FileField(Field)
```

Renders a file upload field.

## `FileSize`

class · defined in `oldman.web.components.forms.fields`

```python
class FileSize
```

Limit upload size in bytes.

Constructor:

```python
FileSize(max_bytes: int, message: str | LazyTranslation | None=None) -> None
```

## `Flags`

class · defined in `oldman.web.components.forms._core.fields.core`

```python
class Flags
```

Holds a set of flags as attributes.

## `FloatField`

class · defined in `oldman.web.components.forms._core.fields.numeric`

```python
class FloatField(Field)
```

A text field, except all input is coerced to an float.  Erroneous input

Constructor:

```python
FloatField(label=None, validators=None, **kwargs)
```

Members:

- `def process_formdata(valuelist)`

## `Form`

class · defined in `oldman.web.components.forms.base`

```python
class Form(CoreForm)
```

Base class for Oldman server-rendered forms.

Constructor:

```python
Form(*args: Any, request: Any=None, data: Mapping[str, Any] | SanicFormData | None=None, files: Mapping[str, Any] | None=None, obj: Any=None, session: Any=None, initial: dict[str, Any] | None=None, prefix: str='', csrf_token: str='', select_secret_key: str='', **kwargs: Any) -> None
```

Members:

- `field_layout: tuple[FieldLayout | str, ...] = ()`
- `layout: FormLayout | None = None`
- `def configure_remote_select_fields() -> None` — Configure field-validation boundaries for remote Select widgets.
- `classmethod def from_request(request, *, obj: Any=None, session: Any=None, initial: dict[str, Any] | None=None, prefix: str='', csrf_token: str='', select_secret_key: str='', **kwargs: Any) -> Self` — Create a form instance from a Sanic request.
- `classmethod def from_query(request, *, obj: Any=None, session: Any=None, initial: dict[str, Any] | None=None, prefix: str='', **kwargs: Any) -> Form` — Create a GET filter form from Sanic query parameters.
- `async def render(*, action: str='', method: str='post', form_mode: str='html', target: str | None=None, swap: str | None=None, submit_label: str | LazyTranslation=_SAVE_LABEL, cancel_url: str | None=None, cancel_label: str | LazyTranslation=_CANCEL_LABEL, extra_buttons: Markup | str='', form_class: str='', component_name: str | None='form', validate: bool=False, feedback_target: str | None=None) -> Markup` — Render complete form HTML.
- `def get_renderer() -> FormRenderer` — Return the current form renderer instance.
- `def get_field_renderer() -> FieldRenderer` — Return the current form's field renderer instance.
- `async def render_field(field: Field | str) -> Markup` — Render a field's label, control, and errors.
- `async def render_actions(*, submit_label: str | LazyTranslation=_SAVE_LABEL, cancel_url: str | None=None, cancel_label: str | LazyTranslation=_CANCEL_LABEL, extra_buttons: Markup | str='') -> Markup` — Render the bottom action area for partial template use.
- `def visible_fields() -> list[Field]` — Return visible fields.
- `def hidden_fields() -> list[Field]` — Return hidden fields.
- `def iter_layout() -> Iterable[FieldLayout]` — Return form-layout fields.
- `def get_layout_steps() -> tuple[FormStep, ...]` — Return multi-step field groups declared in the layout.
- `def iter_step_layout(step: FormStep) -> Iterable[FieldLayout]` — Expand field layouts within one step.
- `def iter_layout_segments() -> Iterable[tuple[FieldGroup | None, tuple[FieldLayout, ...]]]` — Split the top-level layout into consecutive ungrouped-field sections and individual FieldGroup sections.
- `def iter_step_segments(step: FormStep) -> Iterable[tuple[FieldGroup | None, tuple[FieldLayout, ...]]]` — Split one step's layout into grouped sections.
- `def get_layout_actions() -> Actions | None` — Return actions configuration declared in the layout.
- `def to_api_response() -> DefaultApiFormResponse` — Convert current form state to a common API response object.

## `FormField`

class · defined in `oldman.web.components.forms._core.fields.form`

```python
class FormField(Field)
```

Encapsulate a form as a field in another form.

Constructor:

```python
FormField(form_class, label=None, validators=None, separator='-', **kwargs)
```

Members:

- `def process(formdata, data: Any=unset_value, extra_filters=None)`
- `async def validate(form, extra_validators=())`
- `def write_cleaned_value(obj, name, value)`
- `def populate_obj(obj, name)`
- `property data`
- `def errors(value)`
- `def add_error(message)` — Reject the nested form as a whole: ``message`` is listed under this field's name in ``errors``.
- `def error_items(name)` — Report each nested field under its HTML input name; the nested form's top message and errors added to this field under ``name``.

## `FormLayout`

class · defined in `oldman.web.components.forms.layouts`

```python
class FormLayout
```

Declarative form layout.

Constructor:

```python
FormLayout(*items: object) -> None
```

Members:

- `items: tuple[object, ...]`

## `FormRenderer`

class · defined in `oldman.web.components.forms.renderers`

```python
class FormRenderer
```

Unthemed whole-form renderer.

Constructor:

```python
FormRenderer(form: Any) -> None
```

Members:

- `async def render(**kwargs: Any) -> Markup` — Render complete form HTML.
- `async def render_table_filter(**kwargs: Any) -> Markup` — Render HTML specifically for TableFilterForm.
- `async def render_inline_filter(attrs: dict[str, Any], *, submit_label: object, extra_buttons: Markup | str) -> Markup` — Render an inline filter bar with search, prefixed controls, ranges, a More filters panel, and right-aligned actions.
- `async def render_with_attrs(attrs: dict[str, Any], *, method: str, submit_label: object, cancel_url: str | None, cancel_label: object, extra_buttons: Markup | str, validator: bool=False) -> Markup` — Render the complete form template with specified form attributes.
- `def template_name(name: str) -> str` — Return the current renderer's template path.
- `async def render_fields() -> Markup` — Render form fields according to their layout.
- `async def render_status() -> Markup` — Render the submission-status anchor used by the browser Form component.
- `async def render_actions(*, submit_label: object, cancel_url: str | None, cancel_label: object, extra_buttons: Markup | str) -> Markup` — Render bottom form buttons.
- `async def render_message() -> Markup` — Render the single top-level form-validation message area.

## `FormStep`

class · defined in `oldman.web.components.forms.layouts`

```python
class FormStep
```

Declare a field group in a multi-step form.

Constructor:

```python
FormStep(title: str | LazyTranslation, *items: object, description: str | LazyTranslation='') -> None
```

Members:

- `title: str | LazyTranslation`
- `items: tuple[object, ...]`
- `description: str | LazyTranslation = ''`

## `HiddenField`

class · defined in `oldman.web.components.forms._core.fields.simple`

```python
class HiddenField(StringField)
```

HiddenField is a convenience for a StringField with a HiddenInput widget.

## `InputSpinnerWidget`

class · defined in `oldman.web.components.forms.widgets`

```python
class InputSpinnerWidget
```

Emit progressively enhanced increment/decrement controls for WTForms numeric fields.

Members:

- `async def render_async(field: Field, form: Any, **kwargs: Any) -> Markup` — Retain a native number input and declare an outer InputSpinner component.

## `IntegerField`

class · defined in `oldman.web.components.forms._core.fields.numeric`

```python
class IntegerField(Field)
```

A text field, except all input is coerced to an integer.  Erroneous input

Constructor:

```python
IntegerField(label=None, validators=None, **kwargs)
```

Members:

- `def process_data(value)`
- `def process_formdata(valuelist)`

## `IntegerRangeField`

class · defined in `oldman.web.components.forms._core.fields.numeric`

```python
class IntegerRangeField(IntegerField)
```

Represents an ``<input type="range">``.

## `JSONListField`

class · defined in `oldman.web.components.forms.fields`

```python
class JSONListField(FieldList)
```

Bind a JSON array in Text to a WTForms scalar-field list.

Constructor:

```python
JSONListField(unbound_field: Any, *args: Any, **kwargs: Any) -> None
```

Members:

- `def process(formdata: Any, data: Any=unset_value, extra_filters: Any=None) -> None` — Decode model values and check submitted indexes/counts before WTForms truncation.
- `async def validate(form: BaseForm, extra_validators: Any=()) -> bool` — Preserve child-field errors and pass list-level failures to the top form message.
- `def template_entry(index: str='__index__') -> Any` — Create an empty child field outside entries for HTML-template cloning.
- `staticmethod def encode(value: list[Any]) -> str` — Return stable compact JSON for database Text storage.

## `Label`

class · defined in `oldman.web.components.forms._core.fields.core`

```python
class Label
```

An HTML form label.

Constructor:

```python
Label(field_id, text)
```

## `ModelChoice`

class · defined in `oldman.web.components.forms.choices`

```python
class ModelChoice
```

Local model-choice configuration.

Members:

- `model: type[Any]`
- `value_field: str = 'id'`
- `label_field: str = 'name'`
- `order_by: Sequence[str] = dataclass_field(default_factory=tuple)`
- `max_choices: int = 200`
- `empty_label: str | None = None`
- `async def get_queryset(request: Any, session: Any) -> Sequence[Any]` — Return local candidate objects visible to the current request/session.
- `def value_from_instance(obj: Any) -> Any` — Read the submitted value from a candidate object.
- `def label_from_instance(obj: Any) -> str` — Read display text from a candidate object.

## `ModelChoiceField`

class · defined in `oldman.web.components.forms.fields`

```python
class ModelChoiceField(SelectField)
```

Local model foreign-key choice field.

Constructor:

```python
ModelChoiceField(*args: Any, model_choice: ModelChoice, coerce: Any=int, **kwargs: Any) -> None
```

Members:

- `async def prepare_choices(form: Any) -> None` — Load local candidates into WTForms choices.
- `def pre_validate(form: BaseForm) -> None` — Require submitted values to belong to currently visible choices.

## `ModelForm`

class · defined in `oldman.web.components.forms.models`

```python
class ModelForm(Form)
```

Base class for unthemed Oldman model forms.

Constructor:

```python
ModelForm(*args: Any, instance: Any=None, **kwargs: Any) -> None
```

Members:

- `classmethod def from_request(request, *, instance: Any=None, session: Any=None, initial: dict[str, Any] | None=None, prefix: str='', csrf_token: str='', select_secret_key: str='', **kwargs: Any) -> Self` — Create a model form from a Sanic request.
- `classmethod def from_query(request, *, instance: Any=None, session: Any=None, initial: dict[str, Any] | None=None, prefix: str='', **kwargs: Any) -> Self` — Create a model filter form from Sanic query parameters.
- `classmethod def get_model() -> type[Any]` — Return the model class declared by Meta.model.
- `classmethod def get_model_fields() -> tuple[str, ...]` — Return editable fields declared by Meta.fields.
- `classmethod def inject_model_fields() -> None` — Map SQLAlchemy model fields to WTForms fields.
- `async def validate(extra_validators: dict[str, Any] | None=None) -> bool` — Validate ordinary fields and require new uploads for non-nullable file columns while allowing retained files on edit.
- `def populate_obj(obj: Any) -> None` — Write permitted cleaned_data fields back to the model instance.
- `async def save(*, commit: bool=False, session: Any=None) -> Any` — Save the model form and return its instance, leaving transaction commit to the caller.
- `async def before_save(instance: Any) -> None` — Maintain derived fields after form values and uploaded filenames are assigned but before database writes.

## `MonthField`

class · defined in `oldman.web.components.forms._core.fields.datetime`

```python
class MonthField(DateField)
```

Same as :class:`~wtforms.fields.DateField`, except represents a month,

Constructor:

```python
MonthField(label=None, validators=None, format: str | list[str]='%Y-%m', **kwargs)
```

## `MultipleFileField`

class · defined in `oldman.web.components.forms._core.fields.simple`

```python
class MultipleFileField(FileField)
```

A :class:`FileField` that allows choosing multiple files.

Members:

- `def process_formdata(valuelist)`

## `PasswordField`

class · defined in `oldman.web.components.forms._core.fields.simple`

```python
class PasswordField(StringField)
```

A StringField, except renders an ``<input type="password">``.

## `RadioField`

class · defined in `oldman.web.components.forms._core.fields.choices`

```python
class RadioField(SelectField)
```

Like a SelectField, except displays a list of radio buttons.

## `RichTextField`

class · defined in `oldman.web.components.forms.fields`

```python
class RichTextField(TextAreaField)
```

Submit HTML through a native textarea with explicit optional server-side sanitization.

Constructor:

```python
RichTextField(*args: Any, sanitizer: Callable[[str], str] | None=None, **kwargs: Any) -> None
```

Members:

- `def process_formdata(valuelist: list[Any]) -> None` — Sanitize submissions only when a sanitizer is configured, without guessing business trust policies.

## `RichTextWidget`

class · defined in `oldman.web.components.forms.widgets`

```python
class RichTextWidget
```

Emit a native textarea supporting progressive Quill enhancement.

Members:

- `async def render_async(field: Field, form: Any, **kwargs: Any) -> Markup` — Retain textarea as the actual submission control and provide an editor mount point.

## `Row`

class · defined in `oldman.web.components.forms.layouts`

```python
class Row
```

Declare a row and default grid widths, combining exactly two fields into a range control with as_range=True.

Constructor:

```python
Row(*fields: str, width: str='md:col-span-12', as_range: bool=False, advanced: bool=False, label: str | LazyTranslation | None=None) -> None
```

Members:

- `fields: tuple[str, ...]`
- `width: str = 'md:col-span-12'`
- `as_range: bool = False`
- `advanced: bool = False`
- `label: str | LazyTranslation | None = None`

## `SanicFormData`

class · defined in `oldman.web.components.forms._core.utils`

```python
class SanicFormData
```

Adapt Sanic form data to the form core's getlist protocol.

Constructor:

```python
SanicFormData(data: Mapping[str, Any] | None, files: Mapping[str, Any] | None=None)
```

Members:

- `def getlist(key: str) -> list[Any]` — Return the field's list of values.
- `def get(key: str, default: Any=None) -> Any` — Return the first field value from ordinary mappings or Sanic parameter objects.
- `def items()` — Return original field items for debugging and tests.
- `def to_dict() -> dict[str, Any]` — Convert raw input to an ordinary dict while preserving multi-value lists.

## `SearchField`

class · defined in `oldman.web.components.forms._core.fields.simple`

```python
class SearchField(StringField)
```

Represents an ``<input type="search">``.

## `SelectField`

class · defined in `oldman.web.components.forms._core.fields.choices`

```python
class SelectField(SelectFieldBase)
```

Constructor:

```python
SelectField(label=None, validators=None, coerce: Any=str, choices: Any=None, validate_choice=True, **kwargs)
```

Members:

- `choices: Any`
- `def iter_choices()`
- `def has_groups()`
- `def iter_groups()`
- `def process_data(value)`
- `def process_formdata(valuelist)`
- `def pre_validate(form)`

## `SelectFieldBase`

class · defined in `oldman.web.components.forms._core.fields.choices`

```python
class SelectFieldBase(Field)
```

Constructor:

```python
SelectFieldBase(label=None, validators=None, option_widget=None, **kwargs)
```

Members:

- `option_widget: Any = widgets.Option()`
- `def iter_choices()` — Provides data for choice widget rendering. Must return a sequence or
- `def has_groups() -> bool`
- `def iter_groups()`

## `SelectMultipleField`

class · defined in `oldman.web.components.forms._core.fields.choices`

```python
class SelectMultipleField(SelectField)
```

No different from a normal select field, except this one can take (and

Members:

- `def process_data(value)`
- `def process_formdata(valuelist)`
- `def pre_validate(form)`

## `SlugField`

class · defined in `oldman.web.components.forms.fields`

```python
class SlugField(StringField)
```

Normalize submissions as URL slugs, optionally filling empty values from another form field.

Constructor:

```python
SlugField(*args: Any, source_field: str | None=None, allow_unicode: bool=False, **kwargs: Any) -> None
```

Members:

- `def process_formdata(valuelist: list[Any]) -> None` — Normalize only submitted values without rewriting model initial values used for editing.
- `def validate(form: BaseForm, extra_validators: Any=()) -> bool` — Generate empty values from a source field while preserving the meaning of user-supplied values.

## `StringField`

class · defined in `oldman.web.components.forms._core.fields.simple`

```python
class StringField(Field)
```

This field is the base for most of the more complicated fields, and

Members:

- `def process_formdata(valuelist)`

## `SubmitField`

class · defined in `oldman.web.components.forms._core.fields.simple`

```python
class SubmitField(BooleanField)
```

Represents an ``<input type="submit">``.  This allows checking if a given

## `SwitchCardWidget`

class · defined in `oldman.web.components.forms.widgets`

```python
class SwitchCardWidget(SwitchWidget)
```

Boolean field as a bordered card: label and help text on the left, switch on the right.

## `SwitchWidget`

class · defined in `oldman.web.components.forms.widgets`

```python
class SwitchWidget(CheckboxInput)
```

Boolean field as an inline 18×32 switch row with the label and help text beside it.

## `TableFilterForm`

class · defined in `oldman.web.components.forms.base`

```python
class TableFilterForm(Form)
```

A filter form specifically for driving Table APIs.

Members:

- `layout_style: str = 'inline'`
- `async def render(*, table_target: str='', action: str='', method: str='get', submit_label: str | LazyTranslation=_FILTER_LABEL, cancel_url: str | None=None, cancel_label: str | LazyTranslation=_CANCEL_LABEL, extra_buttons: Markup | str='', form_class: str='') -> Markup` — Render Table filter-component HTML.

## `TagsField`

class · defined in `oldman.web.components.forms.fields`

```python
class TagsField(StringField)
```

Store progressively enhanced text tags as one string.

Constructor:

```python
TagsField(*args: Any, delimiter: str=',', **kwargs: Any) -> None
```

Members:

- `def process_data(value: Any) -> None` — Normalize model/default values so initial rendering matches submission results.
- `def process_formdata(valuelist: list[Any]) -> None` — Normalize browser submissions while preserving the string-data contract.

## `TagsInputWidget`

class · defined in `oldman.web.components.forms.widgets`

```python
class TagsInputWidget(TextInput)
```

Emit a native text input declaring progressive TagsInput enhancement.

Constructor:

```python
TagsInputWidget(*, delimiter: str=',') -> None
```

## `TagsSelectWidget`

class · defined in `oldman.web.components.forms.widgets`

```python
class TagsSelectWidget(SelectWidget)
```

Display local multiple selections as removable tags through the existing Select component.

Constructor:

```python
TagsSelectWidget() -> None
```

## `TailwindFieldRenderer`

class · defined in `oldman.web.components.forms.renderers`

```python
class TailwindFieldRenderer(FieldRenderer)
```

Tailwind/Oldman field renderer.

Members:

- `def widget_base_class(field: Field) -> str` — Return Tailwind control classes.
- `def invalid_class() -> str` — Return field-error classes.

## `TailwindForm`

class · defined in `oldman.web.components.forms.tailwind`

```python
class TailwindForm(Form)
```

Default Tailwind base for ordinary business forms.

## `TailwindFormRenderer`

class · defined in `oldman.web.components.forms.renderers`

```python
class TailwindFormRenderer(FormRenderer)
```

Tailwind/Oldman whole-form renderer.

## `TailwindModelForm`

class · defined in `oldman.web.components.forms.tailwind`

```python
class TailwindModelForm(ModelForm)
```

Default Tailwind base for business model forms.

## `TailwindTableFilterForm`

class · defined in `oldman.web.components.forms.tailwind`

```python
class TailwindTableFilterForm(TableFilterForm)
```

Default Tailwind base for business table-filter forms.

## `TelField`

class · defined in `oldman.web.components.forms._core.fields.simple`

```python
class TelField(StringField)
```

Represents an ``<input type="tel">``.

## `TextAreaField`

class · defined in `oldman.web.components.forms._core.fields.simple`

```python
class TextAreaField(StringField)
```

This field represents an HTML ``<textarea>`` and can be used to take

## `TimeField`

class · defined in `oldman.web.components.forms._core.fields.datetime`

```python
class TimeField(DateTimeField)
```

Same as :class:`~wtforms.fields.DateTimeField`, except stores a

Constructor:

```python
TimeField(label=None, validators=None, format: str | list[str]='%H:%M', **kwargs)
```

Members:

- `def process_formdata(valuelist)`

## `UploadField`

class · defined in `oldman.web.components.forms.fields`

```python
class UploadField(FileField)
```

A WTForms field binding one Sanic upload.

Members:

- `def process_data(value: Any) -> None` — Do not treat the database's logical filename as a new upload when editing models.

## `URLField`

class · defined in `oldman.web.components.forms._core.fields.simple`

```python
class URLField(StringField)
```

Represents an ``<input type="url">``.

## `ValidationError`

class · defined in `oldman.web.components.forms._core.validators`

```python
class ValidationError(ValueError)
```

Raised when a validator fails to validate its input.

Constructor:

```python
ValidationError(message='', *args, **kwargs)
```

## `WeekField`

class · defined in `oldman.web.components.forms._core.fields.datetime`

```python
class WeekField(DateField)
```

Same as :class:`~wtforms.fields.DateField`, except represents a week,

Constructor:

```python
WeekField(label=None, validators=None, format: str | list[str]='%Y-W%W', **kwargs)
```

Members:

- `def process_formdata(valuelist)`

## Module `oldman.web.components.forms.models`

ModelForm base class.

Import with `from oldman.web.components.forms.models import <name>`.

### `humanize_model_field_name`

function · defined in `oldman.web.components.forms.models`

```python
def humanize_model_field_name(name: str) -> str
```

Convert a model field name to a default form label.

### `model_field_for_column`

function · defined in `oldman.web.components.forms.models`

```python
def model_field_for_column(column: Any, *, mapper: Any=None, label: str | None=None, description: str | None=None, model_choice: ModelChoice | None=None) -> Any
```

Convert a SQLAlchemy Column to a WTForms field declaration.

## Module `oldman.web.components.forms.renderers`

Form renderer protocols and template-based theme output.

Import with `from oldman.web.components.forms.renderers import <name>`.

### `layout_width_classes`

function · defined in `oldman.web.components.forms.renderers`

```python
def layout_width_classes(width: str) -> str
```

Return declarative Tailwind grid-column spans.

## Module `oldman.web.components.forms.validators`

Field validators for Oldman forms.

Import with `from oldman.web.components.forms.validators import <name>`.

### `any_of`

value · defined in `oldman.web.components.forms._core.validators`

```python
any_of = AnyOf
```

### `AnyOf`

class · defined in `oldman.web.components.forms._core.validators`

```python
class AnyOf
```

Compares the incoming data to a sequence of valid inputs.

Constructor:

```python
AnyOf(values, message=None, values_formatter=None)
```

Members:

- `staticmethod def default_values_formatter(values)`

### `data_required`

value · defined in `oldman.web.components.forms._core.validators`

```python
data_required = DataRequired
```

### `DataRequired`

class · defined in `oldman.web.components.forms._core.validators`

```python
class DataRequired
```

Checks the field's data is 'truthy' otherwise stops the validation chain.

Constructor:

```python
DataRequired(message=None)
```

### `Disabled`

class · defined in `oldman.web.components.forms._core.validators`

```python
class Disabled
```

Set a field disabled.

Constructor:

```python
Disabled()
```

### `disabled`

value · defined in `oldman.web.components.forms._core.validators`

```python
disabled = Disabled
```

### `Email`

class · defined in `oldman.web.components.forms._core.validators`

```python
class Email
```

Validates an email address. Requires email_validator package to be

Constructor:

```python
Email(message=None, granular_message=False, check_deliverability=False, allow_smtputf8=True, allow_empty_local=False)
```

### `email`

value · defined in `oldman.web.components.forms._core.validators`

```python
email = Email
```

### `equal_to`

value · defined in `oldman.web.components.forms._core.validators`

```python
equal_to = EqualTo
```

### `EqualTo`

class · defined in `oldman.web.components.forms._core.validators`

```python
class EqualTo
```

Compares the values of two fields.

Constructor:

```python
EqualTo(fieldname, message=None)
```

### `input_required`

value · defined in `oldman.web.components.forms._core.validators`

```python
input_required = InputRequired
```

### `InputRequired`

class · defined in `oldman.web.components.forms._core.validators`

```python
class InputRequired
```

Validates that input was provided for this field.

Constructor:

```python
InputRequired(message=None)
```

### `ip_address`

value · defined in `oldman.web.components.forms._core.validators`

```python
ip_address = IPAddress
```

### `IPAddress`

class · defined in `oldman.web.components.forms._core.validators`

```python
class IPAddress
```

Validates an IP address.

Constructor:

```python
IPAddress(ipv4=True, ipv6=False, message=None)
```

Members:

- `classmethod def check_ipv4(value)`
- `classmethod def check_ipv6(value)`

### `Length`

class · defined in `oldman.web.components.forms._core.validators`

```python
class Length
```

Validates the length of a string.

Constructor:

```python
Length(min=-1, max=-1, message=None)
```

### `length`

value · defined in `oldman.web.components.forms._core.validators`

```python
length = Length
```

### `mac_address`

value · defined in `oldman.web.components.forms._core.validators`

```python
mac_address = MacAddress
```

### `MacAddress`

class · defined in `oldman.web.components.forms._core.validators`

```python
class MacAddress(Regexp)
```

Validates a MAC address.

Constructor:

```python
MacAddress(message=None)
```

### `none_of`

value · defined in `oldman.web.components.forms._core.validators`

```python
none_of = NoneOf
```

### `NoneOf`

class · defined in `oldman.web.components.forms._core.validators`

```python
class NoneOf
```

Compares the incoming data to a sequence of invalid inputs.

Constructor:

```python
NoneOf(values, message=None, values_formatter=None)
```

Members:

- `staticmethod def default_values_formatter(v)`

### `number_range`

value · defined in `oldman.web.components.forms._core.validators`

```python
number_range = NumberRange
```

### `NumberRange`

class · defined in `oldman.web.components.forms._core.validators`

```python
class NumberRange
```

Validates that a number is of a minimum and/or maximum value, inclusive.

Constructor:

```python
NumberRange(min=None, max=None, message=None)
```

### `Optional`

class · defined in `oldman.web.components.forms._core.validators`

```python
class Optional
```

Allows empty input and stops the validation chain from continuing.

Constructor:

```python
Optional(strip_whitespace=True)
```

### `optional`

value · defined in `oldman.web.components.forms._core.validators`

```python
optional = Optional
```

### `ReadOnly`

class · defined in `oldman.web.components.forms._core.validators`

```python
class ReadOnly
```

Set a field readonly.

Constructor:

```python
ReadOnly()
```

### `readonly`

value · defined in `oldman.web.components.forms._core.validators`

```python
readonly = ReadOnly
```

### `Regexp`

class · defined in `oldman.web.components.forms._core.validators`

```python
class Regexp
```

Validates the field against a user provided regexp.

Constructor:

```python
Regexp(regex, flags=0, message=None)
```

### `regexp`

value · defined in `oldman.web.components.forms._core.validators`

```python
regexp = Regexp
```

### `StopValidation`

class · defined in `oldman.web.components.forms._core.validators`

```python
class StopValidation(Exception)
```

Causes the validation chain to stop.

Constructor:

```python
StopValidation(message='', *args, **kwargs)
```

### `URL`

class · defined in `oldman.web.components.forms._core.validators`

```python
class URL(Regexp)
```

Simple regexp based url validation. Much like the email validator, you

Constructor:

```python
URL(require_tld=True, allow_ip=True, message=None)
```

### `url`

value · defined in `oldman.web.components.forms._core.validators`

```python
url = URL
```

### `UUID`

class · defined in `oldman.web.components.forms._core.validators`

```python
class UUID
```

Validates a UUID.

Constructor:

```python
UUID(message=None)
```

## Module `oldman.web.components.forms.widgets`

Form widgets: Oldman's own and the form core's HTML widgets.

Import with `from oldman.web.components.forms.widgets import <name>`.

### `CheckboxInput`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class CheckboxInput(Input)
```

Render a checkbox.

### `ColorInput`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class ColorInput(Input)
```

Renders an input with type "color".

### `DateInput`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class DateInput(Input)
```

Renders an input with type "date".

### `DateTimeInput`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class DateTimeInput(Input)
```

Renders an input with type "datetime".

### `DateTimeLocalInput`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class DateTimeLocalInput(Input)
```

Renders an input with type "datetime-local".

### `EmailInput`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class EmailInput(Input)
```

Renders an input with type "email".

### `FileInput`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class FileInput(Input)
```

Render a file chooser input.

Constructor:

```python
FileInput(multiple=False)
```

### `HiddenInput`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class HiddenInput(Input)
```

Render a hidden input.

Constructor:

```python
HiddenInput(*args, **kwargs)
```

### `html_params`

function · defined in `oldman.web.components.forms._core.widgets.core`

```python
def html_params(**kwargs)
```

Generate HTML attribute syntax from inputted keyword arguments.

### `Input`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class Input
```

Render a basic ``<input>`` field.

Constructor:

```python
Input(input_type=None)
```

Members:

- `validation_attrs: list[str]`

### `ListWidget`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class ListWidget
```

Renders a list of fields as a `ul` or `ol` list.

Constructor:

```python
ListWidget(html_tag='ul', prefix_label=True)
```

### `MonthInput`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class MonthInput(Input)
```

Renders an input with type "month".

### `NumberInput`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class NumberInput(Input)
```

Renders an input with type "number".

Constructor:

```python
NumberInput(step=None, min=None, max=None)
```

### `Option`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class Option
```

Renders the individual option from a select field.

### `PasswordInput`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class PasswordInput(Input)
```

Render a password input.

Constructor:

```python
PasswordInput(hide_value=True)
```

### `RadioInput`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class RadioInput(Input)
```

Render a single radio button.

### `RangeInput`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class RangeInput(Input)
```

Renders an input with type "range".

Constructor:

```python
RangeInput(step=None)
```

### `SearchInput`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class SearchInput(Input)
```

Renders an input with type "search".

### `Select`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class Select
```

Renders a select field.

Constructor:

```python
Select(multiple=False)
```

Members:

- `classmethod def render_option(value, label, selected, **kwargs)`

### `SubmitInput`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class SubmitInput(Input)
```

Renders a submit button.

### `TableWidget`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class TableWidget
```

Renders a list of fields as a set of table rows with th/td pairs.

Constructor:

```python
TableWidget(with_table_tag=True)
```

### `TelInput`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class TelInput(Input)
```

Renders an input with type "tel".

### `TextArea`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class TextArea
```

Renders a multi-line text area.

### `TextInput`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class TextInput(Input)
```

Render a single-line text input.

### `TimeInput`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class TimeInput(Input)
```

Renders an input with type "time".

### `URLInput`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class URLInput(Input)
```

Renders an input with type "url".

### `WeekInput`

class · defined in `oldman.web.components.forms._core.widgets.core`

```python
class WeekInput(Input)
```

Renders an input with type "week".
