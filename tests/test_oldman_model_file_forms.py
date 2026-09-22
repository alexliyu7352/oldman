"""模型文件列、上传字段与 ModelForm 保存协议测试。"""

from __future__ import annotations

import unittest
from collections.abc import AsyncIterable
from typing import Any, cast
from unittest.mock import patch

from sanic.request import File
from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from wtforms import StringField
from wtforms.validators import DataRequired

from oldman.storage import InMemoryStorage, InvalidStorageName, StorageBackendError, file_column, storages
from oldman.storage.base import StorageContent
from oldman.storage.models import _CREATED_FILES_KEY, _get_model_file_config
from oldman.web.components.forms import FileExtension, FileSize, OldmanForm, OldmanModelForm, SanicFormData, UploadField


def upload_to_owner(instance: Any, filename: str) -> str:
    """使用本次表单更新后的 owner 生成文件名。"""
    return f"owners/{instance.owner}/{filename}"


class ModelFileTestBase(DeclarativeBase):
    """隔离本文件模型 metadata。"""


class ModelFileAsset(ModelFileTestBase):
    """覆盖字符串和 callable upload_to 以及多个 Storage alias。"""

    __tablename__ = "task5_model_file_asset"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str]
    avatar: Mapped[str] = file_column(
        upload_to=upload_to_owner,
        storage="images",
        max_length=180,
        index=True,
        unique=True,
        default="owners/default.png",
        comment="owner avatar",
        info={"public": True},
    )
    contract: Mapped[str | None] = file_column(upload_to="contracts", storage="documents", nullable=True)


class AssetForm(OldmanModelForm):
    """由模型文件元数据自动生成上传字段。"""

    class Meta:
        model = ModelFileAsset
        fields = ("owner", "avatar", "contract")


class RecordingStorage(InMemoryStorage):
    """记录 Storage 收到的名称，并可模拟保存失败或重命名。"""

    def __init__(self, alias: str, *, returned_name: str | None = None, fail: bool = False) -> None:
        super().__init__(alias=alias)
        self.returned_name = returned_name
        self.fail = fail
        self.saved: list[tuple[str, bytes]] = []

    async def _save(self, name: str, content: StorageContent, *, overwrite: bool) -> str:
        if self.fail:
            raise OSError("storage unavailable")
        payload = content if isinstance(content, bytes) else await self._collect(content)
        self.saved.append((name, payload))
        if self.returned_name is not None:
            return self.returned_name
        return await super()._save(name, payload, overwrite=overwrite)

    @staticmethod
    async def _collect(content: AsyncIterable[bytes]) -> bytes:
        return b"".join([chunk async for chunk in content])


class RecordingStorageRegistry:
    """按 alias 返回测试 Storage。"""

    def __init__(self, **items: RecordingStorage) -> None:
        self.items = items
        self.used: list[str] = []

    def using(self, alias: str) -> RecordingStorage:
        self.used.append(alias)
        return self.items[alias]


class RecordingSession:
    """记录 ModelForm 对当前数据库事务的最小操作。"""

    def __init__(self) -> None:
        self.info: dict[str, Any] = {}
        self.added: list[Any] = []
        self.flush_calls = 0

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        self.flush_calls += 1


def uploaded_file(name: str, body: bytes = b"content") -> File:
    """构造 Sanic 已缓存到内存的上传文件。"""
    return File(type="application/octet-stream", body=body, name=name)


class ModelFileDeclarationTest(unittest.TestCase):
    """验证 file_column 的普通 String 列边界。"""

    def test_file_column_preserves_sqlalchemy_options_and_private_metadata(self) -> None:
        column = ModelFileAsset.__table__.c.avatar
        config = _get_model_file_config(column)
        column_type = cast(String, column.type)

        self.assertIsInstance(column_type, String)
        self.assertEqual(180, column_type.length)
        self.assertFalse(column.nullable)
        self.assertTrue(column.index)
        self.assertTrue(column.unique)
        self.assertEqual("owners/default.png", column.default.arg)
        self.assertEqual("owner avatar", column.comment)
        self.assertIs(column.info["public"], True)
        self.assertIsNotNone(config)
        assert config is not None
        self.assertEqual("images", config.storage)
        self.assertIs(config.upload_to, upload_to_owner)

    def test_file_column_validates_declaration_without_resolving_storage(self) -> None:
        with patch.object(storages, "using", side_effect=AssertionError("registry must stay lazy")):
            column = file_column(upload_to="uploads", storage="later", nullable=True)
        self.assertIsNotNone(column)

        invalid_calls = (
            ({"upload_to": "uploads", "storage": ""}, (ValueError, TypeError)),
            ({"upload_to": "uploads", "storage": "   "}, (ValueError, TypeError)),
            ({"upload_to": "uploads", "max_length": 0}, (ValueError, TypeError)),
            ({"upload_to": "uploads", "max_length": True}, (ValueError, TypeError)),
            ({"upload_to": "uploads", "max_length": "255"}, (ValueError, TypeError)),
            ({"upload_to": "uploads", "type_": String(32)}, (ValueError, TypeError)),
        )
        for kwargs, errors in invalid_calls:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(errors):
                    file_column(**kwargs)  # type: ignore[arg-type]

        reserved_key = next(key for key in ModelFileAsset.__table__.c.avatar.info if key != "public")
        with self.assertRaises((ValueError, TypeError)):
            file_column(upload_to="uploads", info={reserved_key: "override"})


class UploadFieldTest(unittest.IsolatedAsyncioTestCase):
    """验证 Sanic 文件绑定、validator 和 multipart 输出。"""

    async def test_request_files_bind_to_upload_field_and_cleaned_data(self) -> None:
        class UploadForm(OldmanForm):
            title = StringField("Title")
            attachment = UploadField("Attachment", validators=[DataRequired()])

        class Request:
            method = "POST"
            form = {"title": "Report"}
            files = {"attachment": uploaded_file("report.txt")}

        form = UploadForm.from_request(Request())

        self.assertTrue(await form.validate())
        self.assertEqual("Report", form.cleaned_data["title"])
        self.assertIs(Request.files["attachment"], form.cleaned_data["attachment"])

        empty = UploadForm(data={"title": "Report"}, files={})
        self.assertFalse(await empty.validate())
        self.assertIsNone(empty.attachment.data)

        file_only = UploadForm(files={"attachment": uploaded_file("report.txt")})
        self.assertTrue(file_only.is_bound)
        self.assertTrue(await file_only.validate())

    async def test_file_validators_check_size_and_final_suffix(self) -> None:
        class UploadForm(OldmanForm):
            attachment = UploadField(
                "Attachment",
                validators=[FileSize(4), FileExtension((".txt", "PDF"))],
            )

        valid = UploadForm(data={}, files={"attachment": uploaded_file(r"C:\fakepath\REPORT.PDF", b"1234")})
        self.assertTrue(await valid.validate())

        too_large = UploadForm(data={}, files={"attachment": uploaded_file("report.txt", b"12345")})
        self.assertFalse(await too_large.validate())
        self.assertIn("attachment", too_large.errors)

        wrong_suffix = UploadForm(data={}, files={"attachment": uploaded_file("archive.tar.gz", b"1")})
        self.assertFalse(await wrong_suffix.validate())
        self.assertIn("attachment", wrong_suffix.errors)

        empty = UploadForm(data={}, files={})
        self.assertTrue(await empty.validate())

    def test_file_validators_reject_invalid_configuration(self) -> None:
        for max_bytes in (0, -1, True, "10"):
            with self.subTest(max_bytes=max_bytes):
                with self.assertRaises((TypeError, ValueError)):
                    FileSize(max_bytes)  # type: ignore[arg-type]

        for extensions in ((), "jpg", ("",), (1,)):
            with self.subTest(extensions=extensions):
                with self.assertRaises((TypeError, ValueError)):
                    FileExtension(extensions)  # type: ignore[arg-type]

    async def test_renderer_only_adds_multipart_for_upload_fields(self) -> None:
        class PlainForm(OldmanForm):
            title = StringField("Title")

        class UploadForm(OldmanForm):
            attachment = UploadField("Attachment")

        self.assertNotIn("multipart/form-data", str(await PlainForm().render()))
        self.assertIn('enctype="multipart/form-data"', str(await UploadForm().render()))


class ModelFileFormTest(unittest.IsolatedAsyncioTestCase):
    """验证 ModelForm 文件字段映射、校验和保存顺序。"""

    async def test_model_form_maps_file_columns_and_validates_existing_value(self) -> None:
        self.assertIsInstance(AssetForm()._fields["avatar"], UploadField)
        self.assertIsInstance(AssetForm()._fields["contract"], UploadField)

        unbound = AssetForm()
        self.assertFalse(await unbound.validate())
        self.assertEqual({}, unbound.errors)
        self.assertEqual({}, unbound.cleaned_data)
        self.assertIsNone(unbound.error_message)

        missing = AssetForm(data={"owner": "alice"})
        self.assertFalse(await missing.validate())
        self.assertIn("avatar", missing.errors)
        self.assertNotIn("contract", missing.errors)

        existing = ModelFileAsset(owner="old", avatar="owners/old/avatar.png", contract=None)
        edit = AssetForm(data={"owner": "new"}, instance=existing)
        self.assertTrue(await edit.validate())

    async def test_explicit_upload_field_keeps_its_own_validators_and_the_not_null_rule(self) -> None:
        """显式声明只接管字段本身，不会取消“非空列新建必传、编辑可沿用”。"""

        class ExplicitAssetForm(OldmanModelForm):
            avatar = UploadField("Custom avatar")

            class Meta:
                model = ModelFileAsset
                fields = ("owner", "avatar")

        create_form = ExplicitAssetForm(formdata=SanicFormData({"owner": ["alice"]}))

        self.assertEqual("Custom avatar", create_form.avatar.label.text)
        self.assertEqual((), tuple(create_form.avatar.validators))
        self.assertFalse(await create_form.validate())
        self.assertEqual(["This field is required."], create_form.errors["avatar"])

        edit_form = ExplicitAssetForm(
            formdata=SanicFormData({"owner": ["alice"]}),
            instance=ModelFileAsset(owner="alice", avatar="owners/alice/avatar.png"),
        )

        self.assertTrue(await edit_form.validate())

    async def test_save_uses_new_normal_fields_safe_basename_and_storage_result(self) -> None:
        image_storage = RecordingStorage("images", returned_name="owners/alice/avatar_renamed.JPG")
        registry = RecordingStorageRegistry(images=image_storage, documents=RecordingStorage("documents"))
        session = RecordingSession()
        form = AssetForm(
            data={"owner": "alice"},
            files={"avatar": uploaded_file(r"C:\fakepath\avatar.JPG", b"image")},
            session=session,
        )
        self.assertTrue(await form.validate())

        with patch("oldman.web.components.forms.models.storages", registry):
            instance = await form.save(commit=False)

        self.assertEqual([("owners/alice/avatar.JPG", b"image")], image_storage.saved)
        self.assertEqual("owners/alice/avatar_renamed.JPG", instance.avatar)
        self.assertIsNone(instance.id)
        self.assertEqual([], session.added)
        self.assertEqual(0, session.flush_calls)
        records = session.info[_CREATED_FILES_KEY]
        self.assertEqual(1, len(records))
        self.assertIs(instance, records[0].instance)
        self.assertEqual("avatar", records[0].field_name)
        self.assertEqual("images", records[0].storage_alias)
        self.assertEqual("owners/alice/avatar_renamed.JPG", records[0].path)

    async def test_multiple_file_fields_use_independent_storage_and_preserve_missing_upload(self) -> None:
        image_storage = RecordingStorage("images")
        document_storage = RecordingStorage("documents")
        registry = RecordingStorageRegistry(images=image_storage, documents=document_storage)
        instance = ModelFileAsset(owner="old", avatar="owners/old/old.png", contract="contracts/old.pdf")
        form = AssetForm(
            data={"owner": "new"},
            files={"avatar": uploaded_file("../../new.png", b"avatar")},
            instance=instance,
            session=RecordingSession(),
        )
        self.assertTrue(await form.validate())

        with patch("oldman.web.components.forms.models.storages", registry):
            await form.save()

        self.assertEqual("owners/new/new.png", instance.avatar)
        self.assertEqual("contracts/old.pdf", instance.contract)
        self.assertEqual(["images"], registry.used)
        self.assertEqual([], document_storage.saved)

        both = AssetForm(
            data={"owner": "next"},
            files={
                "avatar": uploaded_file("next.png", b"avatar2"),
                "contract": uploaded_file("contract.pdf", b"document"),
            },
            instance=instance,
            session=RecordingSession(),
        )
        self.assertTrue(await both.validate())
        with patch("oldman.web.components.forms.models.storages", registry):
            await both.save()

        self.assertEqual("owners/next/next.png", instance.avatar)
        self.assertEqual("contracts/contract.pdf", instance.contract)
        self.assertEqual(["images", "images", "documents"], registry.used)

    async def test_storage_failure_does_not_assign_requested_name(self) -> None:
        instance = ModelFileAsset(owner="old", avatar="owners/old/old.png", contract=None)
        registry = RecordingStorageRegistry(
            images=RecordingStorage("images", fail=True),
            documents=RecordingStorage("documents"),
        )
        form = AssetForm(
            data={"owner": "new"},
            files={"avatar": uploaded_file("new.png")},
            instance=instance,
            session=RecordingSession(),
        )
        self.assertTrue(await form.validate())

        with patch("oldman.web.components.forms.models.storages", registry):
            with self.assertRaises(StorageBackendError):
                await form.save()

        self.assertEqual("owners/old/old.png", instance.avatar)
        self.assertEqual("new", instance.owner)

    async def test_commit_true_adds_and_flushes_without_committing(self) -> None:
        storage = RecordingStorage("images")
        registry = RecordingStorageRegistry(images=storage, documents=RecordingStorage("documents"))
        session = RecordingSession()
        form = AssetForm(
            data={"owner": "alice"},
            files={"avatar": uploaded_file("avatar.png")},
        )
        self.assertTrue(await form.validate())

        with patch("oldman.web.components.forms.models.storages", registry):
            instance = await form.save(commit=True, session=session)

        self.assertEqual([instance], session.added)
        self.assertEqual(1, session.flush_calls)
        self.assertFalse(hasattr(session, "commit_calls"))

    async def test_commit_true_without_session_fails_before_storage_write(self) -> None:
        storage = RecordingStorage("images")
        registry = RecordingStorageRegistry(images=storage, documents=RecordingStorage("documents"))
        form = AssetForm(
            data={"owner": "alice"},
            files={"avatar": uploaded_file("avatar.png")},
        )
        self.assertTrue(await form.validate())

        with patch("oldman.web.components.forms.models.storages", registry):
            with self.assertRaisesRegex(ValueError, "requires a session"):
                await form.save(commit=True)

        self.assertEqual([], registry.used)
        self.assertEqual([], storage.saved)

    async def test_storage_rejects_unsafe_callable_result(self) -> None:
        class UnsafeAsset(ModelFileTestBase):
            __tablename__ = "task5_unsafe_asset"

            id: Mapped[int] = mapped_column(primary_key=True)
            file: Mapped[str] = file_column(upload_to=lambda _instance, filename: f"../{filename}")

        class UnsafeForm(OldmanModelForm):
            class Meta:
                model = UnsafeAsset
                fields = ("file",)

        form = UnsafeForm(data={}, files={"file": uploaded_file("safe.txt")}, session=RecordingSession())
        self.assertTrue(await form.validate())
        registry = RecordingStorageRegistry(default=RecordingStorage("default"))

        with patch("oldman.web.components.forms.models.storages", registry):
            with self.assertRaises(InvalidStorageName):
                await form.save()


if __name__ == "__main__":
    unittest.main()
