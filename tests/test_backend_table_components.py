"""后端 Table 组件合同。"""

from __future__ import annotations

import asyncio
import json
import unittest
from dataclasses import dataclass
from typing import Any, cast

from markupsafe import Markup
from sqlalchemy import ForeignKey, Integer, String, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from oldman.web.api.enums import ApiErrorCode
from oldman.web.components.tables import BaseTableView, Column, SQLAlchemyTableView, TableRenderer, TableResult
from oldman.web.components.tables.views import TableInvalidRequest


@dataclass
class Channel:
    name: str


@dataclass
class Programme:
    id: int
    title: str
    channel: Channel
    hits: int


class DemoProgramTable(BaseTableView):
    route_name = "program_table"
    route_path = "/programmes/table"
    columns = [
        "id",
        ("Title", "title", "get_column_title_data"),
        ("Channel", "channel.name"),
        ("Hits", "hits"),
    ]
    search_fields = ["title", "channel.name"]
    ordering = ["title"]
    page_size = 2
    page_size_options = [1, 2, 5]
    max_page_size = 5

    async def get_object_list(self):
        return [
            Programme(id=1, title="Zoo News", channel=Channel("BBC"), hits=3),
            Programme(id=2, title="Alpha Show", channel=Channel("CNN"), hits=8),
            Programme(id=3, title="Beta News", channel=Channel("BBC"), hits=5),
        ]

    async def filter_channel(self, rows, value, table_request):
        return [row for row in rows if row.channel.name == value]

    def get_column_title_data(self, row, **kwargs):
        return f'<a href="/programmes/{row.id}">{row.title}</a>', row.title


class DictProgramTable(BaseTableView):
    route_name = "dict_program_table"
    route_path = "/dict-programmes/table"
    columns = ["id", ("Title", "title"), ("Channel", "channel.name"), ("Hits", "hits")]
    search_fields = ["title", "channel.name"]
    ordering = ["title"]
    page_size = 2
    page_size_options = [1, 2, 5]
    max_page_size = 5

    async def get_object_list(self):
        return [
            {"id": 1, "title": "Zoo News", "channel": {"name": "BBC"}, "hits": 3},
            {"id": 2, "title": "Alpha Show", "channel": {"name": "CNN"}, "hits": 8},
            {"id": 3, "title": "Beta News", "channel": {"name": "BBC"}, "hits": 5},
        ]

    async def filter_channel(self, rows, value, table_request):
        return [row for row in rows if row["channel"]["name"] == value]


class SelectableProgramTable(DemoProgramTable):
    selectable = True


class SlugProgramTable(DemoProgramTable):
    row_id_field = "title"


class DeniedProgramTable(DemoProgramTable):
    async def check_auth(self, request) -> bool:
        return False


class TableColumnContractTest(unittest.TestCase):
    def test_column_normalization_matches_document_contract(self) -> None:
        class DemoTable(BaseTableView):
            route_name = "demo_table"
            route_path = "/demo/table"
            columns = [
                "id",
                ("Title", "title", "get_column_title_data"),
                ("Action", None, "get_column_action_data"),
                Column("created_at", label="Created"),
            ]
            search_fields = ["title"]

        columns = DemoTable().get_columns()

        self.assertEqual([column.name for column in columns], ["id", "title", "action", "created_at"])
        self.assertEqual(columns[0].field_path, "id")
        self.assertTrue(columns[0].sortable)
        self.assertFalse(columns[0].searchable)
        self.assertTrue(columns[1].searchable)
        self.assertFalse(columns[2].sortable)
        self.assertFalse(columns[2].searchable)
        self.assertIsNone(columns[2].field_path)
        self.assertFalse(hasattr(columns[0], "sort_expression"))

    def test_column_sortable_is_internal_metadata(self) -> None:
        with self.assertRaises(TypeError):
            Column("title", sortable=False)  # type: ignore[call-arg]


class TableStructuredDataTest(unittest.TestCase):
    def test_structured_data_query_supports_search_filter_sort_and_page_size(self) -> None:
        table = DemoProgramTable()
        request = table.build_table_request(
            make_request(
                args={
                    "q": "news",
                    "filter.channel": "BBC",
                    "sort": "-hits",
                    "page_size": "1",
                    "page": "1",
                }
            ),
            route_kwargs={},
        )

        result = asyncio.run(table.query_result(request))

        self.assertEqual(result.total, 3)
        self.assertEqual(result.filtered_total, 2)
        self.assertEqual(result.page_size, 1)
        self.assertEqual([row.id for row in result.rows], [3])

    def test_dict_data_reuses_the_same_lifecycle(self) -> None:
        table = DictProgramTable()
        request = table.build_table_request(
            make_request(
                args={
                    "q": "news",
                    "filter.channel": "BBC",
                    "sort": "-hits",
                    "page_size": "1",
                    "page": "1",
                }
            ),
            route_kwargs={},
        )

        result = asyncio.run(table.query_result(request))

        self.assertEqual(result.filtered_total, 2)
        self.assertEqual([row["id"] for row in result.rows], [3])

    def test_sort_uses_the_column_field_path_instead_of_its_public_name(self) -> None:
        class TeamProgramTable(DemoProgramTable):
            columns = (Column("team", "Team", field_path="channel.name"),)

        table = TeamProgramTable()
        request = table.build_table_request(
            make_request(args={"sort": "team", "page_size": "5"}),
            route_kwargs={},
        )

        result = asyncio.run(table.query_result(request))

        self.assertEqual([row.id for row in result.rows], [1, 3, 2])

    def test_table_request_normalizes_sanic_multivalue_filter_args(self) -> None:
        request = DemoProgramTable().build_table_request(
            make_sanic_args_request(args={"filter.channel": ["BBC"], "page_size": ["1"]}),
            route_kwargs={},
        )

        self.assertEqual(request.filters, {"channel": "BBC"})
        self.assertEqual(request.page_size, 1)

    def test_table_request_rejects_invalid_page_and_page_size(self) -> None:
        table = DemoProgramTable()
        for args in (
            {"page": "abc"},
            {"page": "0"},
            {"page_size": "abc"},
            {"page_size": "0"},
            {"page_size": "6"},
        ):
            with self.subTest(args=args), self.assertRaises(TableInvalidRequest):
                table.build_table_request(make_request(args=args), route_kwargs={})

    def test_render_shell_and_fragment_keep_source_protocol(self) -> None:
        table = DemoProgramTable()
        shell = str(asyncio.run(table.render_shell()))
        request = table.build_table_request(make_request(args={"page_size": "1"}), route_kwargs={})
        result = TableResult(
            rows=[Programme(id=1, title="Zoo News", channel=Channel("BBC"), hits=3)],
            row_contexts=[{}],
            total=3,
            filtered_total=3,
            page=1,
            page_size=1,
        )
        rendered_fragment = asyncio.run(table.render_html_fragment(request, result))
        fragment = str(rendered_fragment)

        self.assertIsInstance(rendered_fragment, Markup)
        self.assertIn('data-om-component="table"', shell)
        self.assertIn('data-om-table-src="/programmes/table"', shell)
        self.assertIn("data-om-table-loading", shell)
        self.assertIn("data-om-table-error", shell)
        self.assertNotIn("data-om-table-format", shell)
        self.assertNotIn("data-om-table-page-size-control", shell)
        self.assertNotIn("data-om-table-summary", shell)
        self.assertIn("data-om-table-row", fragment)
        self.assertIn('data-om-table-row-id="1"', fragment)
        self.assertIn("data-om-table-page-size-control", fragment)
        self.assertIn("data-om-table-summary", fragment)
        self.assertIn('data-om-table-page="2"', fragment)

    def test_table_rendering_delegates_to_renderer_class(self) -> None:
        class MinimalRenderer(TableRenderer):
            async def render_shell(self, *, route_kwargs, html_id=None, show_search=True, data_format="html"):
                return Markup(f'<section data-custom-table="1" data-format="{data_format}"></section>')

        class CustomRenderedTable(DemoProgramTable):
            renderer_class = MinimalRenderer

        self.assertEqual(
            str(asyncio.run(CustomRenderedTable().render_shell(data_format="json"))),
            '<section data-custom-table="1" data-format="json"></section>',
        )

    def test_json_shell_outputs_format_footer_and_selectable_head(self) -> None:
        shell = str(asyncio.run(SelectableProgramTable().render_shell(data_format="json")))

        self.assertIn('data-om-table-format="json"', shell)
        self.assertIn('data-om-table-empty-message="No records found."', shell)
        self.assertIn("data-om-table-page-size-control", shell)
        self.assertIn("data-om-table-summary", shell)
        self.assertIn("data-om-table-pagination", shell)
        self.assertIn("data-om-table-initial-loading", shell)
        self.assertIn("data-om-table-select-all", shell)

    def test_render_shell_rejects_unknown_data_format(self) -> None:
        with self.assertRaisesRegex(ValueError, "data_format must be 'html' or 'json'"):
            asyncio.run(DemoProgramTable().render_shell(data_format="csv"))  # type: ignore[arg-type]

    def test_selectable_table_outputs_selection_without_polluting_columns(self) -> None:
        table = SelectableProgramTable()
        request = table.build_table_request(make_request(), route_kwargs={})
        result = asyncio.run(table.query_result(request))

        html = str(asyncio.run(table.render_html_fragment(request, result)))
        payload = table.render_json_payload(request, result)

        self.assertIn("data-om-table-select-all", html)
        self.assertIn("data-om-table-select-row", html)
        self.assertEqual([column["name"] for column in payload["columns"]], ["id", "title", "channel.name", "hits"])
        self.assertNotIn("selection", payload["rows"][0]["cells"])

    def test_plain_table_can_select_another_stable_row_field(self) -> None:
        table = SlugProgramTable()
        request = table.build_table_request(make_request(args={"page_size": "1"}), route_kwargs={})
        result = asyncio.run(table.query_result(request))

        html = str(asyncio.run(table.render_html_fragment(request, result)))
        payload = table.render_json_payload(request, result)

        self.assertIn('data-om-table-row-id="Alpha Show"', html)
        self.assertEqual("Alpha Show", payload["rows"][0]["data"]["id"])

    def test_sqlalchemy_table_uses_primary_key_or_explicit_stable_field(self) -> None:
        class Base(DeclarativeBase):
            pass

        class SingleKey(Base):
            __tablename__ = "single_key_row_identity"

            slug: Mapped[str] = mapped_column(String, primary_key=True)

        class CompositeKey(Base):
            __tablename__ = "composite_key_row_identity"

            group: Mapped[str] = mapped_column(String, primary_key=True)
            name: Mapped[str] = mapped_column(String, primary_key=True)

        class SingleTable(SQLAlchemyTableView):
            model = SingleKey

        class CompositeTable(SQLAlchemyTableView):
            model = CompositeKey
            row_id_field = "name"

        self.assertEqual("news", SingleTable().get_row_id(SingleKey(slug="news")))
        self.assertEqual("b", CompositeTable().get_row_id(CompositeKey(group="a", name="b")))

    def test_sqlalchemy_relationship_sort_uses_explicit_path_or_local_foreign_key(self) -> None:
        class Base(DeclarativeBase):
            pass

        class Team(Base):
            __tablename__ = "table_sort_team"

            id: Mapped[int] = mapped_column(Integer, primary_key=True)
            name: Mapped[str] = mapped_column(String)

        class Project(Base):
            __tablename__ = "table_sort_project"

            id: Mapped[int] = mapped_column(Integer, primary_key=True)
            team_id: Mapped[int] = mapped_column(ForeignKey("table_sort_team.id"))
            team: Mapped[Team] = relationship()

        class ProjectTable(SQLAlchemyTableView):
            model = Project
            columns = (Column("team", "Team", field_path="team.name"),)

        class DefaultProjectTable(SQLAlchemyTableView):
            model = Project
            columns = (Column("team", "Team"),)

        table = ProjectTable()
        request = table.build_table_request(make_request(args={"sort": "team"}), route_kwargs={})

        ordered_query = asyncio.run(table.apply_ordering(select(Project), request))
        sql = str(ordered_query)

        self.assertIn("JOIN table_sort_team", sql)
        self.assertIn("ORDER BY table_sort_team.name ASC", sql)

        default_table = DefaultProjectTable()
        default_request = default_table.build_table_request(
            make_request(args={"sort": "-team"}),
            route_kwargs={},
        )
        default_query = asyncio.run(default_table.apply_ordering(select(Project), default_request))

        self.assertIn("ORDER BY table_sort_project.team_id DESC", str(default_query))

    def test_permission_denied_uses_json_error_contract(self) -> None:
        response = asyncio.run(DeniedProgramTable().get(make_request(headers={"accept": "application/json"})))
        body = response.body
        assert body is not None
        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(response.status, 403)
        self.assertEqual(payload["error_code"], ApiErrorCode.PERMISSION_DENIED)

    def test_table_result_requires_row_contexts_to_match_rows(self) -> None:
        with self.assertRaises(ValueError):
            TableResult(rows=[object()], row_contexts=[])


def make_request(*, args: dict[str, str] | None = None, headers: dict[str, str] | None = None):
    class Headers(dict):
        def get(self, key, default=None):
            return super().get(key.lower(), default)

    return type(
        "TableRequestStub",
        (),
        {
            "args": dict(args or {}),
            "headers": Headers({(key or "").lower(): value for key, value in (headers or {}).items()}),
            "app": None,
        },
    )()


def make_sanic_args_request(*, args: dict[str, list[str]], headers: dict[str, str] | None = None):
    class Args(dict):
        def get(self, key, default=None):
            value = super().get(key, default)
            return value[0] if isinstance(value, list) and value else value

    request = make_request(headers=headers)
    cast(Any, request).args = Args(args)
    return request


if __name__ == "__main__":
    unittest.main()
