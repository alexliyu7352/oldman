# Source development, verification, and releases

This chapter is for framework maintainers. Application developers do not need repository release verification just to use Admin or Forms; see [Deployment and Operations](../users/deployment.md) for application deployment.

## Repository layout and environment

| Path | Responsibility |
| --- | --- |
| `oldman/` | Python package: Apps, runtime, Web, data, and other public capabilities |
| `frontend/packages/oldman-web/` | Published browser component package |
| `frontend/apps/admin/` | Built-in Admin browser consumer; output enters Python static assets |
| `oldman/scaffolds/` | Project/App/service generation templates |
| `tests/` | Python behavior and installation/maintenance-script checks |
| `scripts/` | Build, installation, browser, and release verification tools, not business APIs |
| `docs/public/<language>/` | Public documentation: users for usage, developers for exact interfaces, agents for task wiring |

Complete Admin/dashboard demos are separate repositories with their own dependencies, configuration, databases, and Git. Root README links them. Do not create business config/services/data directories in the framework or commit local demo settings here.

Prepare the environment at framework root:

```sh
uv sync --group dev
pnpm install --frozen-lockfile
```

Current metadata requires Python 3.12–3.14 and Node 20+, with packageManager pnpm 9.12.3. Frontend versions follow pnpm-lock.yaml. Python dependencies are constrained only by pyproject.toml; uv.lock is a local resolution and is not committed. Do not arbitrarily upgrade around failures. Dependency changes are separate reviewable work. CI's 3.13/3.14 matrix pins 3.13.11/3.14.2: under asyncio debug (forced by IsolatedAsyncioTestCase), uvloop crashes while collecting unclosed async generators, still unfixed in 0.22.1/0.23.0 ([uvloop#699](https://github.com/MagicStack/uvloop/issues/699), [uvloop#715](https://github.com/MagicStack/uvloop/issues/715)). Framework tests trigger it on 3.13.15/3.14.7 but not these pinned versions. Relax pins after the upstream fix.

Before editing, inspect Git status, existing style, and all relevant callers. Use one commit per task; see [Source development, verification, and releases](#commit-titles-and-release-notes) for titles. Release checks do not authorize committing unfinished user changes. When clean committed source is required, establish ownership first rather than using reset or add . to clear the workspace.

## Daily verification: relevant scope only

Python examples:

```sh
.venv/bin/python -m unittest -q tests.test_oldman_web_auth_user_session
.venv/bin/ruff check oldman/web/auth/user_session.py
.venv/bin/ruff format --check oldman/web/auth/user_session.py
.venv/bin/pyright oldman/web/auth/user_session.py
```

Substitute actual files for this task. Tests cover behavior and necessary failures rather than mere implementation-string presence. Check all consumers when changing shared functions.

After changing public names (__all__, exported signatures, or docstring first lines), run `.venv/bin/python scripts/api_index.py --write` and commit generated docs/public/en/api changes together. tests/test_api_index.py checks source/index consistency and every public-doc from oldman... import against the index. Before documenting a name absent from __all__, establish that it should be public, then add it to its module's __all__.

Frontend changes require package tests/typechecks and actual Chrome interaction. Check initialization, revisits, remote replacements, departure, and failure feedback. Screenshots are evidence rather than substitutes for clicks/results. Compatibility targets extend beyond Chrome.

Manage only task-owned services, browsers, and Redis. Put temporary data in your own /tmp subdirectory, not /dev/shm, and do not use real demo databases for destructive checks. Stop children, confirm port release, then remove owned temporary directories.

See [Test isolation requirements](testing.md) for Settings/App Registry/model isolation. Do not add production reset, second Settings, or fake providers for tests.

## Browser package and Admin builds

```sh
pnpm --filter oldman-web build
pnpm --filter oldman-admin build
```

Run in order. oldman-web prebuild generates icons, frontend message lists, and i18n CLI, compiles TS, and copies styles. Admin imports public implementations from it, with Vite output at oldman/apps/admin/static/oldman/admin.

These commands update generated files and clear their build targets. Preserve user edits before running and inspect diffs afterwards; do not hand-edit minified JS/CSS. Custom styles/icons belong in application builds, without business dependencies in the framework.

Translation changes follow POT extraction → PO update → translation → MO/frontend JSON compilation, not direct generated-catalog edits. See [Frontend assets, styles, icons, and translation](assets.md#framework-translations) for application usage.

The framework has one translation source, oldman/locales, covering Admin, accounts, tables/forms, notifications, roles, CLI/migrations, and oldman-web browser text. Maintain it through [scripts/framework_i18n.py](https://github.com/alexliyu7352/oldman/blob/main/scripts/framework_i18n.py). After adding/changing/removing text, including oldman-web messages (first run generate:i18n-messages), at framework root:

```sh
.venv/bin/python scripts/framework_i18n.py update    # Rebuild messages.pot and merge into zh_Hans/zh_Hant PO files
# Translate new entries and remove fuzzy markers after checking fuzzy entries
.venv/bin/python scripts/framework_i18n.py compile   # Write .mo files shipped in wheels
.venv/bin/python scripts/framework_i18n.py check     # List stale outputs; no output means current
```

Extraction uses oldman/i18n/framework-babel.cfg plus the frontend message list, sharing the function used by project i18n extract for framework messages, so coverage matches. Add new message-bearing framework directories there. Templates/PO omit line numbers, so moving code alone does not stale catalogs. tests/test_oldman_framework_translations.py runs the same ordinary checks: template/source mismatches, untranslated/fuzzy entries, and MO/PO mismatches all fail. .mo/.pot are ignored; add them explicitly by path with git add -f.

## Versions and releases

Root pyproject.toml project.version is authoritative and must satisfy both SemVer/PEP 440. Use 0.1.1 for stable and 0.1.1-rc.1 for prereleases. Python filenames/metadata normalize to PEP 440 (0.1.1rc1), while npm retains the original string. Maintenance scripts convert through python_distribution_version() in scripts/release_artifacts.py, not handwritten formatting.

GitHub Actions publishes releases. Locally, do only three things:

1. Change project.version, run pnpm version:sync, review/commit rewritten Python/npm copies (package.json, both frontend packages, oldman/version.py, OLDMAN_WEB_VERSION). Do not manually edit versions and miss another package.
2. Create an annotated v<version> tag on that main commit, such as v0.1.1 or v0.1.1-rc.1, then push main/tag.
3. Inspect the Release Action and verify PyPI, npm, and GitHub Release.

.github/workflows/release.yml validates tag/version equality, generates release notes from commit titles (below), runs pnpm build:python and pnpm pack:web, then verify-wheel-contents, verify-sdist-contents, verify-python-package-install (Python 3.12/3.13/3.14), and verify-oldman-web-package. After all pass, Trusted Publishing (OIDC, without long-lived tokens) publishes PyPI/npm and creates a GitHub Release with generated notes, three artifacts, and SHA256SUMS. Any failure prevents all publishing. After fixing, delete/recreate the tag on the new commit.

.github/workflows/docs.yml publishes website/ to GitHub Pages at https://alexliyu7352.github.io/oldman/. After a successful stable Release (tag without -), it checks out that tag, runs pnpm verify:docs, and deploys matching documentation. Prereleases do not update docs. It runs separately after Release, rather than as a Release job, because Pages deployment environments default to allowing only default-branch deployment and would reject tags. For between-release updates, run it manually in Actions with a branch/tag. First set repository Settings → Pages → Source to GitHub Actions.

### Commit titles and release notes

There is no CHANGELOG file. GitHub Release bodies are release notes generated by git-cliff from commit titles using root cliff.toml. Each title becomes one user-facing English sentence in the notes:

```text
type(scope): summary
```

- type selects groups: feat → Added, fix → Fixed, perf → Performance, refactor → Changed, docs → Documentation, revert → Reverted. test/build/ci/chore/release are excluded.
- scope is optional and identifies the affected subsystem, such as fix(web): ... .
- summary appears unchanged, including case. Start lowercase except when preserving a command/function name; for example, fix(db): loaddata reads back the float columns dumpdata wrote.
- Mark breaking changes with ! after the type, as in feat(db)!: ..., or a final BREAKING CHANGE: ... body footer. These entries lead the notes.
- Choose dependency-change types by user-visible effect rather than build. Added/removed dependencies, narrowed/widened ranges, and optional-group changes affect installations and must enter notes. Use feat/fix/refactor according to impact; add ! when existing projects can no longer install or require code changes, such as fix(db)!: require SQLAlchemy below 2.1. build is only for changes that do not affect installation results.
- Bodies do not enter release notes; use them for rationale/implementation details.
- Invalid titles still appear under Other rather than disappearing, but should be avoided.

Stable notes include commits since the previous stable version, including intervening prereleases; prerelease notes start at the previous tag. Preview locally before publishing:

```sh
uvx git-cliff@2.14.2 --unreleased
```

Titles cannot change after pushing. Correct mistakes by editing the Release body directly.

Prerelease versions containing - are PyPI prereleases: pip install oldman excludes them by default without --pre or an exact version. npm publishes to next, retaining latest. GitHub marks them prereleases. Rehearsing the release chain this way does not affect stable users.

.github/workflows/ci.yml runs static checks and Python/frontend tests on every push/PR. Real-service checks require redis-server (6.2+, from apt) and nats-server (pinned workflow download verified by SHA-256). Missing programs fail rather than skip; see [Test isolation requirements](testing.md#real-service-checks).

Use the same commands for local artifact verification:

```sh
pnpm build:python
pnpm pack:web
```

The first builds Admin, then wheel/sdist; the second builds/packs oldman-web. Current stable artifacts are:

- `dist/oldman-<normalized-Python-version>-py3-none-any.whl`
- `dist/oldman-<normalized-Python-version>.tar.gz`
- `frontend/packages/oldman-web/oldman-web-<version>.tgz`

Prerelease Python filenames may normalize. Tools calculate paths through scripts/release_artifacts.py rather than guessing via modification time/globs. Installation checks must target actual intended files/hashes; editable installs do not verify wheels.

Python packages include runtime code, templates, Admin builds, migrations, scaffolds, required MO, and licensing material. sdist has explicit content rules. A source file's existence does not guarantee release inclusion.

## Full verification in serial stages

Run these stages only for release preparation or explicitly requested full acceptance. Diagnose a failed stage before continuing rather than backgrounding every command:

```sh
pnpm verify:static
pnpm verify:python
pnpm verify:frontend
pnpm verify:web-boundaries
pnpm verify:web-package
pnpm verify:python-package
pnpm verify:scaffold-matrix
pnpm verify:docs
```

- static: Python lint/format (ruff check, ruff format --check, with ruff format as the formatting standard), plus pyright/Pyrefly type checks. Pyrefly is pinned in pyproject.toml dev dependencies and configured under tool.pyrefly.
- python: full Python tests.
- frontend: both frontend packages' tests/typechecks.
- web-boundaries: existing frontend boundary checks.
- web-package: current npm artifacts and real-consumer verification.
- python-package: wheel/sdist contents, Python 3.12–3.14 installs, and built-in Admin Chrome checks. Release runs the browser-independent subset.
- scaffold-matrix: creates projects from real artifacts and verifies generated services, including browsers where needed. API projects additionally create an mcp-template App with startapp, wire install_mcp according to [MCP server](mcp.md), and call its tools with the generated API key using both handshake and 2026-07-28 protocols.
- docs: installs website dependencies and builds English/Chinese sites. Dead links fail; invalid anchors currently warn because untranslated fallback pages use Chinese anchors that temporarily mismatch translated targets. CI also runs this on 3.12.

Package/scaffold stages create isolated environments, download dependencies, and build, using more disk/memory than ordinary unit tests. Check available disk/memory and active services first; run only one Chrome task at a time. No fixed space cap suits every machine because environments/caches affect usage.

These entry points save evidence under /tmp/oldman-*-evidence by default and do not delete all results automatically. For explicit locations, call corresponding scripts/verify-current-release-*.py --evidence-root /tmp/task-owned-parent. Each invocation creates an independent run directory. Never clean a shared user directory.

Inspect result.json, logs, and browser screenshots, then record conclusions. Archive required evidence to a user-designated location, confirm processes exited, and delete **that exact run directory**. Do not recursively delete all /tmp or arbitrary wildcard directories.

Advanced --use-existing-artifacts requires corresponding SHA-256 values; filenames alone do not bypass build confirmation. Consult script --help for arguments. Ordinary maintainers can use default stage entry points.

## Publishing is not a testing side effect

Builds/verification do not upload automatically. Actual publishing also requires explicit target registries, account permissions, versions, licensing, release notes, and rollback arrangements. Once publishing is authorized, upload the same verified artifacts rather than rebuilding replacements at the last moment.

Report unrun stages, known failures, deprecation warnings, and omitted manual operations honestly. Documentation rewrites or a few targeted checks do not establish full acceptance or external-registry availability.

<!-- source: zh/developers/maintenance.md @ 7b6b8aba -->
