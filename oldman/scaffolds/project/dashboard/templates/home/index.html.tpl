{% extends "base.html" %}
{% from "oldman/dashboard/components/page_head.html" import page_head with context %}

{% block title %}{{ _("Home") }} · {{ site_name() }}{% endblock %}

{% block content %}
  <div class="om-page-section">
    {{ page_head(_("Welcome, %(name)s", name=request.ctx.user.display_name or request.ctx.user.username)) }}

    <div class="grid gap-4 md:grid-cols-3">
      {% for label in (_("First figure"), _("Second figure"), _("Third figure")) %}
        <div class="om-card om-stat-card">
          <p class="om-stat-label">{{ label }}</p>
          <p class="om-stat-value">—</p>
          <p class="om-stat-meta">{{ _("Replace with your own numbers in apps/home/views.py.") }}</p>
        </div>
      {% endfor %}
    </div>

    <div class="om-card">
      <div class="om-card-header">
        <h2 class="om-card-title">{{ _("Next steps") }}</h2>
      </div>
      <div class="om-card-body space-y-2 text-sm">
        <p>{{ _("Add a page with ./run.sh startapp, then give it a link in templates/partials/sidebar.html.") }}</p>
        <p>{{ _("The sign-in, account and user pages come from the framework; a file of the same name under templates/ replaces one.") }}</p>
        <p>{{ _("Who may sign in, and with what permissions, is set in apps/accounts/routes.py and through roles.") }}</p>
      </div>
    </div>
  </div>
{% endblock %}
