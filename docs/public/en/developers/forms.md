# Forms, fields, and remote choices

The backend owns fields, validation, and HTML. The browser submits and enhances forms rather than generating an entire form from backend field schemas. Ordinary pages and Modals use the same Form. For complete CRUD wiring, see [Demo HTML/JSON tables and Modal forms](../users/tutorial-dashboard.md).

Business code in this chapter comes from the EPG demo's [apps/examples/forms.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/forms.py), without another example App. Follow [Run EPG Dashboard Demo](../users/getting-started.md) to load fixtures and sign in, then compare these pages:

| Page | Class and actual behavior |
| --- | --- |
| `/examples/forms/basics` | BasicFieldsForm; the same declaration demonstrates HTML/JSON responses, validating without database writes |
| `/examples/forms/validation` | ValidationExampleForm; field and cross-field errors; currently JSON forms only |
| `/examples/tables/html`, `/examples/tables/json` | ExampleProjectForm inside Modals; creates/updates actual project records |
| `/examples/forms/multi-step` | MultiStepProjectForm; one multi-step Form that ultimately creates one project |
| `/examples/forms/json-list` | StreamProfileForm; encodes, decodes, and saves a variable-length URL list in a Text column |
| `/examples/forms/selects`, `/examples/forms/autocomplete` | LogoSelectForm and LogoAutocompleteForm; remote image/text choices, saving the selected Logo foreign key |

Class field, Meta, and method excerpts cannot run independently. Retain the original imports, models, constants, and accompanying routes. See [Demo page and source index](../users/demo-examples.md) for other field pages.

## Choosing a base class

Public base classes live in `oldman.web.components.forms`. `Form` / `ModelForm` are unthemed; `TailwindForm` / `TailwindModelForm` serve dashboards; `TableFilterForm` / `TailwindTableFilterForm` filter Tables. The demo's BasicFieldsForm, ExampleProjectForm, and ExampleProjectFilterForm demonstrate the latter three respectively.

Ordinary fields and synchronous validators come directly from WTForms. Oldman supplies request binding, asynchronous cleaning, database choices, ModelForm, layout, and rendering, without requiring duplicate field-wrapper subclasses. Tailwind subclasses use shared `om-*` styles for dashboard/Admin use. Unthemed bases suit applications providing their own renderers.

A form instance belongs to one request and must not be a process-wide singleton.

## Binding and cleaning

Common constructor parameters are `request`, `data`, `files`, `obj`, `session`, `initial`, `prefix`, `csrf_token`, and `select_secret_key`. `data` is submitted data; `initial` supplies initial values. Do not pass both `data=` and WTForms `formdata=`. ModelForm uses `instance=` rather than `obj=`.

- `Form.from_request(request, ...)` binds `request.form` and `request.files` for POST/PUT/PATCH; GET remains unbound.
- `Form.from_query(request, ...)` binds query parameters even when empty, making it suitable for filters.
- `await form.validate()` / `await form.is_valid()` run the same validation lifecycle.
- Validating an unbound form returns False without generating errors or running asynchronous choices queries.
- `form.data` is the stored input mapping. Read valid values from `form.cleaned_data`; do not write all user input directly to models.

For example, the following complete ExampleProjectForm methods handle unique slugs and date ranges. They remain inside the original class. `select` comes from SQLAlchemy, `ValidationError` from WTForms, `_` is `oldman.i18n.gettext_lazy`, and ExampleProject is the demo model:

```python
    async def clean_slug(self) -> str:
        """Reject duplicate stable slugs before the database constraint fires."""
        slug = str(self.slug.data or "").strip()
        if self.session is None:
            raise RuntimeError("ExampleProjectForm validation requires a database session")
        result = await self.session.execute(select(ExampleProject).where(ExampleProject.slug == slug))
        existing = result.scalar_one_or_none()
        if existing is not None and int(existing.id) != int(getattr(self.instance, "id", 0) or 0):
            raise ValidationError(_("A project with this slug already exists."))
        return slug

    async def clean(self) -> dict[str, object] | None:
        """Validate the optional project date range."""
        start_date = self.cleaned_data.get("start_date")
        end_date = self.cleaned_data.get("end_date")
        if start_date is not None and end_date is not None and end_date < start_date:
            raise ValidationError(_("End date must not be earlier than start date."))
        return None
```

This query provides a friendly message; it does not replace the model's unique constraint. Concurrent submissions can still fail during database writes. Do not turn every database exception into an invalid-field error.

The order is asynchronous field preparation → WTForms synchronous validation → `clean_<name>()` for fields without errors → form-wide `clean()`. Field cleaners must be asynchronous and return the final value; returning None sets the value to None. Even validation-only cleaners should return the original value. The framework cannot infer a forgotten return.

Form `clean()` still runs when some fields fail. Its `cleaned_data` contains only values that passed field validation. Returning None retains existing data; returning a dict **merges** its keys, overriding matching names. Thus `return {"extra": 1}` adds a key without discarding other fields. The `cleaned_data` property returns a copy; modifying that copy does not alter internal state.

Hidden-field values **do** enter `cleaned_data`, consistent with WTForms `form.data`: `HiddenField("record_id")` exists to read that value back. Renderers skip them by type only because `hidden_fields()` renders them together. That is a rendering rule, not a data rule.

`ValidationError` means ordinary validation failure: field-cleaner exceptions become field errors, while form `clean()` exceptions populate the single `error_message`. `add_error(field_name, message)` also adds an actual field error and excludes that field from cleaned_data; the demo's StreamProfileForm.clean_name uses it. Invalid field names and `__all__` raise errors. Programming failures such as TypeError or database exceptions propagate without becoming validation errors.

Python `form.errors` retains complete error lists. HTML and `to_api_response()` display/output only the first error per field. Attach cross-field errors to their relevant field where possible; otherwise raise ValidationError from `clean()`. There is no separate non-field-error list.

## Rendering and responses

`await form.render(...)` returns Markup for a complete `<form>`. Main parameters:

| Parameter | Default and purpose |
| --- | --- |
| `action`, `method` | `""`, `"post"`; an empty action uses the current URL |
| `form_mode` | `"html"` or `"json"`; specifies response format |
| `target`, `swap` | Unspecified by default; HTML replacement target and inner/outer mode |
| `submit_label`, `cancel_url`, `cancel_label` | Submit and cancel buttons |
| `component_name` | `"form"`; None omits the browser Form declaration for native browser submission |
| `validate` | False; True enables browser validation enhancement; backend validation is still required |
| `feedback_target`, `form_class`, `extra_buttons` | Explicit feedback target, container classes, and additional button HTML |

`render_field(field_or_name)` renders a field's label, control, help, and errors. `render_actions()` renders the action area. Custom whole-form templates must retain actual field names, error locations, the top message, and CSRF fields. Use distinct prefixes for multiple forms to avoid id/name collisions.

Generated `<form>` elements have `novalidate`. With `validate=True`, the browser component uses constraint-validation APIs to display field errors. Field plugins and client validation are not save-security boundaries; invalid input sent around the browser must still fail.

The demo's [views/forms.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/forms.py) passes mode in `_form_card()`, [page.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/forms/page.html) calls `form.render()`, and POST binds with the same prefix. Retain the two forms' `html` / `json` prefixes during submission or field names will not match.

The file's error-response function follows unchanged. The Accept header sent by Form determines the actual response. JSON clients receive `form.to_api_response()` (HTTP 200 because validation failure is a business result); fragment clients receive the rerendered Form (422). `mode` configures the rerendered Form. Do not infer backend response format from the URL alone:

```python
async def _form_error_response(request: Request, form: Any, *, action: str, mode: str):
    """Return the response contract selected by the mounted Form component."""
    return await form_invalid_response(
        request,
        form,
        fragment=lambda: form.render(action=action, form_mode=mode, submit_label=_("Submit example")),
    )
```

`form_invalid_response` comes from `oldman.web.api`, alongside `accepts_json_form_response`, `form_success_response`, and others; see [Browser responses and ordered actions](responses.md#backend-types). Request, Any, and translation functions are imported in that file. Whole-page forms also pass a `page=` callback so direct browser submissions receive a complete page with status 422. HTML success uses `_form_success_response()` for a success fragment; JSON success returns DefaultApiFormResponse and actions. Ordinary-field examples save no records; only `multi-step` calls ModelForm.save in a transaction. See [Browser responses and ordered actions](responses.md) for both paths and browser event order.

## ModelForm save boundaries

ExampleProjectForm inherits TailwindModelForm. Its Meta excerpt follows; the two cleaners above also belong to this class:

```python
    class Meta(TailwindModelForm.Meta):
        """Bind only fields exercised by the Table CRUD example."""

        model = ExampleProject
        fields = (
            "team_id",
            "name",
            "slug",
            "description",
            "status",
            "priority",
            "budget",
            "progress",
            "start_date",
            "end_date",
            "is_active",
        )
```

`Meta.fields` must enumerate fields explicitly; `"__all__"` is unsupported. Meta can provide `labels`, `help_texts`, and `model_choices`. Explicit fields take precedence, without a global heuristic for complex types.

Automatic mappings cover strings/Text, integers, booleans, dates/datetimes, ordinary foreign keys, and file-metadata columns. Other types require explicit fields such as DecimalField; unknown types do not silently become strings. String-column lengths set maxlength, but business-required server constraints such as Length still need explicit declarations.

The actual creation endpoint is in [views/tables.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/tables.py). Its `router` comes from `oldman.web`, db_manager from `oldman.db`, and `login_required`/`require_perm` from `oldman.web.auth`. CSRF decorators and `modal_success_response` (`oldman.web.api`) come from the framework. `ExamplePermissions` contains demo-declared permissions:

```python
@router.post("/examples/tables/projects/create", name="example_project_create")
@csrf_protect()
@login_required()
async def example_project_create(request: Request):
    """Create one Project and reload the mounted HTML or JSON Table."""
    await require_perm(request, ExamplePermissions.change_projects)
    async with db_manager.get_session() as session:
        form = ExampleProjectForm.from_request(request, session=session)
        if not await form.validate():
            return json_response(form.to_api_response().to_dict())
        await form.save(commit=True, session=session)
    return modal_success_response(_("Project created."), table_target="#example-projects-table")
```

GET `example_project_create_modal()` first gets a token through `@add_csrf_token()`, renders database choices in a read Session, and gives the complete Form HTML to an ordinary Modal. `modal_success_response()` runs only after successful transaction exit and returns feedback, close-Modal, and refresh-Table actions. See [Browser responses and ordered actions](responses.md#backend-types) for its payload.

`save()` defaults to commit=False and only prepares the model instance. commit=True adds/flushes with the supplied Session but **does not commit itself**. The outer scope owns the transaction. Saving without successful validation raises ValueError. The demo edit endpoint first queries through `get_object_or_404(session, ExampleProject, project_id, ...)` (`oldman.web.shortcuts`), then passes `instance=project`. The current demo shares data among all signed-in users. Business applications requiring user/tenant isolation must restrict the query too; a request primary key is not a trusted save target.

Maintain model-derived columns (created/updated times, lowercase lookup columns, constructed keys) in `before_save(instance)` rather than overriding `save()`. This hook runs after form values and uploaded filenames enter the instance but before database writes. The framework still handles session, add, and flush.

```python
    async def before_save(self, channel: ChannelsEpg) -> None:
        """Maintain derived fields inherited from the legacy database."""
        if channel.create_date is None:
            channel.create_date = utcnow_naive()
        channel.tvg_id_lookup = channel.tvg_id.lower() if channel.tvg_id else None
```

Upload fields are an exception: save may write new files to Storage even with commit=False. Pass a framework-managed Session to participate in the existing file lifecycle. Do not interpret commit=False as an absolute guarantee of no external side effects.

See [File storage and model file fields](storage.md#model-declarations-and-forms) for complete wiring of file_column, multiple file fields, replacement/rollback/deletion, and Storage initialization.

## Layout and multiple steps

The demo's `/examples/forms/layouts` uses the complete LayoutExampleForm. It inherits BasicFieldsForm in the same file. Actions, FieldLayout, FormLayout, FormStep, and Row all come from `oldman.web.components.forms`:

```python
class LayoutExampleForm(BasicFieldsForm):
    """The same scalar fields arranged through Oldman's declarative layout."""

    layout = FormLayout(
        Row("name", "email", width="md:col-span-6"),
        Row("age", "budget", "enabled", width="md:col-span-4"),
        FieldLayout("notes"),
        Actions(submit=_("Submit layout")),
    )
```

`FieldLayout(name, width="md:col-span-12", advanced=False)` controls one field; Row gives grouped fields equal widths. `Row(start, end, as_range=True, label=...)` combines start/end fields into one range control. Its `label` describes the whole range, defaulting to the start field's label. Grid layouts show two inputs under one label; inline filters use one prefix with two inputs. `FieldGroup(title, *items, description="")` renders a titled (14/500) `fieldset` with a one-sentence description and an internal field grid. It can mix with ungrouped fields or appear inside FormStep. MultiStepProjectForm inherits ExampleProjectForm above and uses FormLayout/FormStep from the same file for Identity, Planning, and Details steps. A final Actions submits the entire form. There is still one backend validation and one save, not a database submission per step. Server errors must preserve step/field markers. Dynamic templates must mount through Page's component manager.

When ModelForm generates fields from columns, labels/help follow these priorities: explicitly declared fields > `Meta.labels` / `Meta.help_texts` > column `info={"label": ..., "help_text": ...}` > humanized field names. Put model-level defaults on columns and form-specific overrides in Meta.

Filter forms (`TailwindTableFilterForm`) default to `layout_style = "inline"`. Search inputs (`render_kw={"type": "search"}` or field name `q`) fill remaining width; other controls use labels as left prefixes. `advanced=True` fields move into a "More filters" panel on the right, followed by fixed "Reset" and "Filter" controls. Pages with many always-visible fields can use `layout_style = "grid"` for labels above controls. Each layout has corresponding templates under `oldman/forms/default/`; override matching project paths to restyle them.

## Extended fields

Import all the following from `oldman.web.components.forms`:

| Field or Widget | Stored value and purpose |
| --- | --- |
| `SlugField` | Ordinary string for URL slug generation/editing, not a tag list |
| `TagsField(delimiter=",")` | Delimited string; browser tag addition/removal for String/Text |
| `SwitchCardWidget` / `SwitchWidget` / `CheckboxWidget` | Three BooleanField presentations: bordered switch card (label/help left, switch right; Tailwind default), inline switch, or checkbox row. All submit ordinary checkbox values. Help comes from field `description`, equivalent to Django help_text |
| `TagsInputWidget` | Adds tags-input DOM to an ordinary text field; use TagsField for normalization |
| `TagsSelectWidget` | Enhances an existing Select for local multiple selection; submits an option list rather than a delimited string |
| `CheckboxGroupField` | List selecting multiple fixed choices, rendered as checkboxes rather than a multi-select listbox. WTForms-style grouped choices (dict of group name → choices) show group subheadings. Like other multiple-selection fields, only listed values are accepted. `DataRequired()` requires at least one selection without making every checkbox required. Render through `await form.render()` / `render_field()`; direct field calls still produce a multi-select listbox |
| `JSONListField` | JSON array in Text ↔ a one-dimensional scalar-field list; form-repeater handles additions/removals |
| `InputSpinnerWidget` | Increment/decrement controls for Integer/Decimal fields; still a number input underneath |
| `DateTimePickerWidget` | Adds a picker to existing date/time fields; fields validate actual formats |
| `ColorPickerField` | Hex color; `allow_alpha` controls transparency |
| `EmailField` | `type="email"` input; trims/lowercases submissions before format and 254-character validation, preserving one database representation; used by user forms and password reset |
| `RichTextField` | HTML string; an editor does not make HTML trusted; sanitize server-side according to business requirements |
| `UploadField` | A Sanic upload object on ordinary Forms, not a local file path |
| `FileSize(max_bytes)`, `FileExtension(extensions)` | Upload-size/extension validation; extensions do not prove actual content safety |

Fields needing asynchronous Widgets must render through `await form.render()`, `await form.render_field()`, or asynchronous templates, not synchronous `field()` calls.

The demo's StreamProfileForm field excerpt follows. StringField, DataRequired, and URL still come from WTForms:

```python
    sources_json = JSONListField(
        StringField(_("Source URL"), validators=[DataRequired(), URL()]),
        min_entries=1,
        max_entries=8,
    )
```

Its model is [ExampleStreamProfile](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/models.py). `sources_json` is a Text column explicitly included in Form.Meta.fields. In [json_list.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/forms/json_list.html), creation uses `prefix="create"` with HTML responses; editing uses `prefix="edit"` with JSON responses. Submitted names include `create-sources_json-0` and `edit-sources_json-0`. Do not omit prefixes or rename fields into another backend protocol.

An ordinary Form's cleaned_data contains a list. ModelForm encodes it as JSON text for the corresponding model field and decodes it on reading. StreamProfileForm.clean() also trims URLs, rejects duplicates, and returns replacement cleaned_data. Creation/edit routes in views/forms.py above both use real database transactions.

Only one-dimensional scalars are supported, not nested FieldList/FormField. Item errors target exact names; list-size/JSON errors populate the top message. Do not silently truncate excessive input and report success.

## Database choices and remote selection

For small choice sets, use `ModelChoiceField(model_choice=ModelChoice(...))` with the current database Session. Synchronous choice validation runs after choices are prepared. For large sets, use remote providers instead of loading an entire table on initial page load.

The remote sequence is Form Widget binding signature → browser provider-endpoint request → binding/permission verification → search or initial-value lookup → JSON choices. AjaxSelectField, AjaxSelectMultipleField, and AjaxAutocompleteWidget come from `oldman.web.components.forms`. ModelSelectProvider, DataSelectProvider, SelectChoice, SelectResult, SelectProviderView, and select_registry come from `oldman.web.components.selects`.

The demo's [providers.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/providers.py) defines ExampleLogoProvider, ExampleTagProvider, and ExampleCountryProvider. `@select_registry.register("example_logos")` registers the class; each request creates an instance. ModelSelectProvider supplies `model`, `search_fields`, `label_field`, `value_field`, and other settings. Override `get_queryset(request, context)` for business queries. ExampleLogoProvider selects available Logos ordered by name/id. It does not override `check_auth`; the central endpoint requires only sign-in. `filter_queryset()` further filters by the signature-permitted country_code. ExampleCountryProvider inherits DataSelectProvider and returns a finite country list through `get_choices()`.

Fields specify `provider` and either `endpoint` or `route_name`, with optional `page_size`, `dependent_fields`, `enhance_choices`, and `label_mode`. Register the endpoint with `SelectProviderView.as_view(secret_key=key)` and use the same key for the Form's `select_secret_key`. Derive it from the unified Web security root key instead of placing separate random values in fields, views, and YAML.

### Registering routes and supplying keys

[views/data_inputs.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/data_inputs.py) imports providers during App view loading. Defining classes without executing registration is insufficient. Its import/initialization excerpt follows:

```python
from apps.examples import providers as _providers  # noqa: F401 - import registers providers.
```

```python
SELECT_BINDING_SECRET = configured_web_security_key(WebSecurityPurpose.SELECT_BINDING)
router.add_route(
    SelectProviderView.as_view(secret_key=SELECT_BINDING_SECRET),
    "/examples/select/<provider_name:str>",
    name="example_select_provider",
)
```

SelectProviderView requires only sign-in by default. Put endpoint-wide rules (staff/permissions) in its `check_permission()` and provider-specific rules in provider `check_auth(request, context)`; see [Permissions](permissions.md#permission-layers-in-data-components). `router` comes from `oldman.web`; WebSecurityPurpose and configured_web_security_key come from `oldman.web.security`. This initialization runs during view loading after service configuration is ready, not in an uninitialized bare Python process.

### Declaring fields and loading initial values

LogoSelectForm's field excerpt from the same forms.py:

```python
    country_code = SelectField(_("Country"), choices=LOGO_COUNTRY_CHOICES, validators=[Optional()])
    logo_id = AjaxSelectField(
        _("Logo"),
        provider="example_logos",
        route_name="example_select_provider",
        page_size=8,
        dependent_fields=("country_code",),
        enhance_choices=True,
        label_mode="html",
        validators=[DataRequired()],
    )
```

Meta.model is ExampleStreamProfile, and Meta.fields contains only `logo_id`. country_code is a query condition, not a saved model field. Fields generate their provider endpoint through the registered route_name.

`render_remote_form_page()` loads profile and its current logo from the database, then calls this complete helper, also in views/data_inputs.py:

```python
def _select_form(request: Request, profile: ExampleStreamProfile | None, logo: ExampleLogo | None) -> LogoSelectForm | None:
    """Build the real edit Select form when fixture data exists."""
    if profile is None:
        return None
    return LogoSelectForm(
        request=request,
        instance=profile,
        initial_logo=logo,
        select_secret_key=SELECT_BINDING_SECRET,
    )
```

LogoSelectForm's own `__init__()` sets the initial_logo country and selected value. Use the fields' built-in initial-selection methods rather than handwritten choices and data:

```python
        self.country_code.data = initial_logo.country_code
        self.logo_id.initial_choice(initial_logo.id, f"{initial_logo.name} · {initial_logo.country_code}")
```

`AjaxSelectField.initial_choice(value, label)` inserts/selects one option. `AjaxSelectMultipleField.initial_choices([(value, label), ...])` displays multiple selections in supplied order. `AjaxAutocompleteField.initial_choice(value, label)` puts the ID in the field value and label in the input. All three skip empty values and forms already processed with submitted data (`raw_data is not None`), so call them unconditionally in `__init__` without checking `is_bound`. The check is whether submission happened, not what was submitted. When a user clears every multiple-selection option, browsers omit the key and `raw_data` is an empty list; restoring old values would discard that clearing. Initial HTML thus includes selections, and remote initial-value queries can continue displaying them. The first search page must not replace selected-value lookup. Without profile, return None and ask the user to prepare fixtures rather than fabricating a saved object.

Remote fields **do not validate submitted values by default**. Without local choices, WTForms cannot compare them, so any browser-submitted integer is accepted. To validate, declare field `allowed_values`: an `async (request, values) -> iterable of allowed values` callable returning values permitted for this request. Other submissions fail with `Not a valid choice.`.

```python
async def my_logos(request, values):
    async with db_manager.get_read_session() as session:
        rows = await session.execute(
            select(Logo.id).where(Logo.owner_id == request.ctx.session.user_id, Logo.id.in_(values))
        )
        return [str(value) for value in rows.scalars()]

logo_id = AjaxSelectField("Logo", provider="example_logos", route_name="...", allowed_values=my_logos)
```

It deliberately **does not** reuse provider `get_queryset`. Values a user can see and values they can submit are distinct sets. A common form may permit reassignment to any user while showing only the twenty most recent users in the dropdown. Using the display set as the allowed set would break it. Forms declare allowed sets; providers determine display sets, independently.

The resolver is an ordinary asynchronous function, so sources are not limited to databases. Structured data, caches, and remote services use the same hook. Without a declaration it adds no overhead or queries. Multiple-selection fields with `tags=True` intentionally allow nonexistent values and skip validation even when declared.

Clearing an optional remote foreign key (`validators=[Optional()]`) submits an empty string, which `AjaxSelectField` stores as `None`. No extra empty-to-None coerce wrapper is needed. Cleared multiple selections may submit an empty string or omit the key entirely; `AjaxSelectMultipleField` stores `[]` in both cases, without separate caller handling.

### Submissions still require object validation

POST `/examples/forms/selects/<profile_id>/edit` is protected by `@csrf_protect()` and framework `@login_required()` and enters `_update_logo()`:

1. Query ExampleStreamProfile in a framework write Session; return 404 if absent.
2. Call LogoSelectForm.from_request with instance, the same Session, and SELECT_BINDING_SECRET.
3. Run `await form.validate()`; failure returns HTTP-200 field errors without saving.
4. After validation, call `save(commit=True, session=session)` and rerender the form with its selected Logo.
5. After successful transaction exit, return FeedbackAction and ReplaceHtmlAction to replace `#example-logo-select-form`.

LogoSelectForm's complete field-validation/query method follows, retaining failure paths:

```python
    async def clean_logo_id(self) -> int:
        """Reject forged, unavailable or country-mismatched submitted IDs."""
        logo_id = int(str(self.logo_id.data))
        logo = await self._submitted_logo(logo_id)
        if logo is None or not logo.is_available:
            raise ValidationError(_("Select an available logo."))
        country_code = str(self.country_code.data or "")
        if country_code and logo.country_code != country_code:
            raise ValidationError(_("The selected logo does not belong to this country."))
        return logo_id

    async def _submitted_logo(self, logo_id: int) -> ExampleLogo | None:
        """Read the submitted Logo in the active write transaction."""
        if self.session is None:
            raise RuntimeError("LogoSelectForm validation requires a database session")
        return await self.session.get(ExampleLogo, logo_id)
```

This AjaxSelectField first applies default integer coerce. Failed conversion prevents the cleaner from running. LogoAutocompleteForm uses StringField plus AjaxAutocompleteWidget, so its own cleaner explicitly catches integer-conversion failure. Do not copy the former cleaner to arbitrary string controls while omitting this boundary.

### Image/text choices, pagination, and multiple selection

Successful provider JSON has top-level `results` and `more`, not form actions. Each choice has id/text and optional html/data. Searches read q/page, and `more` controls further loading. Initial values use separate value/values lookups. The server limits providers, field bindings, page sizes, and permitted dependent fields.

ExampleLogoProvider.get_option() returns plain-text labels and trusted Markup through SelectChoice. Images use local fixture SVG paths; names and other variables are escaped first. Fields require `label_mode="html"`; Select also requires `enhance_choices=True`. Ordinary html strings are escaped rather than executed directly. Autocomplete uses the corresponding AjaxAutocompleteWidget with the same provider protocol.

LogoMultipleSelectForm demonstrates multiple initial selections, image/text search, and further loading on the same page. It does not claim to save multiple Logos to one logo_id foreign key and introduces no new many-to-many persistence API.

Remote choices are absent from initial HTML choices, so fields disable WTForms local-choice validation. **Saving must still verify that submitted IDs exist and are selectable by the current user**. Signatures prove Widget binding rather than object permissions. A filtered search list does not justify trusting a hand-crafted POST.

<!-- source: zh/developers/forms.md @ db5eb607 -->
