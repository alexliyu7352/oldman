{% extends "base.html" %}

{% block content %}
<main>
    <h1>{{ project_name }}</h1>
    <p>{{ _("This page is apps/home/views.py with templates/home/index.html; change it, or remove apps.home from the settings.") }}</p>
{{ web_home_admin }}
    <h2>{{ _("Next steps") }}</h2>
    <ul>
        <li>{{ _("Add a page with ./run.sh startapp, then list the new App under apps in data/{{ service_name }}_settings.yaml.") }}</li>
        <li>{{ _("Every page extends templates/base.html; a file of the same name under templates/ replaces a framework template.") }}</li>
        <li>{{ _("For more languages, turn on i18n in the settings and follow the translation steps in README.md.") }}</li>
    </ul>
</main>
{% endblock %}
