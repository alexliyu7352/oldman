{% extends "base.html" %}
{% from "oldman/dashboard/components/page_head.html" import page_head with context %}

{% block title %}{{ _({{ display_name_literal }}) }} · {{ site_name() }}{% endblock %}

{% block content %}
  <div class="om-page-section">
    {{ page_head(_({{ display_name_literal }})) }}

    <div class="om-card">
      <div class="om-card-body text-sm">{{ _("Replace this with the page's content.") }}</div>
    </div>
  </div>
{% endblock %}
