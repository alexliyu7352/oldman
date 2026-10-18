[project]
name = "{{ project_slug }}"
version = "0.1.0"
requires-python = ">=3.12, <3.15"
dependencies = [
    "oldman>={{ framework_version }}",
{{ db_dependency_line }}
]

[tool.oldman]
project_id = "{{ project_id }}"

[tool.uv]
package = false

[tool.ruff]
# Oldman's own code is formatted to 150 columns; ruff's default would be 88.
line-length = 150
