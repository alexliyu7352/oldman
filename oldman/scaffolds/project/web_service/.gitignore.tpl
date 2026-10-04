/.venv/
__pycache__/
/data/*_settings.yaml
/data/*.db
/logs/
/pids/
/static/dist/
# `static collect` copies the framework's files (the Admin's included) into static/oldman/ and lists them in the
# manifest below. An App with a static/ folder of its own is copied into static/<that folder's name>/: ignore it too.
/static/oldman/
/.static.oldman-static.json
# The framework docs AGENTS.md has an agent clone for the installed version.
/.oldman-docs/
