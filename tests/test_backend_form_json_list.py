"""JSONListField 的后端绑定、校验、渲染和 ModelForm 保存测试。"""

from __future__ import annotations

import unittest

from sqlalchemy import Text, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from wtforms import StringField
from wtforms.validators import Length

from oldman.web.components.forms import JSONListField, TailwindForm, TailwindModelForm


class JSONListBase(DeclarativeBase):
    """隔离本文件的 SQLAlchemy metadata。"""


class StreamProfile(JSONListBase):
    """用 Text 保存标量 JSON 列表的最小模型。"""

    __tablename__ = "test_form_json_list_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    sources_json: Mapped[str] = mapped_column(Text, default="[]")


class StreamProfileForm(TailwindModelForm):
    """验证显式 JSONListField 的 ModelForm 行为。"""

    sources_json = JSONListField(
        StringField("Source URL", validators=[Length(min=3)]),
        min_entries=1,
        max_entries=2,
    )

    class Meta(TailwindModelForm.Meta):
        """绑定测试模型。"""

        model = StreamProfile
        fields = ("sources_json",)


class JSONListForm(TailwindForm):
    """验证普通 Form 保留 Python list。"""

    sources = JSONListField(StringField("Source", validators=[Length(min=3)]), min_entries=1, max_entries=2)


class BackendFormJSONListTest(unittest.IsolatedAsyncioTestCase):
    """验证 JSONListField 的公共协议。"""

    async def test_decodes_model_text_and_empty_values(self) -> None:
        """Text JSON 解码成 list，空值统一视为空列表。"""
        self.assertEqual(["one", "two"], StreamProfileForm(instance=StreamProfile(sources_json='["one", "two"]')).sources_json.data)

        for value in (None, "", "[]", []):
            with self.subTest(value=value):
                field = StreamProfileForm(instance=StreamProfile(sources_json=value)).sources_json
                self.assertEqual([None], field.data)

    async def test_rejects_invalid_model_json_and_non_list_values(self) -> None:
        """损坏或非 list 的模型值进入唯一顶部错误，不伪装成子字段错误。"""
        for value in ("{broken", '{"source": "one"}', '[{"source": "one"}]'):
            with self.subTest(value=value):
                form = StreamProfileForm(instance=StreamProfile(sources_json=value))
                self.assertIsNotNone(form.error_message)
                self.assertEqual({}, form.errors)

    async def test_validates_count_indices_children_and_prefix(self) -> None:
        """提交数量、索引和子字段错误不会被 WTForms 静默截断或丢失。"""
        valid = JSONListForm(
            data={"profile-sources-0": "one", "profile-sources-1": "two"},
            prefix="profile",
        )
        self.assertTrue(await valid.validate())
        self.assertEqual(["one", "two"], valid.cleaned_data["sources"])
        self.assertEqual(["profile-sources-0", "profile-sources-1"], [entry.name for entry in valid.sources])

        invalid_child = JSONListForm(data={"sources-0": "x"})
        self.assertFalse(await invalid_child.validate())
        self.assertEqual({"sources-0": ["Field must be at least 3 characters long."]}, invalid_child.errors)

        for data in (
            {"sources-0": "one", "sources-1": "two", "sources-2": "three"},
            {"sources--1": "one"},
        ):
            with self.subTest(data=data):
                form = JSONListForm(data=data)
                self.assertFalse(await form.validate())
                self.assertIsNotNone(form.error_message)

    async def test_renders_rows_template_and_reindex_hooks(self) -> None:
        """Renderer 输出现有行、模板和前端重排所需的完整 hook。"""
        form = JSONListForm(data={"profile-sources-0": "one"}, prefix="profile")
        html = str(await form.render())

        self.assertIn('data-om-component="form-repeater"', html)
        self.assertIn('data-om-repeater-name="profile-sources"', html)
        self.assertIn('name="profile-sources-0"', html)
        self.assertIn('for="id_profile-sources-0"', html)
        self.assertIn('aria-describedby="id_profile-sources-0-error"', html)
        self.assertIn('data-om-error-for="profile-sources-0"', html)
        self.assertIn("data-om-repeater-template", html)
        self.assertIn("__index__", html)

    async def test_model_form_stably_encodes_and_reloads_text(self) -> None:
        """显式 JSONListField 保存紧凑 JSON，重新查询后仍能解码为 list。"""
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(JSONListBase.metadata.create_all)

            async with session_factory() as session:
                form = StreamProfileForm(data={"sources_json-0": "one", "sources_json-1": "two"}, session=session)
                self.assertTrue(await form.validate())
                saved = await form.save(commit=True)
                await session.commit()
                saved_id = saved.id

            async with session_factory() as session:
                loaded = (await session.execute(select(StreamProfile).where(StreamProfile.id == saved_id))).scalar_one()
                self.assertEqual('["one","two"]', loaded.sources_json)
                self.assertEqual(["one", "two"], StreamProfileForm(instance=loaded).sources_json.data)
        finally:
            await engine.dispose()


if __name__ == "__main__":
    unittest.main()
