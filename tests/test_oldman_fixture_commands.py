"""Database-backed contracts for deterministic JSON fixtures."""

from __future__ import annotations

import enum
import importlib
import json
import sys
import tempfile
import unittest
import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Time,
    Uuid,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from oldman.conf.schemas import DatabaseConfig
from oldman.db import DatabaseManager, ModelMetadata
from oldman.db.fixtures import dump_data, load_data, resolve_fixture_path


class FixtureBase(DeclarativeBase):
    """Keep fixture test models outside Oldman's process-wide metadata."""


class ProjectState(enum.StrEnum):
    PLANNED = "planned"
    ACTIVE = "active"


class FixtureTeam(FixtureBase):
    __tablename__ = "fixture_team"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)


class FixtureProject(FixtureBase):
    __tablename__ = "fixture_project"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("fixture_team.id"))
    name: Mapped[str] = mapped_column(String(128), unique=True)
    budget: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    starts_on: Mapped[date] = mapped_column(Date)
    starts_at: Mapped[time] = mapped_column(Time)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    token: Mapped[uuid.UUID] = mapped_column(Uuid)
    state: Mapped[ProjectState] = mapped_column(Enum(ProjectState))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class FixtureTeamMember(FixtureBase):
    __tablename__ = "fixture_team_member"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_slug: Mapped[str] = mapped_column(ForeignKey("fixture_team.slug"))


class FixtureNode(FixtureBase):
    __tablename__ = "fixture_node"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("fixture_node.id"),
        nullable=True,
    )


class FixtureComposite(FixtureBase):
    __tablename__ = "fixture_composite"

    left_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    right_id: Mapped[int] = mapped_column(Integer, primary_key=True)


class FixtureUnmanaged(FixtureBase):
    __tablename__ = "fixture_unmanaged"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)


def _metadata(
    model: type[Any],
    *,
    app_label: str = "demo",
    managed: bool = True,
) -> ModelMetadata:
    """Build the same immutable model metadata exposed by AppRegistry."""
    return ModelMetadata(
        model=model,
        table=model.__table__,
        app_label=app_label,
        verbose_name=model.__name__,
        verbose_name_plural=f"{model.__name__}s",
        managed=managed,
    )


class FixtureRegistry:
    """Minimal read-only Registry surface consumed by fixture helpers."""

    def __init__(self) -> None:
        self.models = (
            _metadata(FixtureTeam),
            _metadata(FixtureProject),
            _metadata(FixtureTeamMember),
            _metadata(FixtureNode),
            _metadata(FixtureComposite, app_label="invalid"),
            _metadata(FixtureUnmanaged, app_label="invalid", managed=False),
        )


class FixturePackageRegistry:
    """Minimal installed-package surface consumed by fixture lookup."""

    def __init__(self, packages: tuple[str, ...]) -> None:
        self.packages = packages


class FixtureDataTest(unittest.IsolatedAsyncioTestCase):
    """Exercise fixture behavior through a real SQLite database."""

    async def asyncSetUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "fixtures.sqlite3"
        self.manager = DatabaseManager(
            DatabaseConfig(
                url=f"sqlite+aiosqlite:///{database_path.as_posix()}",
                echo=False,
            )
        )
        await self.manager.initialize()
        async with self.manager.engine.begin() as connection:
            await connection.run_sync(FixtureBase.metadata.create_all)
        self.registry = FixtureRegistry()

    async def asyncTearDown(self) -> None:
        await self.manager.close()
        self.temporary_directory.cleanup()

    async def test_dump_is_dependency_ordered_typed_and_byte_stable(self) -> None:
        project_token = uuid.UUID("8f5b3114-d13d-41d7-a473-3e4779679e10")
        async with self.manager.get_session() as session:
            session.add(FixtureTeam(id=3, slug="platform"))
            await session.flush()
            session.add(
                FixtureProject(
                    id=7,
                    team_id=3,
                    name="Control Room",
                    budget=Decimal("1250.50"),
                    starts_on=date(2026, 9, 1),
                    starts_at=time(8, 30, 5),
                    updated_at=datetime(2026, 9, 1, 16, 0, tzinfo=UTC),
                    token=project_token,
                    state=ProjectState.ACTIVE,
                    payload={"regions": ["us-west", "eu-central"], "enabled": True},
                )
            )

        first = await dump_data(self.registry, self.manager, "demo")
        second = await dump_data(self.registry, self.manager, "demo")

        self.assertEqual(first, second)
        self.assertTrue(first.endswith("\n"))
        records = json.loads(first)
        self.assertEqual(
            ["demo.FixtureTeam", "demo.FixtureProject"],
            [record["model"] for record in records],
        )
        self.assertEqual(["model", "pk", "fields"], list(records[0]))
        self.assertEqual(
            {
                "team_id": 3,
                "name": "Control Room",
                "budget": "1250.50",
                "starts_on": "2026-09-01",
                "starts_at": "08:30:05",
                "updated_at": "2026-09-01T16:00:00",
                "token": str(project_token),
                "state": "active",
                "payload": {
                    "regions": ["us-west", "eu-central"],
                    "enabled": True,
                },
            },
            records[1]["fields"],
        )

    async def test_dump_can_select_one_model(self) -> None:
        async with self.manager.get_session() as session:
            session.add(FixtureTeam(id=1, slug="one"))

        payload = await dump_data(
            self.registry,
            self.manager,
            "demo.FixtureTeam",
        )

        self.assertEqual(["demo.FixtureTeam"], [item["model"] for item in json.loads(payload)])

    async def test_load_creates_updates_and_remains_idempotent(self) -> None:
        fixture_path = Path(self.temporary_directory.name) / "demo.json"
        records = [
            {
                "model": "demo.FixtureProject",
                "pk": 7,
                "fields": {
                    "team_id": 3,
                    "name": "Control Room",
                    "budget": "1250.50",
                    "starts_on": "2026-09-01",
                    "starts_at": "08:30:05",
                    "updated_at": "2026-09-01T16:00:00+00:00",
                    "token": "8f5b3114-d13d-41d7-a473-3e4779679e10",
                    "state": "active",
                    "payload": {"keep": True},
                },
            },
            {
                "model": "demo.FixtureTeam",
                "pk": 3,
                "fields": {"slug": "platform"},
            },
        ]
        fixture_path.write_text(json.dumps(records), encoding="utf-8")

        first = await load_data(self.registry, self.manager, fixture_path)
        records[0]["fields"] = {"team_id": 3, "name": "Updated"}
        fixture_path.write_text(json.dumps(records), encoding="utf-8")
        second = await load_data(self.registry, self.manager, fixture_path)

        self.assertEqual(2, first)
        self.assertEqual(2, second)
        async with self.manager.get_read_session() as session:
            team_count = await session.scalar(select(func.count()).select_from(FixtureTeam))
            project = await session.get(FixtureProject, 7)
        self.assertEqual(1, team_count)
        self.assertIsNotNone(project)
        assert project is not None
        self.assertEqual("Updated", project.name)
        self.assertEqual(Decimal("1250.50"), project.budget)
        self.assertEqual(date(2026, 9, 1), project.starts_on)
        self.assertEqual(time(8, 30, 5), project.starts_at)
        self.assertEqual(datetime(2026, 9, 1, 16, 0), project.updated_at)
        self.assertEqual(uuid.UUID("8f5b3114-d13d-41d7-a473-3e4779679e10"), project.token)
        self.assertEqual(ProjectState.ACTIVE, project.state)
        self.assertEqual({"keep": True}, project.payload)

    async def test_load_rejects_missing_foreign_keys_before_writing(self) -> None:
        fixture_path = self._write_fixture(
            [
                {
                    "model": "demo.FixtureProject",
                    "pk": 1,
                    "fields": self._project_fields(team_id=999, name="Missing"),
                }
            ]
        )

        with self.assertRaisesRegex(ValueError, "team_id.*999"):
            await load_data(self.registry, self.manager, fixture_path)

        async with self.manager.get_read_session() as session:
            count = await session.scalar(select(func.count()).select_from(FixtureProject))
        self.assertEqual(0, count)

    async def test_load_accepts_existing_foreign_keys_and_preserves_autoincrement(self) -> None:
        async with self.manager.get_session() as session:
            session.add(FixtureTeam(id=9, slug="existing"))
        fixture_path = self._write_fixture(
            [
                {
                    "model": "demo.FixtureProject",
                    "pk": 12,
                    "fields": self._project_fields(team_id=9, name="Imported"),
                }
            ]
        )

        await load_data(self.registry, self.manager, fixture_path)
        async with self.manager.get_session() as session:
            project = FixtureProject(
                team_id=9,
                name="Automatic",
                budget=Decimal("2.00"),
                starts_on=date(2026, 9, 2),
                starts_at=time(9, 0),
                updated_at=datetime(2026, 9, 2, 16, 0),
                token=uuid.UUID("ccaa3897-f564-4270-85c6-48a104ad26f3"),
                state=ProjectState.PLANNED,
                payload={},
            )
            session.add(project)
            await session.flush()
            generated_id = project.id

        self.assertEqual(13, generated_id)

    async def test_load_orders_same_file_foreign_key_to_unique_non_primary_column(self) -> None:
        fixture_path = self._write_fixture(
            [
                {
                    "model": "demo.FixtureTeamMember",
                    "pk": 4,
                    "fields": {"team_slug": "platform"},
                },
                {
                    "model": "demo.FixtureTeam",
                    "pk": 3,
                    "fields": {"slug": "platform"},
                },
            ]
        )

        loaded = await load_data(self.registry, self.manager, fixture_path)

        self.assertEqual(2, loaded)
        async with self.manager.get_read_session() as session:
            member = await session.get(FixtureTeamMember, 4)
        self.assertIsNotNone(member)
        assert member is not None
        self.assertEqual("platform", member.team_slug)

    async def test_load_orders_self_referencing_rows(self) -> None:
        fixture_path = self._write_fixture(
            [
                {"model": "demo.FixtureNode", "pk": 2, "fields": {"parent_id": 1}},
                {"model": "demo.FixtureNode", "pk": 1, "fields": {"parent_id": None}},
            ]
        )

        loaded = await load_data(self.registry, self.manager, fixture_path)

        self.assertEqual(2, loaded)
        async with self.manager.get_read_session() as session:
            child = await session.get(FixtureNode, 2)
        self.assertIsNotNone(child)
        assert child is not None
        self.assertEqual(1, child.parent_id)

    async def test_load_rejects_new_record_cycles(self) -> None:
        fixture_path = self._write_fixture(
            [
                {"model": "demo.FixtureNode", "pk": 1, "fields": {"parent_id": 2}},
                {"model": "demo.FixtureNode", "pk": 2, "fields": {"parent_id": 1}},
            ]
        )

        with self.assertRaisesRegex(ValueError, "cycle"):
            await load_data(self.registry, self.manager, fixture_path)

    async def test_load_rolls_back_the_whole_file_on_database_failure(self) -> None:
        fixture_path = self._write_fixture(
            [
                {"model": "demo.FixtureTeam", "pk": 1, "fields": {"slug": "same"}},
                {"model": "demo.FixtureTeam", "pk": 2, "fields": {"slug": "same"}},
            ]
        )

        with self.assertRaises(IntegrityError):
            await load_data(self.registry, self.manager, fixture_path)

        async with self.manager.get_read_session() as session:
            count = await session.scalar(select(func.count()).select_from(FixtureTeam))
        self.assertEqual(0, count)

    async def test_load_rejects_duplicate_records_and_unknown_fields(self) -> None:
        cases = {
            "duplicate": [
                {"model": "demo.FixtureTeam", "pk": 1, "fields": {"slug": "one"}},
                {"model": "demo.FixtureTeam", "pk": 1, "fields": {"slug": "two"}},
            ],
            "unknown field": [
                {
                    "model": "demo.FixtureTeam",
                    "pk": 1,
                    "fields": {"slug": "one", "missing": True},
                }
            ],
            "not installed": [
                {
                    "model": "demo.Missing",
                    "pk": 1,
                    "fields": {},
                }
            ],
        }
        for message, records in cases.items():
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    await load_data(
                        self.registry,
                        self.manager,
                        self._write_fixture(records),
                    )

    async def test_unmanaged_and_composite_models_are_not_fixture_targets(self) -> None:
        for selector, message in (
            ("invalid.FixtureUnmanaged", "not managed"),
            ("invalid.FixtureComposite", "single-column primary key"),
        ):
            with self.subTest(selector=selector):
                with self.assertRaisesRegex(ValueError, message):
                    await dump_data(self.registry, self.manager, selector)

    def _write_fixture(self, records: list[dict[str, Any]]) -> Path:
        path = Path(self.temporary_directory.name) / "input.json"
        path.write_text(json.dumps(records), encoding="utf-8")
        return path

    @staticmethod
    def _project_fields(*, team_id: int, name: str) -> dict[str, Any]:
        return {
            "team_id": team_id,
            "name": name,
            "budget": "1.00",
            "starts_on": "2026-09-01",
            "starts_at": "08:30:00",
            "updated_at": "2026-09-01T16:00:00+00:00",
            "token": "8f5b3114-d13d-41d7-a473-3e4779679e10",
            "state": "planned",
            "payload": {},
        }


class FixturePathTest(unittest.TestCase):
    """Resolve named fixtures only from installed App package roots."""

    def test_named_fixture_is_resolved_and_ambiguity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            packages = []
            for index in (1, 2):
                package = f"fixture_package_{index}"
                fixture = root / package / "fixtures/demo.json"
                fixture.parent.mkdir(parents=True)
                (fixture.parent.parent / "__init__.py").write_text("", encoding="utf-8")
                fixture.write_text("[]", encoding="utf-8")
                packages.append(package)
            sys.path.insert(0, str(root))
            importlib.invalidate_caches()
            try:
                registry = FixturePackageRegistry(tuple(packages[:1]))
                self.assertEqual(
                    (root / packages[0] / "fixtures/demo.json").resolve(),
                    resolve_fixture_path(registry, "demo"),
                )

                ambiguous = FixturePackageRegistry(tuple(packages))
                with self.assertRaisesRegex(ValueError, "more than one installed App"):
                    resolve_fixture_path(ambiguous, "demo")
            finally:
                sys.path.remove(str(root))
                for package in packages:
                    sys.modules.pop(package, None)
                importlib.invalidate_caches()


if __name__ == "__main__":
    unittest.main()
