"""Forms shared by every site that manages the configured User model: login, filter, create/edit, password."""

from __future__ import annotations

import inspect
from functools import cache
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy import inspect as sqlalchemy_inspect
from wtforms import BooleanField, DateTimeLocalField, PasswordField, SelectField, StringField
from wtforms.validators import DataRequired, InputRequired, Length, Optional, Regexp

from oldman.auth import normalize_email, user_identity_matches
from oldman.db import explicit_primary_key_column, session_dialect
from oldman.i18n import gettext, gettext_lazy
from oldman.web.components.forms import (
    CheckboxWidget,
    DateTimePickerWidget,
    EmailField,
    FieldLayout,
    FormLayout,
    Row,
    TailwindForm,
    TailwindModelForm,
    TailwindTableFilterForm,
)
from oldman.web.components.forms.models import model_field_for_column

PASSWORD_PATTERN = r"^(?=.*[A-Za-z])(?=.*\d).{8,128}$"
PASSWORD_MESSAGE = cast(
    str,
    gettext_lazy("Password must be 8-128 characters and include letters and numbers"),
)


class UserPasswordForm(TailwindForm):
    """Validate a new password through the shared Web account policy."""

    password = PasswordField(
        cast(str, gettext_lazy("New Password")),
        validators=[
            DataRequired(),
            Length(min=8, max=128),
            Regexp(PASSWORD_PATTERN, message=PASSWORD_MESSAGE),
        ],
        render_kw={
            "required": True,
            "minlength": 8,
            "maxlength": 128,
            "pattern": PASSWORD_PATTERN,
            "autocomplete": "new-password",
        },
    )
    confirm_password = PasswordField(
        cast(str, gettext_lazy("Confirm Password")),
        validators=[DataRequired(), Length(min=8, max=128)],
        render_kw={
            "required": True,
            "minlength": 8,
            "maxlength": 128,
            "autocomplete": "new-password",
        },
    )

    field_layout = (
        FieldLayout("password", "md:col-span-12"),
        FieldLayout("confirm_password", "md:col-span-12"),
    )

    async def clean(self) -> None:
        """Require the confirmation to match the new password."""
        if self.password.data != self.confirm_password.data:
            self.add_error("confirm_password", gettext("Passwords do not match"))


class SessionPasswordForm(UserPasswordForm):
    """A signed-in user changing their own password, which takes the current one as well.

    `UserPasswordForm` is what an administrator uses to set *another* account's password,
    and what the reset flow uses once a mailed token has already proved the request; neither
    can ask for a password the requester does not have. This one can, and must: its caller
    is holding a session, and a session is exactly what an attacker steals.
    """

    current_password = PasswordField(
        cast(str, gettext_lazy("Current Password")),
        validators=[DataRequired()],
        render_kw={
            "required": True,
            "maxlength": 128,
            "autocomplete": "current-password",
        },
    )

    field_layout = (
        FieldLayout("current_password", "md:col-span-12"),
        FieldLayout("password", "md:col-span-12"),
        FieldLayout("confirm_password", "md:col-span-12"),
    )


BOOLEAN_FILTER_CHOICES = (
    ("", cast(str, gettext_lazy("All"))),
    ("true", cast(str, gettext_lazy("Yes"))),
    ("false", cast(str, gettext_lazy("No"))),
)
EDITABLE_USER_FIELDS = ("username", "email", "display_name", "is_active", "is_staff", "is_superuser")


class LoginForm(TailwindForm):
    """Collect login credentials plus the remember-me choice."""

    username = StringField(
        cast(str, gettext_lazy("Username")),
        id="username",
        validators=[DataRequired()],
        render_kw={
            "required": True,
            "autocomplete": "username",
            "placeholder": gettext_lazy("Enter username"),
            "autofocus": True,
        },
    )
    password = PasswordField(
        cast(str, gettext_lazy("Password")),
        id="password-input",
        validators=[DataRequired()],
        render_kw={
            "required": True,
            "autocomplete": "current-password",
            "placeholder": gettext_lazy("Enter password"),
        },
    )
    remember_me = BooleanField(cast(str, gettext_lazy("Remember me")), id="remember-me", widget=CheckboxWidget())


class UserFilterForm(TailwindTableFilterForm):
    """Filter a configured User table: search, the three flags and a last-login range."""

    q = StringField(
        cast(str, gettext_lazy("Search")),
        render_kw={"type": "search", "placeholder": gettext_lazy("Search username, email, display name")},
    )
    is_active = SelectField(cast(str, gettext_lazy("Active")), choices=BOOLEAN_FILTER_CHOICES, validators=[Optional()])
    is_staff = SelectField(cast(str, gettext_lazy("Staff")), choices=BOOLEAN_FILTER_CHOICES, validators=[Optional()])
    is_superuser = SelectField(cast(str, gettext_lazy("Superuser")), choices=BOOLEAN_FILTER_CHOICES, validators=[Optional()])
    last_login_from = DateTimeLocalField(
        cast(str, gettext_lazy("Last Login From")),
        format="%Y-%m-%dT%H:%M",
        validators=[Optional()],
        widget=DateTimePickerWidget(date_format="Y-m-d\\TH:i"),
    )
    last_login_to = DateTimeLocalField(
        cast(str, gettext_lazy("Last Login To")),
        format="%Y-%m-%dT%H:%M",
        validators=[Optional()],
        widget=DateTimePickerWidget(date_format="Y-m-d\\TH:i"),
    )

    # Inline bar: search, three prefixed selects, one "last login" range control.
    # The widths only matter when a project switches layout_style to "grid".
    layout = FormLayout(
        FieldLayout("q", "lg:col-span-6 md:col-span-12"),
        FieldLayout("is_active", "lg:col-span-2 md:col-span-4"),
        FieldLayout("is_staff", "lg:col-span-2 md:col-span-4"),
        FieldLayout("is_superuser", "lg:col-span-2 md:col-span-4"),
        Row(
            "last_login_from",
            "last_login_to",
            width="lg:col-span-6 md:col-span-12",
            as_range=True,
            label=cast(str, gettext_lazy("Last Login")),
        ),
    )


class UserModelForm(TailwindModelForm):
    """Shared validation and persistence for the configured User model (create and edit)."""

    current_user_id: int | None = None
    confirm_password: Any
    email: Any
    password: Any
    username: Any

    async def clean_username(self) -> str:
        """Validate username uniqueness before a database constraint can fail."""
        username = str(self.username.data or "").strip()
        if self.session is None or not username:
            return username
        result = await self.session.execute(select(self.model).where(self.model.username == username))
        existing = result.scalar_one_or_none()
        if existing is not None and not self.is_same_instance(existing):
            self.add_error("username", gettext("Username already exists"))
        return username

    async def clean_email(self) -> str | None:
        """Validate optional email uniqueness before persistence; EmailField already settled the spelling."""
        email = normalize_email(str(self.email.data or ""))
        if email is None:
            return None
        if self.session is None:
            return email
        # Legacy rows may still carry mixed case; compare lowercased so they count as taken too.
        result = await self.session.execute(select(self.model).where(func.lower(self.model.email) == email))
        existing = result.scalar_one_or_none()
        if existing is not None and not self.is_same_instance(existing):
            self.add_error("email", gettext("Email already exists"))
        return email

    async def clean_explicit_primary_key(self) -> Any:
        """Validate a user-supplied primary key before database persistence."""
        primary_key = list(self.mapper.primary_key)[0]
        field_name = primary_key.key
        value = self._fields[field_name].data
        if self.session is None or value is None or value == "":
            return value
        result = await self.session.execute(select(self.model).where(getattr(self.model, field_name) == value))
        existing = result.scalar_one_or_none()
        if existing is not None and not self.is_same_instance(existing):
            self.add_error(
                field_name,
                gettext("%(field)s already exists", field=self._fields[field_name].label.text),
            )
        return value

    async def clean(self) -> None:
        """Protect the current user and validate password confirmation."""
        await super().clean()
        if self.instance is not None and user_identity_matches(self.instance, self.current_user_id):
            if self.cleaned_data.get("is_active") is False:
                self.add_error("is_active", gettext("cannot disable current user"))
            if self.cleaned_data.get("is_staff") is False:
                self.add_error("is_staff", gettext("cannot remove current user staff access"))
            if self.cleaned_data.get("is_superuser") is False:
                self.add_error("is_superuser", gettext("cannot remove current user superuser access"))
        if "confirm_password" in self._fields and self.password.data != self.confirm_password.data:
            self.add_error("confirm_password", gettext("Passwords do not match"))

    async def save(self, *, commit: bool = False, session: Any = None) -> Any:
        """Persist profile fields and hash the create-form password."""
        user = await super().save(commit=False)
        if bool(getattr(user, "is_superuser", False)):
            user.is_staff = True
        if "password" in self._fields:
            user.set_password(str(self.password.data or ""))
        if commit:
            active_session = session or self.session
            if active_session is None:
                raise ValueError("save(commit=True) requires a session")
            active_session.add(user)
            flush_result = active_session.flush()
            if inspect.isawaitable(flush_result):
                await flush_result
        return user

    def is_same_instance(self, other: Any) -> bool:
        """Compare rows without assuming the primary key is named ``id``."""
        if self.instance is None:
            return False
        try:
            primary_key = list(self.mapper.primary_key)
            return len(primary_key) == 1 and getattr(other, primary_key[0].key) == getattr(self.instance, primary_key[0].key)
        except (AttributeError, TypeError):
            return other is self.instance

    @property
    def mapper(self):
        """Return the mapped model metadata used by identity comparisons."""
        return sqlalchemy_inspect(self.model)


@cache
def user_edit_form_class(user_model: type[Any]) -> type[UserModelForm]:
    """A ModelForm for editing the configured User model's profile and flags."""
    return _user_model_form_class(user_model, create=False, include_explicit_primary_key=False)


def user_create_form_class(user_model: type[Any], *, session: Any = None, dialect: Any = None) -> type[UserModelForm]:
    """A ModelForm for creating a User: profile, flags, password plus confirmation."""
    mapper = sqlalchemy_inspect(user_model)
    resolved_dialect = dialect or session_dialect(session)
    include_primary_key = explicit_primary_key_column(mapper, dialect=resolved_dialect) is not None
    return _user_model_form_class(
        user_model,
        create=True,
        include_explicit_primary_key=include_primary_key,
    )


@cache
def _user_model_form_class(
    user_model: type[Any],
    *,
    create: bool,
    include_explicit_primary_key: bool,
) -> type[UserModelForm]:
    mapper = sqlalchemy_inspect(user_model)
    model_fields = list(EDITABLE_USER_FIELDS)
    field_layout: list[FieldLayout] = [
        FieldLayout("username", "md:col-span-6"),
        FieldLayout("email", "md:col-span-6"),
        FieldLayout("display_name", "md:col-span-6"),
    ]
    fields: dict[str, Any] = {
        "username": StringField(
            cast(str, gettext_lazy("Username")),
            validators=[DataRequired(), Length(max=150)],
            render_kw={"required": True, "maxlength": 150},
        ),
        "email": EmailField(
            cast(str, gettext_lazy("Email")),
            validators=[Optional()],
        ),
        "display_name": StringField(
            cast(str, gettext_lazy("Display Name")),
            validators=[Optional(), Length(max=150)],
            render_kw={"maxlength": 150},
        ),
        "is_active": BooleanField(cast(str, gettext_lazy("Active")), description=cast(str, gettext_lazy("Can sign in"))),
        "is_staff": BooleanField(cast(str, gettext_lazy("Staff")), description=cast(str, gettext_lazy("Can open the dashboard"))),
        "is_superuser": BooleanField(cast(str, gettext_lazy("Superuser")), description=cast(str, gettext_lazy("Has every permission"))),
    }
    primary_key = list(mapper.primary_key)[0]
    if not create and primary_key.key in model_fields:
        # Session identity is backed by the persisted primary key.  Editing it
        # would orphan the active session and bypass the self-protection
        # rules, so custom protocol models may only collect it during create.
        model_fields.remove(primary_key.key)
        fields.pop(primary_key.key, None)
        field_layout = [item for item in field_layout if item.name != primary_key.key]
    if create:
        if include_explicit_primary_key:
            field_name = primary_key.key
            if field_name not in fields:
                fields[field_name] = model_field_for_column(primary_key, mapper=mapper)
                model_fields.insert(0, field_name)
                field_layout.insert(0, FieldLayout(field_name, "md:col-span-6"))
            validators = list(fields[field_name].kwargs.get("validators", []))
            if fields[field_name].field_class is not BooleanField and not any(
                isinstance(validator, (DataRequired, InputRequired)) for validator in validators
            ):
                fields[field_name].kwargs["validators"] = [InputRequired(), *validators]
            if not hasattr(UserModelForm, f"clean_{field_name}"):
                fields[f"clean_{field_name}"] = UserModelForm.clean_explicit_primary_key
        fields.update(
            password=PasswordField(
                cast(str, gettext_lazy("Password")),
                validators=[
                    DataRequired(),
                    Length(min=8, max=128),
                    Regexp(PASSWORD_PATTERN, message=PASSWORD_MESSAGE),
                ],
                render_kw={
                    "required": True,
                    "minlength": 8,
                    "maxlength": 128,
                    "pattern": PASSWORD_PATTERN,
                    "autocomplete": "new-password",
                },
            ),
            confirm_password=PasswordField(
                cast(str, gettext_lazy("Confirm Password")),
                validators=[DataRequired(), Length(min=8, max=128)],
                render_kw={"required": True, "minlength": 8, "maxlength": 128, "autocomplete": "new-password"},
            ),
        )
        field_layout.extend(
            (
                FieldLayout("password", "md:col-span-6"),
                FieldLayout("confirm_password", "md:col-span-6"),
            )
        )
    field_layout.extend(
        (
            # The three switch cards share one row under the text fields.
            FieldLayout("is_active", "md:col-span-4 md:col-start-1"),
            FieldLayout("is_staff", "md:col-span-4"),
            FieldLayout("is_superuser", "md:col-span-4"),
        )
    )
    fields["field_layout"] = tuple(field_layout)
    fields["Meta"] = type("Meta", (), {"model": user_model, "fields": model_fields})
    suffix = "CreateForm" if create else "EditForm"
    return type(f"{user_model.__name__}{suffix}", (UserModelForm,), fields)


__all__ = [
    "BOOLEAN_FILTER_CHOICES",
    "EDITABLE_USER_FIELDS",
    "LoginForm",
    "PASSWORD_MESSAGE",
    "PASSWORD_PATTERN",
    "SessionPasswordForm",
    "UserFilterForm",
    "UserModelForm",
    "UserPasswordForm",
    "user_create_form_class",
    "user_edit_form_class",
]
