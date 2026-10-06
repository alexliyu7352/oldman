"""后端 Table 组件合同。"""

from __future__ import annotations

import asyncio
import json
import unittest
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Literal, cast

from jinja2 import DictLoader, Environment
from markupsafe import Markup
from sqlalchemy import ForeignKey, Integer, String, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from oldman.web.api.enums import ApiErrorCode
from oldman.web.components.tables import BaseTableView, Column, SQLAlchemyTableView, TableRenderer, TableResult
from oldman.web.components.tables.request import TableRequest
from oldman.web.components.tables.views import TableInvalidRequest
from oldman.web.template import template_globals


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
    async def check_auth(self, table_request) -> bool:
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

    def test_build_row_contexts_feeds_both_the_page_and_the_export(self) -> None:
        class RankedTable(DictProgramTable):
            export_formats = ("csv",)
            ordering = ["id"]
            columns = ["id", Column("rank", label="Rank", field_path=None, callback="get_column_rank_data")]
            batches: list[int] = []

            async def build_row_contexts(self, rows: Sequence[object]) -> list[Mapping[str, object]]:
                # One lookup for the whole batch, the way a per-row COUNT would be aggregated in a single query.
                self.batches.append(len(rows))
                return [{"rank": index + 1} for index, _row in enumerate(rows)]

            def get_column_rank_data(self, row, row_context, **kwargs):
                return row_context["rank"]

        table = RankedTable()
        page = asyncio.run(table.query_result(table.build_table_request(make_request(args={"page_size": "2"}), route_kwargs={})))
        self.assertEqual([context["rank"] for context in page.row_contexts], [1, 2])

        response = asyncio.run(table.get(make_request(args={"export": "csv"})))
        rows = (response.body or b"").decode("utf-8").lstrip("\ufeff").splitlines()
        self.assertEqual(rows, ["Id,Rank", "1,1", "2,2", "3,3"])
        self.assertEqual(table.batches, [2, 3])

    def test_base_filters_shape_the_total_so_an_empty_page_is_not_a_filtered_one(self) -> None:
        class ScopedTable(DictProgramTable):
            async def apply_base_filters(self, rows, table_request):
                return [row for row in rows if cast(Any, row)["hits"] > 100]

        table = ScopedTable()
        result = asyncio.run(table.query_result(table.build_table_request(make_request(), route_kwargs={})))
        self.assertEqual((result.total, result.filtered_total, list(result.rows)), (0, 0, []))

        # Nothing exists in scope, so the fragment must not tell the user to reset filters they never set.
        fragment = str(asyncio.run(table.render_html_fragment(table.build_table_request(make_request(), route_kwargs={}), result)))
        self.assertIn("data-om-table-empty-state", fragment)
        self.assertNotIn("data-om-table-empty-filtered", fragment)
        self.assertNotIn("data-om-table-empty-reset", fragment)

    def test_a_filter_narrows_within_the_base_filters_and_never_widens_them(self) -> None:
        """A visible filter on the field the base filters fix cannot reach rows they leave out."""

        class BbcOnlyTable(DictProgramTable):
            async def apply_base_filters(self, rows, table_request):
                return [row for row in rows if cast(Any, row)["channel"]["name"] == "BBC"]

        table = BbcOnlyTable()
        request = table.build_table_request(make_request(args={"filter.channel": "CNN"}), route_kwargs={})

        result = asyncio.run(table.query_result(request))

        self.assertEqual((2, 0, []), (result.total, result.filtered_total, list(result.rows)))

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
        self.assertIn('data-om-column-label="Title"', fragment)
        self.assertIn('data-om-column-label="Channel"', fragment)
        self.assertIn("data-om-table-page-size-control", fragment)
        self.assertIn('<option value="1" selected>1</option>', fragment)
        self.assertIn('<option value="2">2</option>', fragment)
        self.assertIn("data-om-table-summary", fragment)
        self.assertIn("Showing 1", fragment)
        self.assertIn("of 3 entries", fragment)
        self.assertLess(fragment.index("data-om-table-page-size-control"), fragment.index("data-om-table-summary"))
        self.assertIn('data-om-table-page="2"', fragment)

    def test_render_shell_starts_from_the_initial_filters_and_query(self) -> None:
        table = DemoProgramTable(initial_filters={"channel_id": 12, "date_from": "2026-06-01"}, initial_query="BBC News")

        html = str(asyncio.run(table.render_shell()))

        self.assertIn('data-om-filter-channel-id="12"', html)
        self.assertIn('data-om-filter-date-from="2026-06-01"', html)
        self.assertRegex(html, r'<input [^>]*data-om-table-param="q"[^>]*value="BBC News"')

    def test_render_shell_restores_sort_and_page_size_from_the_list_url(self) -> None:
        """Coming back to the list (from an edit page, say) shows the sort and page size its URL kept."""
        html = str(asyncio.run(DemoProgramTable(request=make_request(args={"sort": "hits", "page_size": "5"})).render_shell()))

        self.assertIn('data-om-table-initial-sort="hits"', html)
        self.assertIn('data-om-table-page-size="5"', html)
        self.assertIn('data-om-table-page-size-options="1,2,5"', html)

    def test_render_shell_draws_the_head_and_a_loading_row_before_the_first_fetch(self) -> None:
        html = str(asyncio.run(DemoProgramTable().render_shell()))

        self.assertIn("data-om-table-partial data-om-initial-table-partial", html)
        self.assertIn('class="om-table-shell"', html)
        self.assertIn('data-om-table-sort="title"', html[html.index("<thead>") : html.index("</thead>")])
        self.assertIn("data-om-table-initial-loading", html[html.index("data-om-table-body") :])
        self.assertIn("Loading...", html)

    def test_page_size_options_accept_what_int_accepts(self) -> None:
        class Seven:
            def __int__(self) -> int:
                return 7

        table = DemoProgramTable()
        table.page_size_options = cast(Any, [Seven()])
        table.max_page_size = 10

        self.assertIn("7", TableRenderer(table).resolve_page_size_options())

    def test_a_fragment_falls_back_to_the_class_page_size_options(self) -> None:
        """A request instance that shadows the options with an empty list still offers the class's choices."""
        table = DemoProgramTable()
        table.page_size_options = []
        request = table.build_table_request(make_request(args={"page_size": "1"}), route_kwargs={})
        result = TableResult(rows=[], row_contexts=[], total=3, filtered_total=3, page=1, page_size=1)

        html = str(asyncio.run(table.render_html_fragment(request, result)))

        self.assertIn('<option value="1" selected>1</option>', html)
        self.assertIn('<option value="2">2</option>', html)
        self.assertIn('<option value="5">5</option>', html)

    def test_head_offers_sort_controls_with_column_metadata(self) -> None:
        html = str(asyncio.run(DemoProgramTable().render_html_head()))

        self.assertIn('class="sort sorting"', html)
        self.assertIn('data-om-table-sort="title"', html)
        self.assertIn("data-om-table-sort-icon", html)
        self.assertIn("ri-arrow-up-down-line", html)
        self.assertIn('data-om-column-type="string"', html)

    def test_pagination_lists_only_a_window_of_pages_for_a_large_result(self) -> None:
        result = TableResult(rows=[], row_contexts=[], total=700, filtered_total=700, page=350, page_size=1)

        html = asyncio.run(DemoProgramTable().render_html_pagination(result))

        self.assertIn('data-om-table-page="1"', html)
        self.assertIn('data-om-table-page="350"', html)
        self.assertIn('data-om-table-page="700"', html)
        self.assertLess(html.count("data-om-table-page="), 20)

    def test_cell_templates_render_in_the_async_app_environment(self) -> None:
        """Table templates use the app's own async environment, so an async template global in a cell is awaited."""

        async def cell_note() -> str:
            return "AWAITED"

        environment = Environment(loader=DictLoader({"probe/cell.html": "<td>{{ cell_note() }}</td>"}), autoescape=True, enable_async=True)
        template_globals(environment)["cell_note"] = cell_note

        class ProbeRenderer(TableRenderer):
            def template_name(self, name: str) -> str:
                return "probe/cell.html" if name == "cell.html" else super().template_name(name)

        class ProbeTable(DemoProgramTable):
            renderer_class = ProbeRenderer

        request = SimpleNamespace(args={}, headers={}, app=SimpleNamespace(ext=SimpleNamespace(environment=environment)))
        table = ProbeTable()
        table.request = request
        table_request = table.build_table_request(request, route_kwargs={})
        result = asyncio.run(table.query_result(table_request))
        html = str(asyncio.run(table.render_html_fragment(table_request, result)))

        self.assertIn("<td>AWAITED</td>", html)
        self.assertNotIn("coroutine", html)

    def test_table_rendering_delegates_to_renderer_class(self) -> None:
        class MinimalRenderer(TableRenderer):
            async def render_shell(
                self,
                *,
                route_kwargs: dict[str, object],
                html_id: str | None = None,
                show_search: bool = True,
                data_format: Literal["html", "json"] = "html",
                bulk_actions_html: Markup | str | None = None,
            ) -> Markup:
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

    def test_shell_toolbar_renders_column_and_density_tools_by_default(self) -> None:
        shell = str(asyncio.run(DemoProgramTable().render_shell()))

        self.assertIn("data-om-table-toolbar", shell)
        # The search box moved into the toolbar; the loading marker stays for the status protocol.
        self.assertIn('data-om-table-filter data-om-table-param="q"', shell)
        self.assertIn("data-om-table-loading", shell)
        self.assertIn('data-om-table-column-toggle value="title"', shell)
        self.assertIn('data-om-table-density="compact"', shell)
        self.assertNotIn("data-om-table-export", shell)
        self.assertNotIn("data-om-table-selection-count", shell)

    def test_shell_toolbar_export_needs_declared_formats_and_skips_pinned_columns(self) -> None:
        class ExportTable(DemoProgramTable):
            export_formats = ("csv",)
            columns = [
                "id",
                Column("title", label="Title", hideable=False),
                Column("action", label="Action", field_path=None, callback="get_column_action_data"),
            ]

            def get_column_action_data(self, row, **kwargs):
                return "…"

        shell = str(asyncio.run(ExportTable().render_shell(show_search=False)))

        self.assertIn('data-om-table-export="csv"', shell)
        self.assertIn('data-om-table-column-toggle value="id"', shell)
        self.assertNotIn('data-om-table-column-toggle value="title"', shell)
        self.assertNotIn('data-om-table-column-toggle value="action"', shell)
        self.assertNotIn("data-om-table-filter", shell)

    def test_shell_toolbar_shows_selection_count_and_bulk_actions_slot(self) -> None:
        shell = str(
            asyncio.run(
                SelectableProgramTable().render_shell(
                    bulk_actions_html=Markup('<button type="button" data-demo-bulk>Archive</button>'),
                )
            )
        )

        self.assertIn("data-om-table-selection-count", shell)
        self.assertIn('data-om-table-bulk-actions hidden><button type="button" data-demo-bulk>Archive</button>', shell)

    def test_shell_toolbar_is_omitted_when_it_would_be_empty(self) -> None:
        class BareTable(DemoProgramTable):
            toolbar = ()

        shell = str(asyncio.run(BareTable().render_shell(show_search=False)))

        self.assertNotIn("data-om-table-toolbar", shell)

        class WrongTable(DemoProgramTable):
            toolbar = ("columns", "filters")

        with self.assertRaisesRegex(ValueError, "Unknown table toolbar tool"):
            asyncio.run(WrongTable().render_shell())

    def test_empty_fragment_offers_a_reset_only_when_filters_hide_existing_records(self) -> None:
        table = DemoProgramTable()
        request = table.build_table_request(make_request(), route_kwargs={})
        empty_all = TableResult(rows=[], row_contexts=[], total=0, filtered_total=0, page=1, page_size=2)
        empty_filtered = TableResult(rows=[], row_contexts=[], total=3, filtered_total=0, page=1, page_size=2)

        plain = str(asyncio.run(table.render_html_fragment(request, empty_all)))
        filtered = str(asyncio.run(table.render_html_fragment(request, empty_filtered)))

        self.assertIn('class="om-table-empty-cell">', plain)
        self.assertIn('<div class="om-empty om-empty-sm" data-om-table-empty-state>', plain)
        self.assertIn("No records found.", plain)
        self.assertNotIn("data-om-table-empty-reset", plain)
        self.assertIn("data-om-table-empty-state data-om-table-empty-filtered", filtered)
        self.assertIn("No matching records", filtered)
        self.assertIn("Adjust or reset the filters to see more records.", filtered)
        self.assertIn("data-om-table-empty-reset", filtered)

        json_shell = str(asyncio.run(table.render_shell(data_format="json")))
        self.assertIn('<template data-om-table-empty-template="all">', json_shell)
        self.assertIn('<template data-om-table-empty-template="filtered">', json_shell)
        self.assertNotIn("data-om-table-empty-template", str(asyncio.run(table.render_shell())))

    def test_csv_export_applies_filters_sort_and_exportable_columns(self) -> None:
        class ExportTable(DemoProgramTable):
            export_formats = ("csv",)
            columns = [
                "id",
                ("Title", "title", "get_column_title_data"),
                ("Channel", "channel.name"),
                Column("hits", label="Hits", exportable=False),
                Column("live", label="Live", field_path=None, callback="get_column_live_data"),
                Column("action", label="Action", field_path=None, callback="get_column_action_data"),
            ]

            def get_column_action_data(self, row, **kwargs):
                return Markup('<button type="button">Edit</button>')

            def get_column_title_data(self, row, **kwargs):
                # Markup links export as their text; the escaped-string fixture above would export literally.
                return Markup(f'<a href="/programmes/{row.id}">{row.title}</a>'), row.title

            def get_column_live_data(self, row, **kwargs):
                return Markup('<span class="om-badge">on air</span>') if row.hits > 4 else False

        response = asyncio.run(
            ExportTable().get(make_request(args={"export": "csv", "filter.channel": "BBC", "sort": "-hits", "page": "2", "page_size": "1"}))
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "text/csv; charset=utf-8")
        self.assertRegex(response.headers["Content-Disposition"], r'^attachment; filename="program_table-\d{4}-\d{2}-\d{2}\.csv"$')
        body = (response.body or b"").decode("utf-8")
        self.assertTrue(body.startswith("\ufeff"))
        self.assertEqual(
            body.lstrip("\ufeff").splitlines(),
            ["Id,Title,Channel,Live", "3,Beta News,BBC,on air", "1,Zoo News,BBC,false"],
        )

    def test_csv_export_neutralises_formula_triggers_but_keeps_numbers(self) -> None:
        class HostileTable(DictProgramTable):
            export_formats = ("csv",)
            ordering = ["id"]

            async def get_object_list(self):
                return [
                    {"id": 1, "title": '=HYPERLINK("http://evil.test","click")', "channel": {"name": "+cmd|' /C calc'!A0"}, "hits": -5},
                    {"id": 2, "title": "@SUM(A1)", "channel": {"name": "\tTabbed"}, "hits": 3.5},
                    {"id": 3, "title": "-1e3", "channel": {"name": "plain +text"}, "hits": 0},
                ]

        response = asyncio.run(HostileTable().get(make_request(args={"export": "csv"})))

        self.assertEqual(response.status, 200)
        rows = (response.body or b"").decode("utf-8").lstrip("\ufeff").splitlines()
        # Text that a spreadsheet would run gets an apostrophe; numbers (including negatives) stay numbers.
        self.assertEqual(rows[1], '1,"\'=HYPERLINK(""http://evil.test"",""click"")",\'+cmd|\' /C calc\'!A0,-5')
        self.assertEqual(rows[2], "2,'@SUM(A1),'\tTabbed,3.5")
        self.assertEqual(rows[3], "3,-1e3,plain +text,0")

    def test_csv_export_reads_markup_cells_as_text_with_block_spacing(self) -> None:
        class MarkupTable(DictProgramTable):
            export_formats = ("csv",)
            ordering = ["id"]
            columns = [
                "id",
                Column("summary", label="Summary", field_path=None, callback="get_column_summary_data"),
                ("Title", "title", "get_column_title_data"),
                ("Channel", "channel.name", "get_column_channel_data"),
            ]

            def get_column_summary_data(self, row, **kwargs):
                # Title plus description in one cell used to export glued together as "Zoo NewsBBC".
                return Markup('<a href="#">{}</a><div class="om-muted">{}<br>live</div>').format(row["title"], row["channel"]["name"])

            def get_column_title_data(self, row, **kwargs):
                # A callback that hands over the raw text exports that text, not the link.
                return Markup('<a href="#">{} &amp; more</a>').format(row["title"]), row["title"]

            def get_column_channel_data(self, row, **kwargs):
                # A field column rendered as a badge without an explicit raw exports what the user sees.
                return Markup('<span class="om-badge">Channel {}</span>').format(row["channel"]["name"])

        response = asyncio.run(MarkupTable().get(make_request(args={"export": "csv"})))

        rows = (response.body or b"").decode("utf-8").lstrip("\ufeff").splitlines()
        self.assertEqual(rows[:2], ["Id,Summary,Title,Channel", "1,Zoo News BBC live,Zoo News,Channel BBC"])

    def test_csv_export_requires_a_declared_format_and_respects_the_row_cap(self) -> None:
        response = asyncio.run(DemoProgramTable().get(make_request(args={"export": "csv"})))
        self.assertEqual(response.status, 400)
        self.assertIn("Unsupported table export format", (response.body or b"").decode("utf-8"))

        class CappedTable(DemoProgramTable):
            export_formats = ("csv",)
            max_export_rows = 2

        capped = asyncio.run(CappedTable().get(make_request(args={"export": "csv"})))
        self.assertEqual(len((capped.body or b"").decode("utf-8").splitlines()), 3)

    def test_render_shell_rejects_unknown_data_format(self) -> None:
        with self.assertRaisesRegex(ValueError, "data_format must be 'html' or 'json'"):
            asyncio.run(DemoProgramTable().render_shell(data_format="csv"))  # type: ignore[arg-type]

    def test_selectable_table_outputs_selection_without_polluting_columns(self) -> None:
        table = SelectableProgramTable()
        request = table.build_table_request(make_request(), route_kwargs={})
        result = asyncio.run(table.query_result(request))

        html = str(asyncio.run(table.render_html_fragment(request, result)))
        payload = asyncio.run(table.render_json_payload(request, result))

        self.assertIn("data-om-table-select-all", html)
        self.assertIn("data-om-table-select-row", html)
        self.assertEqual([column["name"] for column in payload["columns"]], ["id", "title", "channel.name", "hits"])
        self.assertNotIn("selection", payload["rows"][0]["cells"])

    def test_plain_table_can_select_another_stable_row_field(self) -> None:
        table = SlugProgramTable()
        request = table.build_table_request(make_request(args={"page_size": "1"}), route_kwargs={})
        result = asyncio.run(table.query_result(request))

        html = str(asyncio.run(table.render_html_fragment(request, result)))
        payload = asyncio.run(table.render_json_payload(request, result))

        self.assertIn('data-om-table-row-id="Alpha Show"', html)
        self.assertEqual("Alpha Show", payload["rows"][0]["data"]["id"])

    def test_json_payload_escapes_cells_and_keeps_raw_values_for_sorting(self) -> None:
        table = DemoProgramTable()
        request = table.build_table_request(make_request(headers={"accept": "application/json"}), route_kwargs={})

        payload = asyncio.run(table.render_json_payload(request, asyncio.run(table.query_result(request))))

        self.assertEqual("&lt;a href=&#34;/programmes/2&#34;&gt;Alpha Show&lt;/a&gt;", payload["rows"][0]["cells"]["title"])
        self.assertEqual("Alpha Show", payload["rows"][0]["raw_values"]["title"])
        self.assertIn("pagination", payload)

    def test_json_raw_values_are_scalars_even_when_a_column_returns_a_structure(self) -> None:
        class StructuredRawTable(BaseTableView):
            columns = [("Meta", "title", "get_column_meta_data")]

            async def get_object_list(self):
                return [{"id": 1, "title": "Alpha Show"}]

            def get_column_meta_data(self, row, **kwargs):
                return "<strong>Alpha Show</strong>", {"sort": 1}

        table = StructuredRawTable()
        request = table.build_table_request(make_request(headers={"accept": "application/json"}), route_kwargs={})

        payload = asyncio.run(table.render_json_payload(request, asyncio.run(table.query_result(request))))

        self.assertIsInstance(payload["rows"][0]["raw_values"]["title"], str)

    def test_a_column_callback_gets_the_row_context_and_falls_back_to_its_index(self) -> None:
        seen: list[dict[str, Any]] = []

        class VirtualColumnTable(BaseTableView):
            columns = [("Virtual", None)]

            def get_column_0_data(self, row, **kwargs):
                seen.append(kwargs)
                return "virtual", "raw-virtual"

        table = VirtualColumnTable(request=make_request())
        request = table.build_table_request(make_request(), route_kwargs={})
        result = TableResult(rows=[{"id": 1}], row_contexts=[{"shared": "ok"}], total=1, filtered_total=1)

        html = str(asyncio.run(table.render_html_fragment(request, result)))

        self.assertIn("virtual", html)
        self.assertEqual(
            (None, {"shared": "ok"}, 0, 0),
            (seen[0]["field_path"], seen[0]["row_context"], seen[0]["row_index"], seen[0]["column_index"]),
        )
        self.assertIs(table, seen[0]["table"])
        self.assertIs(request.request, seen[0]["request"])

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

    def test_relationship_search_keeps_rows_without_a_related_record(self) -> None:
        """搜索关联字段时用 LEFT OUTER JOIN：没有关联记录的行不能被 JOIN 过滤掉。"""

        class Base(DeclarativeBase):
            pass

        class Feed(Base):
            __tablename__ = "table_search_feed"

            id: Mapped[int] = mapped_column(Integer, primary_key=True)
            tvg_id: Mapped[str] = mapped_column(String)
            canonical_name: Mapped[str] = mapped_column(String)

        class Record(Base):
            __tablename__ = "table_search_record"

            id: Mapped[int] = mapped_column(Integer, primary_key=True)
            source_code: Mapped[str] = mapped_column(String)
            feed_id: Mapped[int | None] = mapped_column(ForeignKey("table_search_feed.id"), nullable=True)
            feed: Mapped[Feed | None] = relationship()

        class RecordTable(SQLAlchemyTableView):
            model = Record
            search_fields = ["source_code", "feed.tvg_id", "feed.canonical_name"]
            columns = (
                Column("source_code", "Source"),
                Column("feed", "Feed", field_path="feed.tvg_id"),
            )

        table = RecordTable()
        request = table.build_table_request(make_request(args={"q": "cctv"}), route_kwargs={})

        sql = str(asyncio.run(table.apply_search(select(Record), request)))

        # 两个字段路径共用一个关系，SQLAlchemy 只拼一次 JOIN。
        self.assertEqual(1, sql.count("JOIN table_search_feed"))
        self.assertIn("LEFT OUTER JOIN table_search_feed", sql)
        self.assertIn("table_search_record.source_code LIKE", sql)
        self.assertIn("table_search_feed.canonical_name LIKE", sql)

        # 需要 JOIN 顺带过滤掉没有关联记录的行时，调用方显式要求内连接。
        inner_query, _field = table.resolve_sql_field(select(Record), "feed.tvg_id", isouter=False)
        inner_sql = str(inner_query)
        self.assertIn("JOIN table_search_feed", inner_sql)
        self.assertNotIn("LEFT OUTER JOIN", inner_sql)

    def test_a_sqlalchemy_table_scopes_its_query_in_apply_base_filters(self) -> None:
        """The first argument is positional-only, so a SQLAlchemy table names it after what it gets: a query."""

        class Base(DeclarativeBase):
            pass

        class Item(Base):
            __tablename__ = "table_scope_item"

            id: Mapped[int] = mapped_column(Integer, primary_key=True)
            owner_id: Mapped[int] = mapped_column(Integer)

        class OwnItemTable(SQLAlchemyTableView):
            model = Item
            columns = (Column("id", "ID"),)

            async def apply_base_filters(self, query, table_request):
                return query.where(Item.owner_id == 7)

        table = OwnItemTable()
        request = table.build_table_request(make_request(), route_kwargs={})

        self.assertIn("table_scope_item.owner_id = ", str(asyncio.run(table.apply_base_filters(select(Item), request))))

    def test_permission_denied_uses_json_error_contract(self) -> None:
        response = asyncio.run(DeniedProgramTable().get(make_request(headers={"accept": "application/json"})))
        body = response.body
        assert body is not None
        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(response.status, 403)
        self.assertEqual(payload["error_code"], ApiErrorCode.PERMISSION_DENIED)
        self.assertEqual("Permission denied", payload["data"]["errors"]["table"])
        self.assertNotIn("errors", payload)

    def test_a_bad_request_answers_400_with_the_table_error_fragment(self) -> None:
        for args, message in (
            ({"filter.unknown": "1"}, b"Unknown table filter"),
            ({"page_size": "999"}, b"Invalid table pagination parameter"),
        ):
            with self.subTest(args=args):
                response = asyncio.run(DemoProgramTable().get(make_request(args=args)))
                body = response.body
                assert body is not None

                self.assertEqual(400, response.status)
                self.assertIn(b"data-om-table-error", body)
                self.assertIn(message, body)

    def test_check_auth_lets_every_request_through_by_default(self) -> None:
        table = DemoProgramTable()

        self.assertTrue(asyncio.run(table.check_auth(table.build_table_request(make_request(), route_kwargs={}))))

    def test_check_auth_receives_the_parsed_request(self) -> None:
        """The data-aware hook sees the parsed search and route parameters, not just the raw request."""
        seen: list[Any] = []

        class InspectingTable(DemoProgramTable):
            async def check_auth(self, table_request) -> bool:
                seen.append(table_request)
                return False

        response = asyncio.run(InspectingTable().get(make_request(args={"q": "news"}, headers={"accept": "application/json"}), channel="cctv1"))

        self.assertEqual(403, response.status)
        self.assertEqual(1, len(seen))
        self.assertIsInstance(seen[0], TableRequest)
        self.assertEqual(("news", {"channel": "cctv1"}), (seen[0].q, seen[0].route_kwargs))

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


class SortAllowlistTest(unittest.TestCase):
    """A client may only sort by a column the table declares as sortable.

    The old check asked `if column is not None` before consulting `sortable`, so a column
    that was declared and excluded was refused while one that was never declared at all
    went straight into ORDER BY. On the framework's own user table - which puts
    password_hash in `exclude` - `?sort=password_hash` produced a working ORDER BY, and
    an undeclared dotted path could emit a JOIN nobody asked for.

    Filters were always an allowlist by construction (an explicit filter_<name> method or
    TableInvalidRequest). Sorting is now held to the same rule.
    """

    def _request(self, sort: str | None) -> TableRequest:
        """Build a real TableRequest rather than a duck-typed stand-in.

        `apply_ordering` declares `TableRequest`, and a look-alike class only satisfies the
        runtime, not the type checker. `resolve_sort_field` reads `sort` with a plain truth
        test, so "" and None take the same branch.
        """
        return TableRequest(request=None, q="", page=1, page_size=10, sort=sort or "", filters={}, route_kwargs={})

    def _table(self):
        from oldman.auth.models import User
        from oldman.web.auth.tables import UserTable

        class Probe(UserTable):
            model = User

        return Probe()

    def test_a_column_the_table_never_declared_is_refused(self) -> None:
        from sqlalchemy import select

        from oldman.auth.models import User
        from oldman.web.components.tables import TableInvalidRequest

        table = self._table()
        for sort in ("password_hash", "-password_hash", "nope.nested"):
            with self.subTest(sort=sort), self.assertRaises(TableInvalidRequest):
                asyncio.run(table.apply_ordering(select(User), self._request(sort)))

    def test_a_declared_but_unsortable_column_is_refused(self) -> None:
        from sqlalchemy import select

        from oldman.auth.models import User
        from oldman.web.components.tables import TableInvalidRequest

        table = self._table()
        with self.assertRaises(TableInvalidRequest):
            asyncio.run(table.apply_ordering(select(User), self._request("action")))

    def test_a_declared_sortable_column_still_orders(self) -> None:
        from sqlalchemy import select

        from oldman.auth.models import User

        table = self._table()
        query = asyncio.run(table.apply_ordering(select(User), self._request("username")))
        self.assertIn("ORDER BY oldman_user.username ASC", str(query))

    def test_the_developer_default_ordering_is_not_held_to_the_allowlist(self) -> None:
        """`ordering` is code, not request input; it may name a field that is not a column."""
        from sqlalchemy import select

        from oldman.auth.models import User
        from oldman.web.components.tables import SQLAlchemyTableView
        from oldman.web.components.tables.columns import Column

        class HiddenDefaultTable(SQLAlchemyTableView):
            model = User
            columns = (Column("username", "User"),)
            ordering = ["-last_login_at"]  # deliberately not a declared column

        query = asyncio.run(HiddenDefaultTable().apply_ordering(select(User), self._request(None)))
        self.assertIn("ORDER BY oldman_user.last_login_at DESC", str(query))

    def test_the_export_path_uses_the_same_allowlist(self) -> None:
        """query_export orders through apply_ordering too, so it cannot be the way in."""
        import inspect

        from oldman.web.components.tables.views import SQLAlchemyTableView

        source = inspect.getsource(SQLAlchemyTableView.query_export)
        self.assertIn("apply_ordering", source)
