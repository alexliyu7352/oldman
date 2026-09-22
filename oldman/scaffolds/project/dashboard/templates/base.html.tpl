{% extends "oldman/dashboard/base.html" %}
{% from "oldman/dashboard/partials/shell.html" import dashboard_main_frame, dashboard_sidebar, sidebar_menu_link with context %}
{% from "oldman/dashboard/partials/topbar.html" import dashboard_topbar with context %}

{% set scaffold_brand_subtitle %}{{ project_name }}{% endset %}

{% block title %}{{ project_name }}{% endblock %}

{% block dashboard_head_meta %}
  <meta name="oldman-asset-base" content="{{ bundle_asset_base_url(app_main_bundle) }}">
{% endblock %}

{% block dashboard_head_assets %}
  {{ bundle_entry(app_main_bundle, include_dev_client=true) }}
{% endblock %}

{% block dashboard_sidebar %}
  {% call dashboard_sidebar(dashboard_home_href | default("/"), _("Menu"), brand_subtitle=scaffold_brand_subtitle | trim, declarative_menu=true) %}
    {% for item in dashboard_menu_items | default(()) %}
      {{ sidebar_menu_link(item.href, _(item.label), icon=item.icon | default("ri-dashboard-2-line"), active=item.active | default(false)) }}
    {% endfor %}
  {% endcall %}
{% endblock %}

{% block dashboard_topbar %}
  {{ dashboard_topbar(
    activity_notifications=dashboard_activity_notifications | default(()),
    activity_href=dashboard_activity_href | default(none),
    language_switcher=dashboard_language_switcher | default(none),
    account_controls=dashboard_account_controls | default(none)
  ) }}
{% endblock %}

{% block dashboard_content %}
  {% call dashboard_main_frame() %}
    {{ super() }}
  {% endcall %}
{% endblock %}
