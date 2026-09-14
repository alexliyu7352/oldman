[project]
name = "{{ project_slug }}"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "oldman>={{ framework_version }}",
{{ db_dependency_line }}
]

[tool.oldman]
project_id = "{{ project_id }}"

[tool.uv]
package = false
