# Agent instructions for {{ project_name }}

This project is built on the Oldman framework (Python package `oldman`). Read this whole file
before changing anything. Every rule under "Rules" is mandatory.

## Before writing code

1. Get the installed framework version: `{{ agents_version_command }}` (prints `oldman X.Y.Z`, written
   as its release tag is, a prerelease too: `oldman 0.6.0-rc.1` is tag `v0.6.0-rc.1`).
   Get the framework docs for exactly that version, once per project:
   `git clone --depth 1 --branch vX.Y.Z https://github.com/alexliyu7352/oldman.git .oldman-docs`
   If `.oldman-docs` exists for another version, delete it and clone again. Read and grep the docs
   under `.oldman-docs/docs/public/`; the framework source for that version is there too.
{{ agents_guide_step }}{{ agents_index_step }}. Look up every `oldman` import in the public API index before using it: start at
   `.oldman-docs/docs/public/en/api/README.md`, then open the package's page.
   Do not guess module paths, class names or attributes.

## Rules

{{ agents_rules }}
## Facts

{{ agents_facts }}
## Done means

{{ agents_done }}