[ignore: .venv/**]
encoding = utf-8

[ignore: node_modules/**]
encoding = utf-8

[ignore: scripts/**]
encoding = utf-8

[ignore: tests/**]
encoding = utf-8

[python: apps/**.py]
encoding = utf-8

[python: config/**.py]
encoding = utf-8

[python: core/**.py]
encoding = utf-8

[python: services/**.py]
encoding = utf-8

[jinja2: templates/**.html]
encoding = utf-8
extensions=jinja2.ext.i18n,oldman.web.template.I18nExtension,oldman.web.security.csrf.CsrfExtension
silent=False
