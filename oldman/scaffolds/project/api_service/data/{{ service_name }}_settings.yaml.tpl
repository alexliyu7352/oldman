apps:{{ settings_apps }}
database:
  url: {{ database_url }}
web:
  auth:
    # How programs sign in to /api/caller and /api/ops (apps/home/views.py); generated for this project.
    authenticators: [api_key, http_basic]
    api_keys:
      example:
        secret: "{{ api_example_key }}"
    http_basic:
      accounts:
        ops: "{{ api_ops_password }}"
