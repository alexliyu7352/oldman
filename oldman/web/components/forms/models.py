"""ModelForm 基类。"""

from __future__ import annotations

import inspect
from typing import Any, Self

from sqlalchemy import Boolean as SQLABoolean
from sqlalchemy import Date as SQLADate
from sqlalchemy import DateTime as SQLADateTime
from sqlalchemy import Integer as SQLAInteger
from sqlalchemy import SmallInteger as SQLASmallInteger
from sqlalchemy import String as SQLAString
from sqlalchemy import Text as SQLAText
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.exc import NoInspectionAvailable
from wtforms import (
    BooleanField,
    DateField,
    DateTimeLocalField,
    IntegerField,
    StringField,
    TextAreaField,
)
from wtforms.validators import InputRequired

from oldman.storage.models import _get_model_file_config, _resolve_upload_name, register_created_file
from oldman.storage.registry import storages

from .base import OldmanForm, SanicFormData
from .choices import ModelChoice
from .fields import JSONListField, ModelChoiceField, UploadField


def humanize_model_field_name(name: str) -> str:
    """把模型字段名转换为默认表单标签。"""
    return name.replace("_", " ").strip().title()


def model_field_for_column(
    column: Any,
    *,
    mapper: Any = None,
    label: str | None = None,
    description: str | None = None,
    model_choice: ModelChoice | None = None,
) -> Any:
    """把 SQLAlchemy Column 转换为 WTForms 字段定义。

    标签和帮助文字的优先级：显式参数（Meta.labels / Meta.help_texts）> 列的 ``info["label"]`` /
    ``info["help_text"]`` > 字段名转写。
    """
    column_info = getattr(column, "info", None) or {}
    label = label or column_info.get("label")
    description = description or column_info.get("help_text")
    if _get_model_file_config(column) is not None:
        field_kwargs: dict[str, Any] = {}
        if description:
            field_kwargs["description"] = description
        return UploadField(label or humanize_model_field_name(str(column.key)), **field_kwargs)
    if getattr(column, "foreign_keys", None):
        return model_choice_field_for_foreign_key(column, mapper=mapper, label=label, description=description, model_choice=model_choice)

    field_label = label or humanize_model_field_name(str(column.key))
    field_kwargs: dict[str, Any] = {}
    if description:
        field_kwargs["description"] = description
    column_type = column.type
    if model_column_requires_input(column, checkbox=isinstance(column_type, SQLABoolean)):
        field_kwargs["validators"] = [InputRequired()]

    if isinstance(column_type, SQLABoolean):
        return BooleanField(field_label, **field_kwargs)
    if isinstance(column_type, SQLADateTime):
        return DateTimeLocalField(field_label, format="%Y-%m-%dT%H:%M", **field_kwargs)
    if isinstance(column_type, SQLADate):
        return DateField(field_label, format="%Y-%m-%d", **field_kwargs)
    if isinstance(column_type, (SQLAInteger, SQLASmallInteger)):
        return IntegerField(field_label, **field_kwargs)
    if isinstance(column_type, SQLAText):
        return TextAreaField(field_label, **field_kwargs)
    if isinstance(column_type, SQLAString):
        render_kw: dict[str, Any] = {}
        if getattr(column_type, "length", None):
            render_kw["maxlength"] = column_type.length
        if render_kw:
            field_kwargs["render_kw"] = render_kw
        return StringField(field_label, **field_kwargs)
    raise ValueError(f"Unsupported model field type for {column.key}: {column_type!r}")


def model_choice_field_for_foreign_key(
    column: Any,
    *,
    mapper: Any,
    label: str | None = None,
    description: str | None = None,
    model_choice: ModelChoice | None = None,
) -> ModelChoiceField:
    """把 SQLAlchemy 外键列转换为本地 ModelChoiceField。"""
    if mapper is None:
        raise ValueError(f"{column.key} is a foreign key but mapper is not available")
    target_model, target_field = resolve_foreign_key_target(column, mapper)
    label_field = default_choice_label_field(target_model, fallback=target_field)
    choice = model_choice or ModelChoice(model=target_model, value_field=target_field, label_field=label_field, order_by=(label_field,))
    field_kwargs: dict[str, Any] = {}
    if description:
        field_kwargs["description"] = description
    if model_column_requires_input(column):
        field_kwargs["validators"] = [InputRequired()]
    return ModelChoiceField(
        label or humanize_model_field_name(str(column.key)),
        model_choice=choice,
        coerce=model_choice_coerce(column),
        **field_kwargs,
    )


def model_column_requires_input(column: Any, *, checkbox: bool = False) -> bool:
    """Return whether an included mapped field requires submitted input."""
    if checkbox:
        return False
    table = getattr(column, "table", None)
    if table is not None and getattr(table, "autoincrement_column", None) is column:
        return False
    return (
        not bool(getattr(column, "nullable", True))
        and getattr(column, "default", None) is None
        and getattr(column, "server_default", None) is None
        and getattr(column, "identity", None) is None
        and getattr(column, "computed", None) is None
    )


def resolve_foreign_key_target(column: Any, mapper: Any) -> tuple[type[Any], str]:
    """根据外键目标表在当前 SQLAlchemy registry 中找到映射模型。"""
    foreign_key = next(iter(column.foreign_keys))
    target_column = foreign_key.column
    for related_mapper in mapper.registry.mappers:
        if related_mapper.local_table is target_column.table:
            return related_mapper.class_, str(target_column.key)
    raise ValueError(f"Cannot resolve foreign key target model for {column.key}")


def default_choice_label_field(model: type[Any], *, fallback: str) -> str:
    """选择本地 choices 的默认显示字段。"""
    for name in ("name", "title", "label"):
        if hasattr(model, name):
            return name
    return fallback


def model_choice_coerce(column: Any) -> Any:
    """根据外键列类型选择提交值转换函数。"""
    if isinstance(column.type, SQLABoolean):
        return coerce_boolean_choice
    if isinstance(column.type, (SQLAInteger, SQLASmallInteger)):
        return int
    return str


def coerce_boolean_choice(value: Any) -> bool:
    """Coerce a Boolean select value without applying Python string truthiness."""
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean choice: {value!r}")


class OldmanModelForm(OldmanForm):
    """Oldman 无主题模型表单基类。"""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """子类创建时根据 Meta.fields 注入缺失的模型字段。"""
        super().__init_subclass__(**kwargs)
        cls.inject_model_fields()

    def __init__(self, *args: Any, instance: Any = None, **kwargs: Any) -> None:
        """初始化模型表单并把实例作为初始对象。"""
        if "obj" in kwargs:
            raise TypeError("ModelForm uses instance=..., not obj=...")
        self.instance = instance
        if instance is not None:
            kwargs["obj"] = instance
        super().__init__(*args, **kwargs)
        self.model = self.get_model()
        self.model_fields = self.get_model_fields()

    @classmethod
    def from_request(
        cls,
        request,
        *,
        instance: Any = None,
        session: Any = None,
        initial: dict[str, Any] | None = None,
        prefix: str = "",
        csrf_token: str = "",
        select_secret_key: str = "",
        **kwargs: Any,
    ) -> Self:
        """从 Sanic 请求创建模型表单实例。"""
        if "obj" in kwargs:
            raise TypeError("ModelForm uses instance=..., not obj=...")
        is_submission = request.method.upper() in {"POST", "PUT", "PATCH"}
        files = getattr(request, "files", None) if is_submission else None
        formdata = SanicFormData(getattr(request, "form", None), files) if is_submission else None
        return cls(
            formdata=formdata,
            instance=instance,
            request=request,
            session=session,
            initial=initial,
            files=files,
            prefix=prefix,
            csrf_token=csrf_token,
            select_secret_key=select_secret_key,
            **kwargs,
        )

    @classmethod
    def from_query(
        cls,
        request,
        *,
        instance: Any = None,
        session: Any = None,
        initial: dict[str, Any] | None = None,
        prefix: str = "",
        **kwargs: Any,
    ) -> Self:
        """从 Sanic 查询参数创建模型筛选表单实例。"""
        if "obj" in kwargs:
            raise TypeError("ModelForm uses instance=..., not obj=...")
        return cls(
            formdata=SanicFormData(getattr(request, "args", None)),
            instance=instance,
            request=request,
            session=session,
            initial=initial,
            prefix=prefix,
            **kwargs,
        )

    @classmethod
    def get_model(cls) -> type[Any]:
        """返回 Meta.model 声明的模型类。"""
        meta = getattr(cls, "Meta", None)
        model = getattr(meta, "model", None)
        if model is None:
            raise ValueError(f"{cls.__name__}.Meta.model is required")
        return model

    @classmethod
    def get_model_fields(cls) -> tuple[str, ...]:
        """返回 Meta.fields 声明的可编辑字段。"""
        meta = getattr(cls, "Meta", None)
        fields = getattr(meta, "fields", None)
        if fields is None or fields == "__all__":
            raise ValueError(f"{cls.__name__}.Meta.fields must be an explicit list")
        return tuple(str(field) for field in fields)

    @classmethod
    def inject_model_fields(cls) -> None:
        """把 SQLAlchemy 模型字段映射为 WTForms 字段。"""
        meta = getattr(cls, "Meta", None)
        model = getattr(meta, "model", None)
        fields = getattr(meta, "fields", None)
        if model is None or not fields or fields == "__all__":
            return
        try:
            mapper = sqlalchemy_inspect(model)
        except NoInspectionAvailable:
            return

        labels = dict(getattr(meta, "labels", {}) or {})
        help_texts = dict(getattr(meta, "help_texts", {}) or {})
        model_choices = dict(getattr(meta, "model_choices", {}) or {})
        for field_name in fields:
            name = str(field_name)
            if hasattr(cls, name):
                continue
            column = mapper.columns.get(name)
            if column is None:
                continue
            setattr(
                cls,
                name,
                model_field_for_column(
                    column,
                    mapper=mapper,
                    label=labels.get(name),
                    description=help_texts.get(name),
                    model_choice=model_choices.get(name),
                ),
            )

    async def validate(self, extra_validators: dict[str, Any] | None = None) -> bool:
        """校验普通字段，并补充非空文件列的“新建必传、编辑可沿用”规则。"""
        valid = await super().validate(extra_validators=extra_validators)
        if not self.is_bound:
            return False
        mapper = sqlalchemy_inspect(self.model)
        # 这条规则看模型列和字段类型，不看字段是框架自动生成的还是表单自己声明的：
        # 显式声明 UploadField（为了加尺寸/扩展名校验或 render_kw）不该让规则失效。
        for field_name in self.model_fields:
            column = mapper.columns.get(field_name)
            field = self._fields.get(field_name)
            if column is None or not isinstance(field, UploadField) or _get_model_file_config(column) is None:
                continue
            if column.nullable or field.data is not None:
                continue
            if self.instance is not None and getattr(self.instance, field_name, None):
                continue
            self.add_error(field_name, field.gettext("This field is required."))
            self._cleaned_data.pop(field_name, None)
            valid = False
        self._validation_succeeded = valid and not self.errors and self.error_message is None
        return self._validation_succeeded

    def populate_obj(self, obj: Any) -> None:
        """把 cleaned_data 中允许的字段写回模型实例。"""
        mapper = sqlalchemy_inspect(self.model)
        cleaned_data = self.cleaned_data
        for field_name in self.model_fields:
            column = mapper.columns.get(field_name)
            field = self._fields.get(field_name)
            if column is not None and _get_model_file_config(column) is not None and isinstance(field, UploadField):
                continue
            if field_name in cleaned_data:
                value = cleaned_data[field_name]
                setattr(obj, field_name, field.encode(value) if isinstance(field, JSONListField) else value)

    async def save(self, *, commit: bool = False, session: Any = None) -> Any:
        """保存模型表单并返回模型实例，事务提交由外部负责。"""
        if not self._validation_succeeded:
            raise ValueError("ModelForm.save() requires a successfully validated form")
        instance = self.instance or self.model()
        self.populate_obj(instance)
        active_session = session or self.session
        if commit and active_session is None:
            raise ValueError("save(commit=True) requires a session")
        mapper = sqlalchemy_inspect(self.model)
        cleaned_data = self.cleaned_data
        for field_name in self.model_fields:
            column = mapper.columns.get(field_name)
            field = self._fields.get(field_name)
            config = _get_model_file_config(column) if column is not None else None
            if config is None or not isinstance(field, UploadField):
                continue
            uploaded = cleaned_data.get(field_name)
            if uploaded is None:
                continue
            requested_name = _resolve_upload_name(config, instance, uploaded.name)
            stored_name = await storages.using(config.storage).save(requested_name, uploaded.body)
            if active_session is not None:
                register_created_file(active_session, instance, field_name, config.storage, stored_name)
            setattr(instance, field_name, stored_name)
        await self.before_save(instance)
        if commit:
            assert active_session is not None
            active_session.add(instance)
            flush_result = active_session.flush()
            if inspect.isawaitable(flush_result):
                await flush_result
        self.instance = instance
        return instance

    async def before_save(self, instance: Any) -> None:
        """派生字段的钩子：实例已经装好表单值和上传文件名，还没有写库。

        子类在这里维护模型自己的派生列（创建/更新时间、小写查找列、拼出来的 key……），
        不用重写 `save()`，也就不用复制 session、add 和 flush 那几行。
        """
        del instance


__all__ = ["OldmanModelForm", "humanize_model_field_name", "model_field_for_column"]
