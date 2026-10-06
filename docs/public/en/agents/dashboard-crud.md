# Agent guide: a dashboard page with a table and create, edit, delete

Use this guide to add a business page to an Oldman dashboard project: a list in a table, and create, edit and delete
in a modal. Paths such as `docs/public/zh/developers/tables.md` are relative to the framework repository, which in a
generated project is your `.oldman-docs/` clone. Before using any `oldman` import, look it up in the
[API index](../api/README.md).

## The common path: a list with create, edit and delete

This is the complete sequence, verified on a generated `dashboard` project with SQLite whose service is `dashboard`,
in Chrome. Replace `customers`, `Customer` and the fields with what the user asked for; keep every step.

The project must have been set up once as its README says (`settings sync`, `db migrate`, `createsuperuser`): you
add models to a migrated database. On a database that was never migrated, `db makemigrations` asks for `db migrate`
first and `db migrate` refuses while an App has models without a migration.

### 1. Create and register the App

```sh
OLDMAN_ANSWER_STARTAPP_TEMPLATE=dashboard ./run.sh startapp customers
```

`startapp` writes `apps/customers/` (`apps.py`, `models.py`, `views.py`, `migrations/`), the page template
`templates/customers/index.html` and the page script `frontend/src/pages/customers.ts`. Do not write them by hand.
Add `apps.customers` to `apps` in `data/dashboard_settings.yaml`, then:

```sh
./run.sh dashboard settings sync
```

The menu is listed in one place, `templates/partials/sidebar.html`. Add the page under the Home link:

```jinja
{{ sidebar_menu_link("/customers", _("Customers"), "ri-user-3-line", active=request.path.startswith("/customers")) }}
```

### 2. Declare the model

`apps/customers/models.py`:

```python
"""Data models for customers."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from oldman.db import DatabaseModel
from oldman.utils.date import naive_utcnow


class Customer(DatabaseModel):
    """A customer the team works with."""

    __tablename__ = "customers_customer"  # pyright: ignore[reportAssignmentType] -- SQLAlchemy declared_attr override

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    company: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=naive_utcnow)
```

### 3. Create and apply the migration — the user runs `makemigrations`

```sh
./run.sh db makemigrations
./run.sh db migrate
```

`makemigrations` asks for a description in a real terminal (Enter keeps the suggestion, `create customers_customer`).
Without a terminal it stops with "This migration decision requires an interactive terminal." Ask the user to run it
(in Claude Code: `! ./run.sh db makemigrations`). On a database that is already set up, `db migrate` runs without a
terminal. Check with `./run.sh db status`: the App must show `pending=none`. Never create tables another way; see
`create-service.md` in this directory for the full migration rules.

### 4. The form

`apps/customers/forms.py`:

```python
"""The form that creates and edits a customer."""

from __future__ import annotations

from sqlalchemy import select
from wtforms import BooleanField, StringField, ValidationError
from wtforms.validators import DataRequired, Length, Optional

from apps.customers.models import Customer
from oldman.i18n import gettext_lazy as _
from oldman.web.components.forms import EmailField, FieldLayout, TailwindModelForm


class CustomerForm(TailwindModelForm):
    """Create and edit one customer; only the fields in Meta.fields can be written."""

    name = StringField(_("Name"), validators=[DataRequired(), Length(max=120)])
    email = EmailField(_("Email"), validators=[DataRequired()])
    company = StringField(_("Company"), validators=[Optional(), Length(max=120)])
    is_active = BooleanField(_("Active"), default=True)

    field_layout = (
        FieldLayout("name", "md:col-span-6"),
        FieldLayout("email", "md:col-span-6"),
        FieldLayout("company", "md:col-span-12"),
        FieldLayout("is_active", "md:col-span-12"),
    )

    class Meta(TailwindModelForm.Meta):
        model = Customer
        fields = ("name", "email", "company", "is_active")

    async def clean_email(self) -> str:
        """Reject an address another customer already has, before the unique index does."""
        email = str(self.email.data or "")
        if self.session is None:
            raise RuntimeError("CustomerForm validation needs a database session")
        existing = (await self.session.execute(select(Customer).where(Customer.email == email))).scalar_one_or_none()
        if existing is not None and existing.id != getattr(self.instance, "id", None):
            raise ValidationError(_("A customer with this email already exists."))
        return email
```

- `Meta.fields` is the whitelist of what a request may change. Fields are WTForms fields; `EmailField` stores the
  address stripped and lowercased, so `clean_email` compares one spelling.
- An `async def clean_<field>()` can query the form's session; raise `ValidationError` for a field error. A
  `clean()` method that raises reports a whole-form error at the top of the form.

### 5. The table

`apps/customers/tables.py`:

```python
"""The customers table: one data endpoint serving the page's rows."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from apps.customers.models import Customer
from oldman.i18n import gettext_lazy as _
from oldman.web.components.tables import Column, RowAction, SQLAlchemyTableView, TailwindTableRenderer, badge, row_actions


class CustomerTable(SQLAlchemyTableView):
    """Every customer, searchable by name, email and company."""

    renderer_class = TailwindTableRenderer
    route_name = "customers_table"
    route_path = "/customers/table"
    model = Customer
    ordering = ("name",)
    search_fields = ("name", "email", "company")
    unsortable_columns = ("action",)
    empty_message = _("No customers yet.")
    columns = (
        Column("name", _("Name")),
        Column("email", _("Email")),
        Column("company", _("Company")),
        Column("is_active", _("Status"), callback="get_column_is_active_data"),
        Column("action", _("Actions"), field_path=None, callback="get_column_action_data", exportable=False),
    )

    async def get_queryset(self) -> Any:
        """All customers; a table of private records narrows this query to the ones the user may see."""
        return select(Customer)

    def get_column_is_active_data(self, row: Customer, **kwargs: object):
        """A status badge, with the boolean as the raw value for sorting and export."""
        label = _("Active") if row.is_active else _("Inactive")
        return badge(label, tone="success" if row.is_active else "secondary"), row.is_active

    def get_column_action_data(self, row: Customer, **kwargs: object):
        """Edit and delete open the page's one remote modal with their own URL."""
        return row_actions(
            [
                RowAction(_("Edit"), modal_target="#customer-modal", modal_url=f"/customers/{row.id}/edit-modal", icon="ri-pencil-line"),
                RowAction(
                    _("Delete"),
                    modal_target="#customer-modal",
                    modal_url=f"/customers/{row.id}/delete-modal",
                    icon="ri-delete-bin-line",
                    danger=True,
                ),
            ]
        ), ""
```

- A column callback returns the display value, or `(display, raw)`. Build the display with the cell helpers
  (`badge`, `link`, `date_cell`, `row_actions`) instead of writing HTML; escape any user text you put into `Markup`.
- A callback may be `async def`, for a column that queries the database (`await self.require_db_session().execute(...)`)
  or renders a fragment (`await render_modal(kwargs["request"], ...)`). Cells are computed one after another in the
  request's read session. Data every row needs belongs in `build_row_contexts()`, one query per page; see
  `docs/public/zh/developers/tables.md`.

### 6. The views

Replace `apps/customers/views.py`:

```python
"""Dashboard views for customers: the page, its table data and the modal create/edit/delete."""

from __future__ import annotations

from apps.customers.forms import CustomerForm
from apps.customers.models import Customer
from apps.customers.tables import CustomerTable
from oldman.db import db_manager
from oldman.i18n import gettext_lazy as _
from oldman.web import Request, json_response, render_template, router
from oldman.web.api import modal_response, modal_success_response
from oldman.web.auth import login_required
from oldman.web.security.csrf import add_csrf_token, csrf_protect
from oldman.web.shortcuts import get_object_or_404
from oldman.web.template import render_fragment

TABLE_TARGET = "#customers-table"

# The data endpoint goes through as_view(): that is where sign-in and permission checks run.
router.add_route(CustomerTable.as_view(), CustomerTable.route_path, name=CustomerTable.route_name)


@router.get("/customers", name="customers_index")
@login_required()
async def customers_index(request: Request):
    """The page: any signed-in user; add require_perm(...) when it needs a permission."""
    return await render_template(
        "customers/index.html",
        context={"page_entry": "customers", "request": request, "table": CustomerTable(request=request)},
    )


@router.get("/customers/new-modal", name="customers_create_modal")
@add_csrf_token()
@login_required()
async def customers_create_modal(request: Request):
    """The empty form, loaded into the page's remote modal."""
    async with db_manager.get_read_session() as session:
        form = CustomerForm(request=request, session=session)
        html = await form.render(action="/customers/create", form_mode="json", submit_label=_("Create customer"), validate=True)
    return modal_response(_("New customer"), html=html)


@router.post("/customers/create", name="customers_create")
@csrf_protect()
@login_required()
async def customers_create(request: Request):
    """Validate, save, then close the modal and reload the table."""
    async with db_manager.get_session() as session:
        form = CustomerForm.from_request(request, session=session)
        if not await form.validate():
            return json_response(form.to_api_response().to_dict())
        await form.save(commit=True, session=session)
    # The session commits when the block exits; answer only after that succeeded.
    return modal_success_response(_("Customer created."), table_target=TABLE_TARGET)


@router.get("/customers/<customer_id:int>/edit-modal", name="customers_edit_modal")
@add_csrf_token()
@login_required()
async def customers_edit_modal(request: Request, customer_id: int):
    """The form filled from the stored customer; 404 when it does not exist."""
    async with db_manager.get_read_session() as session:
        customer = await get_object_or_404(session, Customer, customer_id, message="Customer not found")
        form = CustomerForm(request=request, instance=customer, session=session)
        html = await form.render(action=f"/customers/{customer_id}/update", form_mode="json", submit_label=_("Save"), validate=True)
    return modal_response(_("Edit customer"), html=html)


@router.post("/customers/<customer_id:int>/update", name="customers_update")
@csrf_protect()
@login_required()
async def customers_update(request: Request, customer_id: int):
    """Load the stored row first, then let the form change only its own fields."""
    async with db_manager.get_session() as session:
        customer = await get_object_or_404(session, Customer, customer_id, message="Customer not found")
        form = CustomerForm.from_request(request, instance=customer, session=session)
        if not await form.validate():
            return json_response(form.to_api_response().to_dict())
        await form.save(commit=True, session=session)
    return modal_success_response(_("Customer saved."), table_target=TABLE_TARGET)


@router.get("/customers/<customer_id:int>/delete-modal", name="customers_delete_modal")
@add_csrf_token()
@login_required()
async def customers_delete_modal(request: Request, customer_id: int):
    """A real confirmation form: cancelling sends nothing."""
    async with db_manager.get_read_session() as session:
        customer = await get_object_or_404(session, Customer, customer_id, message="Customer not found")
        html = await render_fragment(request, "customers/delete.html", customer=customer, csrf_token=request.ctx.csrf_token)
    return modal_response(_("Delete customer"), html=html)


@router.post("/customers/<customer_id:int>/delete", name="customers_delete")
@csrf_protect()
@login_required()
async def customers_delete(request: Request, customer_id: int):
    """Delete the row, then close the modal and reload the table."""
    async with db_manager.get_session() as session:
        customer = await get_object_or_404(session, Customer, customer_id, message="Customer not found")
        await session.delete(customer)
    return modal_success_response(_("Customer deleted."), table_target=TABLE_TARGET)
```

- Every endpoint checks sign-in itself, the table's data endpoint included (through `as_view()`); hiding a button is
  not access control. A GET that renders a form adds a CSRF token (`add_csrf_token`), every POST checks it
  (`csrf_protect`).
- `page_entry` must name the page script (`setupPage("customers", …)` in `frontend/src/pages/customers.ts`).
- A failed validation answers HTTP 200 with the field errors (`form.to_api_response()`); nothing is saved.
  `modal_success_response` returns three actions in order: a success toast, close the modal, reload the table.
- The views module is loaded because the App is registered; there is no route list to edit.

### 7. The templates

Replace `templates/customers/index.html`:

```jinja
{% extends "base.html" %}
{% from "oldman/dashboard/components/page_head.html" import page_head with context %}
{% from "oldman/dashboard/components/modal.html" import modal %}

{% block title %}{{ _("Customers") }} · {{ site_name() }}{% endblock %}

{% block content %}
  <div class="om-page-section">
    {% call page_head(_("Customers")) %}
      <button
        type="button"
        class="om-button om-button-primary"
        data-om-modal-target="#customer-modal"
        data-om-modal-url="/customers/new-modal"
      ><i class="ri-add-line"></i>{{ _("New customer") }}</button>
    {% endcall %}

    {{ table.render_shell(html_id="customers-table") }}
  </div>

  {% call modal(
    "customer-modal",
    _("Customer"),
    component="modal",
    close_label=_("Close"),
    dialog_scrollable=true,
    inline_hidden_style=true,
    remote_content=true
  ) %}
    <p class="text-default-500 mb-0">{{ _("Loading...") }}</p>
  {% endcall %}
{% endblock %}
```

Add `templates/customers/delete.html`, the confirmation the delete modal loads:

```jinja
{% from "oldman/dashboard/partials/confirm.html" import confirm_body with context %}
{{ confirm_body(customer.name, _("Delete this customer?"), icon="ri-delete-bin-line", wrapper_class="mb-4") }}
<form method="post" action="/customers/{{ customer.id }}/delete" data-om-component="form" data-om-form data-om-form-mode="json">
  <input type="hidden" name="csrfmiddlewaretoken" value="{{ csrf_token }}">
  <div data-om-form-message hidden></div>
  <p data-om-form-status role="status" aria-live="polite" hidden></p>
  <div class="flex justify-end gap-2">
    <button type="button" class="om-button om-button-secondary" data-om-modal-close>{{ _("Cancel") }}</button>
    <button type="submit" class="om-button om-button-danger">{{ _("Delete customer") }}</button>
  </div>
</form>
```

The page script `frontend/src/pages/customers.ts` from `startapp` stays as it is: the table, the modal and the
forms are framework components its base page already loads.

### 8. Build, run and check it in a browser

```sh
cd frontend && pnpm build && cd ..        # also generates the icon CSS for the new ri-* icons
./run.sh dashboard static collect
./run.sh dashboard start                  # foreground; run it in the background while you test
```

Sign in, then check in a real browser:

1. Signed out, `/customers` redirects to the sign-in page; the data endpoint answers 401 to JSON requests.
2. From another page, reach Customers through the sidebar, not only by typing the URL.
3. Create a customer: the modal closes, a toast appears, the table shows the row.
4. Create another with the same email in other letter case: the email field shows the duplicate error and no row is added.
5. Edit it and save: the row shows the new values.
6. Delete, cancel: the row stays. Delete, confirm: the row is gone.
7. Check the database itself, not the toast; check the browser console for errors.

Stop the service with `./run.sh dashboard stop` only. Never use `killall`, `pkill` or kill processes by name or port.

## Access and data rules

1. The dashboard's floor is a signed-in, active account: every enabled user can sign in. A page that needs staff uses
   `staff_required()`, one that needs a permission uses `await require_perm(request, …)` (`oldman.web.auth`); a table
   overrides `check_permission` for the same. `is_staff` means "staff member", not "may use the dashboard".
2. Decide whose records these are. The example shows every customer to every signed-in user. For per-user or
   per-tenant records, narrow `get_queryset()` and load the instance to edit or delete through the same scope: never
   update a row just because the request named its id.
3. Writes use `db_manager.get_session()`, which commits when the block exits; `form.save(commit=True)` adds and
   flushes. Build the success response after the block. Reads use `db_manager.get_read_session()`.
4. Sessions and CSRF are already set up in the skeleton's service. Do not add a second CSRF scheme; GETs that render a
   form use `add_csrf_token()`, POSTs use `csrf_protect()`.
5. File fields: look at the existing storage and model-form upload support first (`docs/public/zh/developers/forms.md`).
   Without a file field, add no file handling.

## Responses: one kind per consumer

| Request | Server answers | Consumer |
| --- | --- | --- |
| A full page, or a native form post | HTML; a failed native post is HTML too | The browser |
| First load of a modal | `modal_response(title, html=...)` (title/html JSON) | The dashboard Modal |
| A JSON form save | HTTP 200 with field errors, message and ordered actions | The Form and the page's action runner |
| An HTML form save | 2xx HTML, or 422 with the form and its errors | The Form |
| Table data | An HTML fragment, or the table's own columns/rows/pagination JSON | The Table |
| A generic `data-om-action` | 2xx with actions | The page's action runner |

- Actions run in list order; if one fails, the rest stop. A committed transaction is not undone by a failed UI
  action. Do not reload the table a second time from a form-success listener.
- `replace_html` resolves its target as `action.target`, then the element's `data-om-target`, then the element itself;
  the swap as `action.swap`, then `data-om-swap`, then `inner`. Name the target when you mean a specific region.
- Business error codes are not retried and do not block the actions. 401, 403, 5xx, network failures and timeouts go
  through the shared HTTP error handling; do not dress an exception up as a field error.

The full response and action reference is `docs/public/zh/developers/responses.md`.

## Browser rules

- Pages extend the project's `BasePage` (a `DashboardPage` with the framework's component loaders). A form inside a
  modal is still the ordinary form component: no second modal-form submitter. Replace HTML through the table, modal or
  `replace_html` lifecycles, never with a bare `innerHTML` that skips unmounting and mounting.
- A remote modal opens only after its content loaded; a failed load shows the page's feedback, leaving the page
  cancels it silently. Do not add another `om:modal:error` listener.
- A page-private component or action goes into that page's script (override the async
  `handleResponseAction(action, context)`, returning true when handled), not into the global loaders. Requests use
  `page.http`; listeners, timers and subscriptions are registered on the page so it releases them.
- Verify entering the page from another page through the sidebar. If typing the URL works and the sidebar does not,
  check the main frame's page entry, that the old page unmounted and the new page was created.
- Table cells carry `data-om-table-row-id` and `data-om-column` for targeted live updates; there is no `updateCell`
  API, and editing the DOM changes only what is shown. Add server-sent events only when the user needs live data.
- A "confirm or prompt, then call the server" flow follows the full demo's `/examples/messages/feedback` page
  (`docs/public/zh/developers/frontend.md`, section on Feedback): no new dialog system, no global feedback instance.

## Reference implementation

The full demo [oldman-epg-dashboard](https://github.com/alexliyu7352/oldman-epg-dashboard) has the same pattern with
more features (filter form, HTML and JSON table modes, export, permissions by role): `apps/examples/tables.py`,
`apps/examples/forms.py`, `apps/examples/views/tables.py` and `templates/pages/examples/tables/dynamic.html`.
Walkthrough: `docs/public/zh/users/tutorial-dashboard.md`. When something is not covered here or the installed
version differs, read the implementation for that point; do not invent APIs such as `get_current_page`,
`updateCell` or a global message bus.

## Done means

List the real URL, the commands the user must run (migrations), what you verified in the browser, and what is not done.
Temporary accounts and data live in your own directories and are cleaned up; you stopped every process you started.
