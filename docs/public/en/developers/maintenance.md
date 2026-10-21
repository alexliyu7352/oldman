# Source development, verification, and releases

This chapter is for framework maintainers. Application developers do not need to run this repository's release verification just to use Admin or Forms. See [Deployment and operation](../users/deployment.md) for application deployment.

## Repository layout and environment

| Path | Responsibility |
| --- | --- |
| `oldman/` | This is the Python package containing Apps, the runtime, Web, data support, and other public capabilities. |
| `frontend/packages/oldman-web/` | This is the published browser component package. |
| `frontend/apps/admin/` | This is the built-in Admin's frontend consumer. Its output enters the Python package's static directory. |
| `oldman/scaffolds/` | This contains templates for generated projects, Apps, and services. |
| `tests/` | This contains Python behavior tests and checks for installation and maintenance scripts. |
| `scripts/` | This contains build, installation, browser, and release verification tools, not business APIs. |
| `docs/public/<language>/` | This contains public documentation: `users` explains usage, `developers` defines exact interfaces, and `agents` explains task wiring. |

The complete Admin and dashboard demos are separate repositories with their own dependencies, configuration, databases, and Git history. The root README links to them. Do not create business config, services, or data directories in the framework, or commit local demo configuration here.

Prepare the environment at the framework root:

```sh
uv sync --group dev
pnpm install --frozen-lockfile
```

Current metadata requires Python 3.12 through 3.14 and Node 20 or later, with packageManager set to pnpm 9.12.3. Frontend dependency versions follow the repository's `pnpm-lock.yaml`. Python dependencies are constrained only by `pyproject.toml`; `uv.lock` is a local resolution and is not committed. Do not arbitrarily upgrade dependencies to bypass a failure. Dependency changes are separate, reviewable tasks. CI pins its 3.13 and 3.14 matrix to 3.13.11 and 3.14.2. In asyncio debug mode, which `IsolatedAsyncioTestCase` forces on, uvloop crashes when collecting unclosed async generators. Neither 0.22.1 nor 0.23.0 fixes this issue; see [uvloop#699](https://github.com/MagicStack/uvloop/issues/699) and [uvloop#715](https://github.com/MagicStack/uvloop/issues/715). Framework tests trigger it on 3.13.15 and 3.14.7 but not on the two pinned versions. Relax these pins after the upstream fix.

Before editing, inspect Git status, the existing style, and all relevant callers. Use one commit for each defined task; see [commit titles and release notes](#commit-titles-and-release-notes) for title conventions. Release verification does not require committing unfinished user changes. When clean committed source is needed, establish ownership first rather than clearing the workspace with reset or add . commands.

## Daily verification: relevant scope only

Python examples:

```sh
.venv/bin/python -m unittest -q tests.test_oldman_web_auth_user_session
.venv/bin/ruff check oldman/web/auth/user_session.py
.venv/bin/ruff format --check oldman/web/auth/user_session.py
.venv/bin/pyright oldman/web/auth/user_session.py
```

Replace these examples with the files actually changed. Tests should check real behavior and necessary failure paths rather than merely the presence of a string in the implementation. Check every consumer when changing a shared function.

After changing public names, such as a module's `__all__`, an exported signature, or a docstring's first line, run `.venv/bin/python scripts/api_index.py --write` and commit changes in `docs/public/en/api/` together. The index is an English reference and takes only the first docstring line. For Chinese docstrings, write one English summary sentence first, leave a blank line, then retain the original Chinese. The same applies to `#:` comments: keep English on the `#:` line and move Chinese to an ordinary `#` line above it. `tests/test_api_index.py` checks that the index matches source, contains no Chinese summaries, and includes every `from oldman... import` in public documentation. Before documenting a name absent from `__all__`, confirm that it should be public and add it to its module's `__all__`.

For frontend changes, run the corresponding package's tests and type checks and operate the relevant pages in real Chrome. Check initialization, revisits, replacement of remote content, page departure, and failure feedback. Screenshots provide evidence but do not replace clicks or result verification. Compatibility targets extend beyond Chrome.

When starting services, browsers, and Redis, manage only this task's processes. Put temporary data in a `/tmp` subdirectory you created, not `/dev/shm`, and do not reuse real demo databases for destructive checks. Stop child processes, confirm port release, then remove your temporary directories.

See [Test isolation requirements](testing.md) for isolation of Settings, App Registry, and models. Do not add production reset operations, a second Settings object, or fake providers for tests.

## Browser package and Admin builds

```sh
pnpm --filter oldman-web build
pnpm --filter oldman-admin build
```

Run these commands in order. The oldman-web prebuild generates icons, frontend message lists, and the i18n CLI, compiles TypeScript, and copies styles. Admin imports public implementations from that package, and Vite outputs to `oldman/apps/admin/static/oldman/admin`.

These commands update generated files and clear their build targets. Preserve user changes before running them and inspect the diff afterwards. Do not edit minified JavaScript or CSS manually. Custom application styles and icons belong in that application's build; do not add business dependencies to the framework.

Translation updates follow extraction of POT, updating PO, translation, and compilation of MO and frontend JSON. Do not edit generated catalogs directly. For application-side instructions, see [the assets documentation](assets.md#framework-translations).

The framework has one translation source, `oldman/locales`, containing text for Admin, account pages, tables, forms, notifications, roles, CLI commands, migration commands, and the `oldman-web` frontend. Maintain it through [scripts/framework_i18n.py](https://github.com/alexliyu7352/oldman/blob/main/scripts/framework_i18n.py). After adding, changing, or deleting framework text, including frontend text in `oldman-web` (first run `generate:i18n-messages`), run the following at the framework root:

```sh
.venv/bin/python scripts/framework_i18n.py update    # Rebuild messages.pot and merge into zh_Hans/zh_Hant PO files
# Translate new entries and remove fuzzy markers after checking fuzzy entries
.venv/bin/python scripts/framework_i18n.py compile   # Write .mo files shipped in wheels
.venv/bin/python scripts/framework_i18n.py check     # List stale outputs; no output means current
```

Extraction uses `oldman/i18n/framework-babel.cfg` and the frontend message list. It shares the function used by `i18n extract` for framework messages in projects, so both cover the same text. Add new framework directories containing messages to that configuration. Templates and PO omit line numbers, so moving code alone does not make catalogs stale. `tests/test_oldman_framework_translations.py` runs these checks in the regular test suite. Mismatched templates and source, untranslated or fuzzy entries, and mismatched MO and PO all fail. `.mo` and `.pot` are in `.gitignore`; add them by explicit path with `git add -f`.

## Versions and releases

The authoritative version is `project.version` in root `pyproject.toml`. It must be valid SemVer and PEP 440: use `0.1.1` for stable versions and `0.1.1-rc.1` for prereleases. Python artifact filenames and metadata use the normalized PEP 440 form, `0.1.1rc1`, while npm preserves the original string. Maintenance scripts convert through `python_distribution_version()` in `scripts/release_artifacts.py`; do not construct versions manually.

GitHub Actions publishes releases. Locally, perform three steps:

1. Change `project.version`, run `pnpm version:sync`, then review and commit its rewritten Python and npm version copies: `package.json`, both frontend packages, `oldman/version.py`, and `OLDMAN_WEB_VERSION`. Do not edit versions individually and overlook another package.
2. Create an annotated `v<version>` tag on that `main` commit, such as `v0.1.1` or `v0.1.1-rc.1`, then push `main` and the tag.
3. Inspect the Release run in Actions and verify PyPI, npm, and GitHub Release.

`.github/workflows/release.yml` validates that the tag equals the `pyproject.toml` version, generates release notes from commit titles as described below, and runs `pnpm build:python` and `pnpm pack:web`. It then runs `verify-wheel-contents`, `verify-sdist-contents`, `verify-python-package-install` for Python 3.12, 3.13, and 3.14, and `verify-oldman-web-package`. After every check passes, Trusted Publishing uses OIDC identity without long-lived tokens to publish to PyPI and npm and create GitHub Release. Its body contains generated release notes, with three artifacts and `SHA256SUMS` attached. If any step fails, nothing is published. After fixing the failure, delete the tag and recreate it on the new commit.

`.github/workflows/docs.yml` publishes the documentation site, `website/`, to GitHub Pages at `https://alexliyu7352.github.io/oldman/`. After Release succeeds for a stable tag without `-`, it checks out that tag, runs `pnpm verify:docs`, and deploys, keeping online documentation aligned with PyPI and npm versions. Prereleases do not update documentation. This workflow runs separately after Release rather than as a job inside it because Pages deployment environments default to allowing only the default branch and would reject a tag. To update documentation between releases, run the workflow manually in Actions and choose a branch or tag. Before first use, set repository Settings → Pages → Source to GitHub Actions.

### Commit titles and release notes

The repository maintains no CHANGELOG file. Release notes are the GitHub Release body, generated from commit titles by git-cliff using root `cliff.toml`. Each title therefore becomes a release-note entry and should be a user-facing English sentence:

```text
type(scope): summary
```

- `type` chooses the group: `feat` goes to Added, `fix` to Fixed, `perf` to Performance, `refactor` to Changed, `docs` to Documentation, and `revert` to Reverted. `test`, `build`, `ci`, `chore`, and `release` do not enter release notes.
- `scope` is optional and identifies the affected subsystem, for example `fix(web): ...`.
- `summary` appears unchanged, including case. Start lowercase unless preserving an initial command or function name. For example: `fix(db): loaddata reads back the float columns dumpdata wrote`.
- Mark breaking changes with `!` after the type, as in `feat(db)!: ...`, or a `BREAKING CHANGE: ...` footer at the end of the body. These entries appear first in release notes.
- Choose dependency-change `type` by its user-visible effect, rather than using `build`. Adding or removing dependencies, narrowing or widening version ranges, and changing optional groups affect what users install and must appear in release notes. Use `feat`, `fix`, or `refactor` as appropriate, adding `!` when existing projects can no longer install or must change code, for example `fix(db)!: require SQLAlchemy below 2.1`. `build` is only for build changes that do not affect installation results.
- Commit bodies do not enter release notes. Use them for rationale and implementation details.
- Titles outside the format still appear under Other rather than being discarded, but should be avoided.

Stable release notes start at the preceding stable version and include intervening prerelease commits. Prerelease notes start at the previous tag. Preview the generated notes locally before releasing:

```sh
uvx git-cliff@2.14.2 --unreleased
```

Commit titles cannot be changed after pushing. Correct mistakes by editing the Release body directly.

Versions containing `-` are prereleases. PyPI treats them as such, so `pip install oldman` does not select them by default without `--pre` or an exact version. npm publishes them to the `next` dist-tag, leaving `latest` unchanged. GitHub Release marks them as prereleases. Rehearsing publication with a prerelease does not affect stable users.

`.github/workflows/ci.yml` runs static checks and Python and frontend tests for every push and pull request. Real-service checks require `redis-server` version 6.2 or later from apt, and `nats-server`, downloaded at a pinned version and checked against SHA-256 by the workflow. Missing executables fail rather than skip; see [Test isolation requirements](testing.md#real-service-checks).

Use the same commands to verify release artifacts locally:

```sh
pnpm build:python
pnpm pack:web
```

The first command builds Admin and then creates the wheel and sdist. The second builds and packages oldman-web. Stable-version artifacts are currently located at:

- `dist/oldman-<normalized-Python-version>-py3-none-any.whl`
- `dist/oldman-<normalized-Python-version>.tar.gz`
- `frontend/packages/oldman-web/oldman-web-<version>.tgz`

Prerelease Python filenames may be normalized. Maintenance tools calculate paths through `scripts/release_artifacts.py`, rather than guessing from modification times or globs. Installation checks must use the actual intended release files and hashes. An editable installation does not verify a wheel.

The Python package includes runtime code, templates, Admin builds, migrations, scaffolds, and required MO files. Licensing material ships with it. The sdist has explicit content rules; a file's presence in the source directory does not guarantee inclusion in release artifacts.

## Full verification in serial stages

Run these stages only when preparing a release or when full acceptance is explicitly requested. Diagnose a failed stage before proceeding; do not run every command in the background at once:

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

- static runs Python lint and format checks, `ruff check` and `ruff format --check`, with code formatted by `ruff format`. It also runs pyright and Pyrefly type checks. Pyrefly is pinned in the dev dependencies of `pyproject.toml` and configured under `[tool.pyrefly]`.
- python runs the full Python test suite.
- frontend runs tests and type checks for both frontend packages.
- web-boundaries runs the existing frontend boundary checks.
- web-package verifies current npm artifacts and real consumers.
- python-package checks wheel and sdist contents, installation on Python 3.12 through 3.14, and built-in Admin in Chrome. The Release workflow runs the parts that do not require a browser.
- scaffold-matrix creates projects from actual release artifacts and verifies generated services, including browser checks where needed. API projects also create an App using the mcp template in `startapp`, wire `install_mcp` according to [MCP server](mcp.md), and invoke its tools with the generated API key using both the handshake generation and 2026-07-28 protocols.
- docs installs `website/` dependencies and builds the documentation site in three languages: English, Simplified Chinese, and Traditional Chinese. Traditional Chinese is not translated: staging converts the Simplified pages with OpenCC using Taiwan vocabulary, leaving code blocks and inline code unchanged. Dead links fail the build. Invalid anchors currently warn because untranslated pages fall back to Chinese during translation and temporarily do not match translated anchors. CI also runs this on 3.12.

Package and scaffold stages create isolated environments, download dependencies, and build, consuming substantially more disk and memory than ordinary unit tests. Check available disk space, memory, and running services first, and run only one Chrome task at a time. No fixed space limit applies to every machine; environments and download caches change actual usage.

These entry points retain evidence under `/tmp/oldman-*-evidence` by default and do not automatically delete all results afterwards. For an explicit location, invoke the corresponding `scripts/verify-current-release-*.py --evidence-root /tmp/task-owned-parent` directly. Each invocation creates a separate run directory. Do not use shared user directories as cleanup targets.

Inspect the relevant result.json, logs, and browser screenshots, then record conclusions. Archive required evidence to the user's chosen location, confirm that this invocation's processes have exited, and delete **that exact run directory**. Do not recursively delete all of `/tmp` or arbitrary wildcard directories.

The advanced `--use-existing-artifacts` path requires corresponding SHA-256 values; a filename alone does not bypass build verification. Consult the script's --help for arguments. Ordinary maintainers can use the default stage entry points.

## Publishing is not a testing side effect

Building and verification do not upload automatically. Before publication, explicitly establish target registries, account permissions, version, licensing, release notes, and rollback arrangements. Once publication is authorized, upload the same verified artifacts. Do not verify one set and rebuild another immediately before uploading.

Report stages not run, known failures, deprecation warnings, and manual operations not performed. Rewritten documentation or a few passing targeted checks do not establish full acceptance for that invocation, nor prove that an external package registry contains the version.

<!-- source: zh/developers/maintenance.md @ d1b215e4 -->
