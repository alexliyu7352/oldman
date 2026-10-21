# Run and understand the Admin Demo

The actual example of the built-in Admin is the standalone [Oldman Admin Demo](https://github.com/alexliyu7352/oldman-admin-demo). The EPG demo's user management page is a business dashboard. Installing the Admin App in EPG does not imply that it provides an automatically generated /admin site.

This chapter uses the Admin demo's own `DemoProject` and `DemoProjectAdmin`, rather than treating EPG's ExampleProject as an already registered Admin model. The two repositories each have their own virtual environment, configuration, and SQLite database.

## 1. Initialization and operation

Run all commands in the **Admin demo root**. Prepare an accessible Redis first; Session defaults to local 6379/5 and SSE to 6379/6. Check the [example YAML](https://github.com/alexliyu7352/oldman-admin-demo/blob/main/data/web_settings.example.yaml), and do not point it at a production database.

First run:

```sh
python3 scripts/bootstrap.py
./run.sh web settings init
./run.sh web settings sync
./run.sh db migrate
./run.sh web loaddata demo
./run.sh web createsuperuser
pnpm --dir frontend build
./run.sh web static collect
./run.sh web start
```

init reads the demo's example YAML to create local configuration. Skip init if web_settings.yaml already exists; do not overwrite it. Follow the migration prompts to check first use or existing state. createsuperuser creates your own account using hidden password input; do not put passwords in command arguments or Git.

Open [http://127.0.0.1:17999/admin](http://127.0.0.1:17999/admin), rather than EPG's 17997. The example sets `web.domain` to `http://127.0.0.1:17999`, which builds links in password reset emails. Change it together with `web.listen_port` when changing ports or deploying to a domain. Use `./run.sh web changepassword <用户名>` to change passwords, replacing the placeholder with the username you created.

bootstrap selects local source or a release package in the same way as EPG: it links directly to source when a sibling oldman_framwork or oldman source directory exists; otherwise, it uses the release package in the manifest. Do not install either demo into the framework's own environment.

`loaddata demo` reads [apps/demo/fixtures/demo.json](https://github.com/alexliyu7352/oldman-admin-demo/blob/main/apps/demo/fixtures/demo.json), explicitly importing 25 real project records without creating users. Normal startup only initializes the framework/site. It does not import data, reset passwords, or delete users automatically; project edits and deletions persist through restart. If you already have projects and do not need preset data, skip the import and create your own records in Admin.

The fixture uses primary keys 1–25. Reimporting updates the file's specified fields by primary key, rather than only filling missing data. Existing records with the same name but different primary keys violate the unique constraint and roll back the entire file. Run it only against your own demo database, without overwriting business records. Older versions created fixed test accounts such as browser_staff and browser_superuser_guard at startup. Source upgrades do not arbitrarily delete existing accounts; inspect your Admin and disable/delete unneeded accounts. Do not expose fixed test passwords in public services. Only the isolated browser verification script now creates these test accounts.

## 2. See the actual model with ModelAdmin

The model is located at [apps/demo/models.py](https://github.com/alexliyu7352/oldman-admin-demo/blob/main/apps/demo/models.py), and the database table is `admin_demo_project`, including name, owner, status, is_active, and created_at. The label of the App is `demo`, and the display name and icon are defined in [apps/demo/apps.py](https://github.com/alexliyu7352/oldman-admin-demo/blob/main/apps/demo/apps.py).

The complete code of [apps/demo/admin.py](https://github.com/alexliyu7352/oldman-admin-demo/blob/main/apps/demo/admin.py):

```python
"""Admin registrations for demo models."""

from oldman.apps.admin import ModelAdmin


class DemoProjectAdmin(ModelAdmin):
    """Admin presentation for demo projects."""

    require_superuser = True
    list_display = ("id", "name", "owner", "status", "is_active", "created_at")
    search_fields = ("name", "owner", "status")
    readonly_fields = ("created_at",)
    ordering = ("name",)
```

This model therefore requires a superuser. The site setting `require_superuser: false` only allows active staff users to sign in to the site; it does not remove stricter model restrictions. created_at is read-only, and the default ordering is by name.

The first-level menu uses the App's display_name/icon, and the second-level menu uses the model display name; modifying the display text does not change the database table name and URL identifier.

## 3. Registering an app does not mean installing the site

The service YAML installs oldman.auth, oldman.apps.admin, the notifications App, and apps.demo. After models enter the Registry, Admin still needs explicit site wiring.

In WebService.init of [services/web.py](https://github.com/alexliyu7352/oldman-admin-demo/blob/main/services/web.py):

1. Execute super().init() to obtain the initialized runtime_app.
2. Import DemoProject, DemoProjectAdmin, and the default User used by the current example.
3. Create AdminSite, register User and DemoProject.
4. Register the Demo's own extension CSS bundle.
5. Call install_admin to hand over the site and extension bundles to the framework.

The original model registration excerpt:

```python
        admin_site = AdminSite("oldman_admin_demo")
        admin_site.register(User, AdminUserModelAdmin)
        admin_site.register(DemoProject, DemoProjectAdmin)
```

The original site installation in the same method:

```python
        install_admin(
            app,
            admin_site=admin_site,
            dev_mode=local_frontend,
            dev_server_url=(
                settings.web.frontend.vite_dev_server_url if local_frontend else ""
            ),
            extension_bundle_name=ADMIN_EXTENSION_BUNDLE,
            auth_settings=auth_app.settings,
            admin_settings=admin_app.settings,
        )
```

This is not a standalone fragment: app comes from runtime_app, local_frontend is the source debugging switch for this Demo, ADMIN_EXTENSION_BUNDLE is a constant from the service module; the full build of StaticBundleRegistry is still in the same init method. Don't just copy the last call and miss the previous resource registration.

Both the framework and this Demo use global settings and the App's own strongly typed settings, and do not copy the configuration in app.ctx; the necessary prerequisites for install_admin are the loaded service/App configuration and site registration, not another settings object.

install_admin wires shared templates, CSRF, assets, and routes. Installing the Admin App, registering models, and installing the site are separate steps. The existence of a model file does not automatically authorize it to appear in the admin menu.

## 4. Resource and source code debugging

The built-in Admin's browser assets ship with the Python package, so applications can use it without rewriting the frontend. This demo adds its own style bundle, so its README also requires building frontend.

Production mode reads the built manifest. To debug local source, stop the production service you started, then run:

```sh
python3 scripts/dev.py
```

The Demo script manages the web with two Vite services: the built-in Admin uses 5173, and the Demo extension uses 5174. It does not change the semantics of run.sh. When resource loading fails, check [frontend build configuration](https://github.com/alexliyu7352/oldman-admin-demo/tree/main/frontend), static collection and service bundle, and do not copy the hashed script address to the template.

## 5. Practical inspection

Sign in with the superuser you created and operate one of your own projects:

- Create, search, edit, and reopen; confirm that field values actually persist, rather than checking only the success message.
- Leaving required fields blank should fail without adding a new row.
- Ordinary staff sign-in does not grant access to Project administration requiring require_superuser. Do not lower permissions to pass a test.
- The left side should be grouped by Apps, with models in a secondary menu, rather than a flat Models list.
- Deleting your own project requires confirmation; canceling does not change the record.
- Accessing protected pages after signing out should require sign in.
- CSRF 403 appears after leaving the page for a long time. You should refresh to obtain a new token; do not disable CSRF.

See [ModelAdmin Reference](../developers/admin.md#modeladmin) when you need to customize forms, columns, save rules, or permissions. The project template is overwritten by the template of the same name in settings.web.template.dir, and the installation package resources are not directly modified. Use extension bundle for additional icons and CSS, do not create a separate Admin Form/Modal.

## 6. Retrieve password

Use “Forgot password?” at the lower right of the sign-in card to open `/admin/password-reset`. The flow matches Django:

1. Enter your account email and submit. The page always opens “Check your email”, whether an account exists or not, without revealing account existence. If an active account exists, its inbox receives an email with a link.
2. Open the email link (`web.domain` plus `/admin/password-reset/<用户标识>/<token>`), set a new password, and confirm it. Rules match Admin password changes: 8 to 128 characters, including both letters and digits.
3. After the change, all of that user's sign-in sessions in other browsers are invalidated, and the page asks them to sign in with the new password.

Links are valid for 24 hours by default and become invalid after a password change, signing in again, or expiry. Each link can be used only once. Accounts without email cannot use self-service recovery; an administrator can change their password in the user list. Each IP can request at most 5 resets per 15 minutes (excess requests return 429), and each email address can receive at most 3 emails per hour (excess requests still display “Sent” but send no email). These values are in the Auth App's `password_reset` settings; see [Configuration](../developers/configuration.md#app-settings).

When developing locally, the default email backend is console, and the email and link will be printed in the service log; for actual sending of emails, you need to configure `mail.backend` as smtp, see [Mail](../developers/mail.md).

## FAQ

| Symptom | Check |
| --- | --- |
| No createsuperuser command | Is oldman.auth installed for this service? |
| App auth is not installed | Does the current YAML install oldman.auth, and has settings sync run? |
| Page returns 404 | Are the correct demo and port running, and does the service call install_admin? |
| Model absent from the menu | Is ModelAdmin registered, and does the current user meet model permissions? |
| User can sign in but Project access is denied | DemoProjectAdmin.require_superuser is explicitly true |
| Missing manifest or icons | Are production assets built/collected, and does the extension bundle exist? |
| New database has no preset projects | Migrate, then explicitly run web loaddata demo; startup does not create demo data |
| Name conflict during import | Check existing same-name records and fixture primary keys; do not clear the database or merge by name automatically |

Read [Deployment and operations](deployment.md) before deployment. Being able to run the demo does not mean production security configuration is complete.

<!-- source: zh/users/admin.md @ 25b7ec11 -->
