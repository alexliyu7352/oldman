apps:{{ settings_apps }}
core:
  site_name: {{ project_name_yaml }}
app_settings:
  auth:
    user_model: apps.accounts.models.User
database:
  url: {{ database_url }}
web:
  session:
    enabled: true
