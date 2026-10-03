{#- Every page of the dashboard, the framework's account pages included: sidebar, topbar, language and account menu. -#}
{% extends "oldman/dashboard/base.html" %}
{% from "oldman/dashboard/partials/shell.html" import dashboard_main_frame, dashboard_sidebar with context %}
{% from "oldman/dashboard/partials/topbar.html" import dashboard_topbar with context %}
{% from "oldman/auth/partials/account_controls.html" import user_account_controls with context %}
{% set urls = account_urls(request) %}

{% block dashboard_language %}{{ current_language(request) }}{% endblock %}

{% block dashboard_head_meta %}
  <meta name="csrf-token" content="{{ csrf_token_for(request) }}">
  <meta name="oldman-asset-base" content="{{ bundle_asset_base_url(app_main_bundle) }}">
  {% if urls.user_events %}
    <meta name="oldman-user-events-url" content="{{ urls.user_events }}">
  {% endif %}
{% endblock %}

{% block dashboard_head_assets %}
  {{ bundle_entry(app_main_bundle, include_dev_client=true) }}
{% endblock %}

{% block dashboard_sidebar %}
  {% call dashboard_sidebar(urls.home, _("Menu"), declarative_menu=true) %}
    {% include "partials/sidebar.html" %}
  {% endcall %}
{% endblock %}

{% macro language_switcher() %}
  {% include "oldman/dashboard/partials/language_switcher.html" %}
{% endmacro %}

{% macro account_controls() %}
  {{ user_account_controls(
    display_name=request.ctx.user.display_name or request.ctx.user.username,
    session_path=urls.profile,
    logout_path=urls.logout,
    subtitle=site_name()
  ) }}
{% endmacro %}

{% block dashboard_topbar %}
  {{ dashboard_topbar(
    user_notification_urls=urls.notifications,
    language_switcher=language_switcher,
    account_controls=account_controls
  ) }}
{% endblock %}

{% block dashboard_content %}
  {% call dashboard_main_frame() %}
    {{ super() }}
  {% endcall %}
{% endblock %}
