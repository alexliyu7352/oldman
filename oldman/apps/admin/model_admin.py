"""ModelAdmin base classes."""

from __future__ import annotations

import base64
import binascii
import datetime as dt
from collections.abc import Sequence
from typing import Any, cast
from urllib.parse import quote, unquote

from markupsafe import Markup, escape
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.schema import Column
from sqlalchemy.sql.sqltypes import String, Text
from wtforms import BooleanField
from wtforms.validators import InputRequired

from oldman.apps.admin.crud import coerce_value
from oldman.apps.admin.permissions import has_admin_permission
from oldman.auth import validate_user_model
from oldman.db import ModelMetadata, explicit_primary_key_column, resolve_model_display_names, session_dialect
from oldman.i18n import gettext, gettext_lazy
from oldman.web.auth.tables import user_cell_value, user_row_actions
from oldman.web.components.forms.models import model_field_for_column
from oldman.web.components.tables import Column as WebTableColumn
from oldman.web.components.tables import badge, date_cell
from oldman.web.components.tables.views import normalize_display_value
from oldman.web.session import SessionData


class InvalidAdminObjectId(ValueError):
    """Raised when a route segment cannot represent a model primary key."""


ENCODED_STRING_KEY_PREFIX = "~b~"

class ModelAdmin:
    """SQLAlchemy/SQLModel metadata-driven Admin CRUD controller."""

    list_display: Sequence[str] = ()
    search_fields: Sequence[str] = ()
    readonly_fields: Sequence[str] = ()
    ordering: Sequence[str] = ()
    exclude: Sequence[str] = ()
    page_size = 20
    table_selectable = False
    # Table toolbar tools (columns / density / export); export needs export_formats.
    table_toolbar: Sequence[str] = ("columns", "density", "export")
    export_formats: Sequence[str] = ("csv",)
    empty_message = cast(str, gettext_lazy("No records found."))
    require_superuser = False
    # Consumer-defined icons and utilities are supplied by the app-owned Admin
    # extension bundle passed to install_admin(); built-in defaults stay in the wheel.
    add_button_icon = "ri-add-line"
    form_back_label: str | None = None
    form_card_classes = "max-w-3xl"
    show_form_card_header = True

    def __init__(self, model: type[Any], site: Any = None) -> None:
        self.model = model
        self.site = site
        self.mapper = sa_inspect(model)
        self._form_classes: dict[tuple[str, ...], type[Any]] = {}

    @property
    def model_name(self) -> str:
        """Return model class name."""
        return self.model.__name__

    def get_model_metadata(self) -> ModelMetadata | None:
        """Return Registry metadata when this AdminSite has a bound App Registry."""
        resolver = getattr(self.site, "get_model_metadata", None)
        return cast(
            ModelMetadata | None,
            resolver(self.model) if callable(resolver) else None,
        )

    @property
    def verbose_name(self) -> Any:
        """Return human-readable singular name."""
        metadata = self.get_model_metadata()
        if metadata is not None:
            return metadata.verbose_name
        return resolve_model_display_names(self.model)[0]

    @property
    def verbose_name_plural(self) -> Any:
        """Return human-readable plural name."""
        metadata = self.get_model_metadata()
        if metadata is not None:
            return metadata.verbose_name_plural
        return resolve_model_display_names(self.model)[1]

    @property
    def model_path(self) -> str:
        """Return URL-safe model path."""
        return getattr(self.model, "__tablename__", self.model_name.lower())

    def get_primary_key_column(self) -> Column[Any]:
        """Return the single-column primary key used by built-in CRUD."""
        primary_key = list(self.mapper.primary_key)
        if len(primary_key) != 1:
            raise ValueError(f"{self.model_name} Admin requires exactly one primary key column")
        return primary_key[0]

    def get_columns(self) -> list[Column[Any]]:
        """Return mapped table columns."""
        excluded = set(self.exclude)
        return [column for column in self.mapper.columns if column.key not in excluded]

    def get_list_display(self) -> tuple[str, ...]:
        """Return columns shown in list pages."""
        if self.list_display:
            return tuple(self.list_display)

        names = [self.get_primary_key_column().key]
        for column in self.get_columns():
            if column.key in names or column.key in {"password_hash"}:
                continue
            names.append(column.key)
            if len(names) >= 5:
                break
        return tuple(names)

    def get_search_fields(self) -> tuple[str, ...]:
        """Return searchable text fields."""
        if self.search_fields:
            return tuple(self.search_fields)
        return tuple(column.key for column in self.get_columns() if is_text_column(column) and column.key not in {"password_hash"})

    def get_table_columns(self) -> tuple[object, ...]:
        """Return shared Table column declarations for the list page."""
        return tuple(self.get_list_display())

    def get_readonly_fields(self) -> tuple[str, ...]:
        """Return readonly fields."""
        return tuple(self.readonly_fields)

    def get_ordering(self) -> tuple[str, ...]:
        """Return default ordering."""
        if self.ordering:
            return tuple(self.ordering)
        return (self.get_primary_key_column().key,)

    def get_form_class(self, *, create: bool = True, dialect: Any = None) -> type[Any]:
        """Return a generated form class backed by the shared Oldman renderer."""
        from oldman.web.components.forms import TailwindModelForm

        primary_key = self.get_primary_key_column()
        explicit_primary_key = explicit_primary_key_column(self.mapper, dialect=dialect) if create else None
        readonly = set(self.get_readonly_fields())
        field_names = tuple(
            column.key
            for column in self.get_columns()
            if column.key not in readonly and (column is not primary_key or column is explicit_primary_key)
        )
        if explicit_primary_key is not None and explicit_primary_key.key not in field_names:
            explicit_primary_key = None
        if field_names in self._form_classes:
            return self._form_classes[field_names]

        meta = type("Meta", (), {"model": self.model, "fields": field_names})
        attributes: dict[str, Any] = {"Meta": meta}
        if explicit_primary_key is not None:
            field_name = explicit_primary_key.key
            primary_key_field = model_field_for_column(explicit_primary_key, mapper=self.mapper)
            validators = list(primary_key_field.kwargs.get("validators", []))
            if primary_key_field.field_class is not BooleanField and not any(
                isinstance(validator, InputRequired) for validator in validators
            ):
                primary_key_field.kwargs["validators"] = [InputRequired(), *validators]
            attributes[field_name] = primary_key_field

            async def clean_explicit_primary_key(form: Any) -> Any:
                value = coerce_value(explicit_primary_key, form._fields[field_name].data)
                if form.session is None or value is None or value == "":
                    return value
                existing = await form.session.get(self.model, value)
                if existing is not None:
                    form.add_error(field_name, f"{form._fields[field_name].label.text} already exists")
                return value

            attributes[f"clean_{field_name}"] = clean_explicit_primary_key
        form_class = type(f"{self.model_name}AdminForm", (TailwindModelForm,), attributes)
        self._form_classes[field_names] = form_class
        return form_class

    def build_form(self, request: Any, *, instance: Any | None = None, session: Any = None):
        """Bind the generated shared ModelForm to an Admin request."""
        return self.get_form_class(
            create=instance is None,
            dialect=session_dialect(session),
        ).from_request(request, instance=instance, session=session)

    def get_edit_extra_buttons(self, instance: Any, admin_prefix: str) -> Markup:
        """Return optional shared Form action controls for an edit page."""
        del instance, admin_prefix
        return Markup("")

    def get_list_card_title(self) -> str:
        """Return the list card title as one translatable message."""
        return f"{self.verbose_name_plural} List"

    def get_add_button_label(self) -> str:
        """Return the add button label as one translatable message."""
        return f"New {self.verbose_name}"

    def get_delete_label(self) -> str:
        """Return the delete page action label as one translatable message."""
        return f"Delete {self.verbose_name}"

    def get_form_document_title(self, instance: Any | None) -> str:
        """Return the document title for the ordinary create/edit page."""
        del instance
        return self.verbose_name

    def get_form_page_title(self, instance: Any | None) -> str:
        """Return the visible heading for the ordinary create/edit page."""
        del instance
        return self.verbose_name

    def get_form_card_title(self, instance: Any | None) -> str:
        """Return the optional form-card heading."""
        return f"{'Edit' if instance is not None else 'New'} {self.verbose_name}"

    def get_form_submit_label(self, instance: Any | None) -> str:
        """Return the ordinary create/edit submit label."""
        return "Save changes" if instance is not None else "Create"

    def row_value(self, instance: Any, field_name: str) -> Any:
        """Return a display value for a list cell."""
        return normalize_display_value(getattr(instance, field_name, None))

    def table_cell_value(self, instance: Any, field_name: str, *, admin_prefix: str) -> Any:
        """Return a field display value for the shared Admin Table.

        Booleans render as a Yes/No badge and dates as a readable timestamp whose
        raw cell value stays ISO 8601; everything else keeps the normalised value.
        """
        del admin_prefix
        value = getattr(instance, field_name, None)
        if isinstance(value, bool):
            return badge(gettext("Yes") if value else gettext("No"), "success" if value else "secondary")
        if isinstance(value, dt.datetime):
            return date_cell(value)
        if isinstance(value, dt.date):
            return date_cell(value, date_format="%Y-%m-%d")
        return self.row_value(instance, field_name)

    def table_action_html(self, instance: Any, *, admin_prefix: str) -> Markup:
        """Return row actions for the shared Admin Table."""
        url = self.get_object_url(instance, admin_prefix=admin_prefix, action="edit")
        return Markup('<a class="om-button om-button-sm om-button-light" href="{}">{}</a>').format(
            escape(url),
            escape(gettext("Edit")),
        )

    def object_pk(self, instance: Any) -> Any:
        """Return the object primary key value."""
        return getattr(instance, self.get_primary_key_column().key)

    def get_object_url(self, instance: Any, *, admin_prefix: str, action: str | None = None) -> str:
        """Build a canonical Admin URL from an object's encoded primary-key segment."""
        segment = encode_admin_path_segment(self.object_pk(instance))
        base_url = f"{admin_prefix.rstrip('/')}/{self.model_path}/{segment}"
        return f"{base_url}/{action}" if action else base_url

    async def get_object(self, session: AsyncSession, object_id: Any) -> Any | None:
        """Return one object by primary key."""
        primary_key = self.get_primary_key_column()
        try:
            decoded_object_id = decode_admin_path_segment(object_id)
            coerced_object_id = coerce_value(primary_key, decoded_object_id)
        except (TypeError, ValueError, OverflowError) as exc:
            raise InvalidAdminObjectId(str(object_id)) from exc
        try:
            return await session.get(self.model, coerced_object_id)
        except OverflowError as exc:
            raise InvalidAdminObjectId(str(object_id)) from exc
        except StatementError as exc:
            if isinstance(exc.orig, OverflowError):
                raise InvalidAdminObjectId(str(object_id)) from exc
            raise

    async def save_model(self, session: AsyncSession, instance: Any) -> Any:
        """Persist a model instance."""
        session.add(instance)
        await session.flush()
        return instance

    async def delete_model(self, session: AsyncSession, instance: Any) -> None:
        """Delete a model instance."""
        await session.delete(instance)
        await session.flush()

    def has_view_permission(self, request: Any) -> bool:
        """Return whether request may view this model."""
        return has_admin_permission(request, require_superuser=self.require_superuser)

    def has_add_permission(self, request: Any) -> bool:
        """Return whether request may add this model."""
        return self.has_view_permission(request)

    def has_change_permission(self, request: Any) -> bool:
        """Return whether request may change this model."""
        return self.has_view_permission(request)

    def has_delete_permission(self, request: Any) -> bool:
        """Return whether request may delete this model."""
        return self.has_view_permission(request)


class AdminUserModelAdmin(ModelAdmin):
    """Complete user manager for the configured Admin user model protocol."""

    readonly_fields = ("password_hash", "last_login_at", "created_at", "updated_at")
    exclude = ("password_hash",)
    ordering = ("username",)
    page_size = 10
    table_selectable = True
    empty_message = cast(str, gettext_lazy("No users found."))
    add_button_icon = "ri-user-add-line"
    form_back_label = cast(str, gettext_lazy("Users"))
    form_card_classes = ""
    show_form_card_header = False

    @property
    def verbose_name(self) -> str:
        """Keep the source user-manager singular label independent of model class name."""
        return cast(str, gettext_lazy("User"))

    @property
    def verbose_name_plural(self) -> str:
        """Keep the source user-manager plural label independent of model class name."""
        return cast(str, gettext_lazy("Users"))

    def get_list_card_title(self) -> str:
        """Keep the source user list card title extractable as one message."""
        return cast(str, gettext_lazy("Users List"))

    def get_add_button_label(self) -> str:
        """Keep the source user add action extractable as one message."""
        return cast(str, gettext_lazy("New User"))

    def get_delete_label(self) -> str:
        """Keep the source user delete action extractable as one message."""
        return cast(str, gettext_lazy("Delete User"))

    def get_form_page_title(self, instance: Any | None) -> str:
        """Mirror the source create/edit page heading."""
        return cast(str, gettext_lazy("Edit User")) if instance is not None else cast(str, gettext_lazy("New User"))

    def get_form_submit_label(self, instance: Any | None) -> str:
        """Keep the source user form's shared default submit copy."""
        del instance
        return cast(str, gettext_lazy("Save"))

    def __init__(self, model: type[Any], site: Any = None) -> None:
        validate_user_model(model)
        super().__init__(model, site)

    def get_list_display(self) -> tuple[str, ...]:
        """Restore the source user profile and status columns."""
        fields = ("username", "email", "display_name", "is_active", "is_staff", "is_superuser", "last_login_at")
        return tuple(name for name in fields if hasattr(self.model, name))

    def get_search_fields(self) -> tuple[str, ...]:
        """Search the source user identity and profile fields."""
        return tuple(name for name in ("username", "email", "display_name") if hasattr(self.model, name))

    def get_table_columns(self) -> tuple[object, ...]:
        """Keep the source user-management header contract."""
        labels = {
            "username": gettext("Username"),
            "email": gettext("Email"),
            "display_name": gettext("Display Name"),
            "is_active": gettext("Status"),
            "is_staff": gettext("Staff"),
            "is_superuser": gettext("Superuser"),
            "last_login_at": gettext("Last Login"),
        }
        return tuple(WebTableColumn(name=name, label=labels[name], field_path=name) for name in self.get_list_display())

    def build_filter_form(self, request: Any) -> Any | None:
        """Bind the shared Admin user filter form to the list query."""
        from oldman.web.auth.forms import UserFilterForm

        return UserFilterForm.from_query(request)

    def build_form(self, request: Any, *, instance: Any | None = None, session: Any = None):
        """Use dedicated create/edit forms without exposing password hashes."""
        from oldman.web.auth.forms import user_create_form_class, user_edit_form_class

        form_class = user_create_form_class(self.model, session=session) if instance is None else user_edit_form_class(self.model)
        form = form_class.from_request(request, instance=instance, session=session)
        form.current_user_id = request_user_id(request)
        return form

    def build_password_form(self, request: Any, *, session: Any = None):
        """Bind the shared password-policy form."""
        from oldman.web.auth.forms import UserPasswordForm

        return UserPasswordForm.from_request(request, session=session)

    def get_form_success_payload(self, instance: Any, *, created: bool, admin_prefix: str) -> dict[str, Any]:
        """Preserve the source user Form redirect, toast and notification contract."""
        username = str(getattr(instance, "username", self.verbose_name))
        return {
            "message": gettext("User created") if created else gettext("User saved"),
            "url": self.get_object_url(instance, admin_prefix=admin_prefix, action="edit"),
            "notification": {
                "title": gettext("User created") if created else gettext("User saved"),
                "description": (
                    gettext("%(username)s can now access the dashboard.", username=username)
                    if created
                    else gettext("%(username)s profile was updated.", username=username)
                ),
                "tone": "success" if created else "primary",
                "icon": "ri-user-add-line" if created else "ri-settings-3-line",
                "href": f"{admin_prefix}/{self.model_path}",
                "time": gettext("Just now"),
            },
        }

    def table_cell_value(self, instance: Any, field_name: str, *, admin_prefix: str) -> Any:
        """Render source-compatible identity links, status badges and login state."""
        value = user_cell_value(instance, field_name, edit_url=self.get_object_url(instance, admin_prefix=admin_prefix, action="edit"))
        if value is not None:
            return value
        return super().table_cell_value(instance, field_name, admin_prefix=admin_prefix)

    def table_action_html(self, instance: Any, *, admin_prefix: str) -> Markup:
        """Expose edit, password, status and delete through the shared Dropdown."""
        return user_row_actions(
            instance,
            edit_url=self.get_object_url(instance, admin_prefix=admin_prefix, action="edit"),
            password_modal_url=self.get_object_url(instance, admin_prefix=admin_prefix, action="password-modal"),
            status_modal_url=self.get_object_url(instance, admin_prefix=admin_prefix, action="status-modal"),
            delete_modal_url=self.get_object_url(instance, admin_prefix=admin_prefix, action="delete-modal"),
        )

    def change_password(self, instance: Any, raw_password: str) -> None:
        """Replace a password through the configured user model protocol."""
        instance.set_password(raw_password)

    def set_active(self, instance: Any, is_active: bool, *, current_user_id: int | None) -> None:
        """Apply the source self-disable protection."""
        from oldman.auth import set_user_active

        set_user_active(instance, is_active, current_user_id=current_user_id)

    def validate_delete(self, instance: Any, *, current_user_id: int | None) -> None:
        """Protect the current user and every superuser from deletion."""
        from oldman.auth import validate_user_delete

        validate_user_delete(instance, current_user_id=current_user_id)


def request_user_id(request: Any) -> int | None:
    """Return the integer user identity stored in the current SessionData."""
    session = getattr(getattr(request, "ctx", None), "session", None)
    return session.user_id if isinstance(session, SessionData) else None


def is_text_column(column: Column[Any]) -> bool:
    """Return whether a column is text-searchable."""
    return isinstance(column.type, (String, Text))


def encode_admin_path_segment(value: Any) -> str:
    """Percent-encode one primary-key path segment, including a literal slash."""
    raw_value = str(value)
    if isinstance(value, str) and (
        raw_value in {".", ".."}
        or "%" in raw_value
        or raw_value.startswith(ENCODED_STRING_KEY_PREFIX)
    ):
        encoded = base64.urlsafe_b64encode(raw_value.encode("utf-8")).decode("ascii").rstrip("=")
        return f"{ENCODED_STRING_KEY_PREFIX}{encoded}"
    return quote(raw_value, safe="")


def decode_admin_path_segment(value: Any) -> str:
    """Decode the single percent-encoded segment supplied by Sanic routing."""
    encoded_value = str(value)
    if encoded_value.startswith(ENCODED_STRING_KEY_PREFIX):
        payload = encoded_value.removeprefix(ENCODED_STRING_KEY_PREFIX)
        padding = "=" * (-len(payload) % 4)
        try:
            return base64.b64decode(payload + padding, altchars=b"-_", validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ValueError("invalid encoded Admin string identity") from exc
    return unquote(encoded_value)
