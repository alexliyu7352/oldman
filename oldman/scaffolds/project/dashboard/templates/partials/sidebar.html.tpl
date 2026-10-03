{#- The menu: the only place its entries are listed. A new page gets its link here. -#}
{% from "oldman/dashboard/partials/shell.html" import sidebar_menu_group, sidebar_menu_item, sidebar_menu_link with context %}
{% set urls = account_urls(request) %}
{% set notifications_url = urls.notifications.center if urls.notifications else none %}

{{ sidebar_menu_link(urls.home, _("Home"), "ri-home-4-line", active=request.path == urls.home) }}

{% set system_paths = [urls.profile, urls.users, notifications_url] %}
{% set system_active = namespace(value=false) %}
{% for path in system_paths if path and (request.path == path or request.path.startswith(path ~ "/")) %}
  {% set system_active.value = true %}
{% endfor %}
{% call sidebar_menu_group("system-menu", _("System"), "ri-settings-3-line", active=system_active.value) %}
  {% if can_manage_users(request) %}
    {{ sidebar_menu_item(urls.users, _("Users"), active=request.path == urls.users or request.path.startswith(urls.users ~ "/")) }}
  {% endif %}
  {% if notifications_url %}
    {{ sidebar_menu_item(notifications_url, _("Notifications"), active=request.path == notifications_url) }}
  {% endif %}
  {{ sidebar_menu_item(urls.profile, _("My account"), active=request.path == urls.profile or request.path.startswith(urls.profile ~ "/")) }}
{{ dashboard_sidebar_admin }}{% endcall %}
