apps:{{ settings_apps }}
core:
  site_name: {{ project_name_yaml }}
{{ settings_user_model }}database:
  url: {{ database_url }}
web:
  session:
    enabled: true
