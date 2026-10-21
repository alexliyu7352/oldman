# Dashboard UI and interactive components

This page helps you choose and integrate existing components. Examples come directly from the EPG demo, retaining actual class names, attributes, routes, and translation calls. Code blocks are excerpts from the corresponding templates or classes, rather than complete new pages. Prepare the demo following [Getting started](getting-started.md), then open the paths below. The default address is `http://127.0.0.1:17997`.

Static Cards and button appearance need only HTML/CSS; interactions such as Dropdown also require Page to mount components. Admin and business dashboards share components and visual variables, but page entry points determine enabled loaders. Copying HTML does not start every capability automatically. See the [Demo tutorial](tutorial-dashboard.md) for complete Form/Modal/Table wiring and the [Example index](demo-examples.md) for all pages.

## Why does the example work directly?

Demo's [views/ui.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/ui.py) processes `/examples/ui/<page>`, verifies the page name and provides template context such as `page_entry="examples"`; the entrance only requires sign in.

Template and browser wiring are:

1. The UI template inherits [pages/examples/base.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/base.html) and puts the content into example_content. This template then inherits the application [base.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/base.html) and uses the shared Dashboard shell, main content Frame and resource tags.
2. [main.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/main.ts) loads [ExamplesPage](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/pages/examples.ts) according to the page entry. It inherits the application [BasePage](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/pages/base-page.ts), which uses createDashboardComponentLoaders and already contains the following shared interactive components.
3. ExamplesPage also registers five Demo private components: navigation-probe, example-chart, realtime-table, icon-catalog, and feedback-workflow. Ordinary Tabs, Slider, and Alert are already in the shared loader and do not need to be registered as global components.
4. Both initial visits and Turbo dynamic entry pages mount content through the Page lifecycle; old instances are cleaned up when leaving. The remote Modal insertion content is already dynamically mounted, so do not write another set of scripts to initialize the plug-in for it.

The complete code of these steps can be found in [Front-end Entry and Lifecycle](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/frontend.md#demo-的-dashboard-页面入口), and the construction and CSS wiring can be found in [Resource Reference](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/assets.md). The following `{{ _("...") }}` is a Jinja translation call and needs to be rendered by the backend; it cannot be saved as a browser static HTML. data-example-* is the positioning or private interaction tag of Demo, not the framework component API; the corresponding attributes and consumers must still be retained when copying private interactions.

## Distinguish three capabilities

| Need | Usage |
| --- | --- |
| Button, Card, Badge, progress, layout, static table | HTML and shared CSS, do not force the creation of JS components |
| Tabs, Dropdown, Tooltip, Modal, Slider and other interactive components | declare components, mounted by Page loader |
| Database writes, permission checks, persistent notifications | Backend capabilities; components submit and display, without replacing the server |

### Cards, buttons and states

Open `/examples/ui/cards`, the following is the complete Standard card in [cards.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/ui/cards.html):

```jinja
    <article class="om-card">
      <div class="om-card-header"><h2 class="om-card-title">{{ _("Standard card") }}</h2><span class="om-badge om-badge-primary">{{ _("Live") }}</span></div>
      <div class="om-card-body"><p class="text-sm leading-6 text-content-muted">{{ _("Use a card for one coherent group of information or controls.") }}</p></div>
      <div class="om-card-footer justify-end"><button type="button" class="om-button om-button-light om-button-sm">{{ _("Cancel") }}</button><button type="button" class="om-button om-button-primary om-button-sm">{{ _("Save") }}</button></div>
    </article>
```

This Card's Save/Cancel buttons demonstrate appearance and have no save interface. Display text does not establish a completed business operation. Actual database writes are in the Form/Table tutorial. The full page also includes compact, flat, accent, and responsive content cards.

[buttons.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/ui/buttons.html) at `/examples/ui/buttons` includes solid, soft, outlined, dashed, ghost, and text buttons, plus sizes, rounded corners, and icon buttons. The following state group is an unchanged excerpt:

```jinja
      <div class="flex flex-wrap items-center gap-3">
        <button type="button" class="om-button om-button-primary" aria-pressed="true">{{ _("Pressed") }}</button>
        <button type="button" class="om-button om-button-primary" aria-busy="true"><span class="om-button-spinner" aria-hidden="true"></span>{{ _("Saving") }}</button>
        <button type="button" class="om-button om-button-primary" disabled>{{ _("Disabled") }}</button>
        <button type="button" class="om-button om-button-light" disabled><i class="ri-lock-line" aria-hidden="true"></i>{{ _("Unavailable") }}</button>
      </div>
```

aria-busy and spinner are static demonstrations here, not sending requests; real requests are managed by the existing loading process of the Form/Action. disabled uses the native button attribute. Check focus with Tab, icon-only buttons retain aria-label or sr-only text.

Semantic colors include primary, success, info, warning, and danger; which variants are supported by specific components are subject to the corresponding page and shared style, and non-existent classes are not randomly spliced. Don’t substitute clicks on the entire card for explicit links within it. See `/examples/ui/badges-avatars` for Badge/avatar, and `/examples/ui/progress-loading` for progress and placeholder.

### Usage syntax: which button goes where

Shared styles divide emphasis into fixed layers, and the page author only needs to decide "which layer this action belongs to":

| Level | class | Where to use |
| --- | --- | --- |
| primary | `om-button-primary` | One per region: the page header's main action, form footer save, or modal confirmation |
| secondary | `om-button-secondary` (`om-button-light` is an alias) | Default for other actions: outline and surface background, filter bars, card headers, table toolbars, cancel |
| soft | `om-button-soft-primary` / `om-button-soft-secondary` | Only for option groups side by side in card headers; do not mix with secondary in one row |
| ghost | `om-button-ghost-secondary`, usually with `om-button-icon` | Icon-only actions: row/card header “More”, close |
| link | `om-button-link` | Only within a sentence, such as “View all” |
| destructive | `om-button-danger` | Final deletion on confirmation modals/pages; list delete entry points use `om-dropdown-item om-dropdown-item-danger` menu items |

The sizes are `om-button` (36px), `om-button-sm` (32px, filter bar and card header), `om-button-lg` (40px, sign in), `om-button-xs` (24px, only for table rows). Add `om-button-icon` to the icon button, and the `<i>` in the button will automatically be typeset at 16px and optically centered. `mr-1`/`align-bottom` is no longer needed.

Boolean fields default to switch cards (`SwitchCardWidget`): a 14/500 label and 12px help text on the left, an 18×32 switch on the right, aligned to equal heights when side by side. For checkbox rows or borderless switch rows, pass `widget=CheckboxWidget()` / `widget=SwitchWidget()` to the field. Use layout `FieldGroup` for a heading over Boolean fields.

Badges: `om-badge om-badge-success|info|warning|danger|primary` is a soft badge with 6px dots for status, boolean and role; `om-badge om-badge-default` is a stroked badge for count, label and version. There is only one set of check boxes and radio selections: `om-check` / `om-radio`; the selected state of the table row is derived from the `:checked` of the check box in the row, and no additional class is needed.

### Page headers, table cards, and states

```jinja
{% from "oldman/dashboard/components/page_head.html" import page_head with context %}

{% call page_head(_("Users"), description=_("Staff accounts.")) %}
  <a class="om-button om-button-primary" href="{{ admin_prefix }}/oldman_user/new"><i class="ri-user-add-line" aria-hidden="true"></i><span>{{ _("New User") }}</span></a>
{% endcall %}
```

On desktop the sidebar collapses to a 48px icon rail. Link-only menu items use `data-om-component="tooltip"` to show names to the icon's right. Groups with submenus need no extra markup: after a 200ms hover, a click, or Arrow Right, the sidebar script opens a panel beside the icon, showing the group name and child links with the current page highlighted. Arrow keys, Home, and End navigate the panel; Esc closes it and returns focus to the icon.

`page_head` outputs a 22px title, optional 14px description, and right-hand action slot. Breadcrumbs are automatic: after each Turbo frame switch and sidebar highlight update, the top bar builds “Sidebar group › Current menu item › Page title”, merging identical title/menu names. Pages need no extra markup. Special pages needing another record-name level pass `breadcrumbs=[{"label": ..., "href": ...}, ...]`. The macro outputs `<template data-om-breadcrumb>` with the page, and the top bar mirrors this explicit declaration first; pages may also output that `<template>` themselves. List pages follow this order: page header → filter toolbar (`om-filter-toolbar`, rendered by TableFilterForm; a single row by default, with gray prefix labels to the left of controls, search filling remaining width, `advanced=True` fields in a “More filters” panel, and “Reset / Filter” on the right; set `layout_style` to `grid` for labels above many fields) → `om-card om-table-card` (divided header, unpadded body; the table shell toolbar has search, selected count, and bulk actions on the left, with small outlined columns/density/export buttons on the right; fitting tables have headers sticky below the top bar, otherwise horizontal scrolling; empty bodies show an empty-state component with “Reset filters” for filtered no-results; the footer provides pagination). Form pages put forms inside `om-card om-form-card`, with a sticky save/cancel footer.

The footer is `oldman/dashboard/partials/footer.html`, the Dashboard basic template includes it through the `dashboard_footer` block, and the same file is included below the sign-in card; the default output is "© Current Year Oldman" (template global `current_year()`), and the project can replace it with its own copyright information by placing the file with the same path in its own template directory.

Use `om-empty` in empty state (can add `om-empty-sm`): `om-empty-icon`, `om-empty-title`, `om-empty-description`, `om-empty-actions`. Skeleton screen uses `om-skeleton` (`om-skeleton-text` / `-title` / `-circle`). To switch the option group, use `om-segmented` (`om-segmented-sm`) plus `om-segment` to select the item label `aria-pressed="true"` or `aria-current="page"`. The statistics card uses `om-stat-card`: `om-stat-label` → `om-stat-value` → `om-stat-meta`, and `om-stat-icon` can be placed in the upper right corner.

## Alert: in-page messages

[alerts.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/ui/alerts.html) at `/examples/ui/alerts` shows both static and dismissible alerts. This is a complete dismissible Alert:

```jinja
      <div class="om-alert-warning om-alert-layout" role="alert" data-om-component="alert">
        <i class="om-alert-icon ri-error-warning-line" aria-hidden="true"></i>
        <div class="om-alert-content"><strong class="om-alert-title">{{ _("Review required") }}</strong><span class="om-alert-description">{{ _("Three channel mappings need a manual decision before publishing.") }}</span><a class="mt-2 inline-flex font-medium underline underline-offset-2" href="/match-decisions">{{ _("Open review queue") }}</a></div>
        <button type="button" class="om-alert-dismiss" data-om-alert-dismiss aria-label="{{ _('Dismiss alert') }}"><i class="ri-close-line" aria-hidden="true"></i></button>
      </div>
```

Clicking Close only hides the current prompt and issues om:alert:dismiss. It does not write to the database or record that the user has "read". The review entrance here is the Demo business page; when copying it to your own business, you should replace the link and description, and you cannot use a non-existent review address.

Static Alert needs no data-om-component; declare alert only for dismiss behavior. Form server messages use Form's dedicated region. Cookie flash messages and persistent notifications have separate storage flows, outside the Alert component.

## Dropdown, Tooltip and Popover

The three are concentrated in `/examples/ui/dropdowns-overlays`, and the source code is [dropdowns-overlays.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/ui/dropdowns-overlays.html).

### Dropdown

The first Dropdown on the page is as follows:

```jinja
        <div class="om-dropdown" data-om-component="dropdown" data-example-dropdown>
          <button type="button" class="om-button om-button-primary" data-om-dropdown-toggle aria-expanded="false">
            {{ _("Project actions") }}<i class="ri-arrow-down-s-line" aria-hidden="true"></i>
          </button>
          <div class="om-dropdown-menu hidden" data-om-dropdown-menu hidden>
            <button type="button" class="om-dropdown-item"><i class="ri-edit-line" aria-hidden="true"></i>{{ _("Edit project") }}</button>
            <button type="button" class="om-dropdown-item"><i class="ri-file-copy-line" aria-hidden="true"></i>{{ _("Duplicate") }}</button>
            <button type="button" class="om-dropdown-item text-danger-600"><i class="ri-delete-bin-line" aria-hidden="true"></i>{{ _("Archive project") }}</button>
          </div>
        </div>
```

The component handles menu switches, external clicks, Escape, and positioning after scrolling/window size changes; do not add additional document click monitoring. Use `om-dropdown-item om-dropdown-item-danger` for dangerous items (`text-danger-600` in the example is the old way of writing), `om-dropdown-label` for group labels, and `om-dropdown-divider` for separators. Right-align and add om-dropdown-menu-end to the menu; the instance exposes toggleOpen(force?) and close().

Here Edit/Duplicate/Archive is still the menu content style and there is no submission action. When you need to actually edit/delete, refer to [Table and Modal Tutorial](tutorial-dashboard.md). Do not infer that Dropdown will automatically process data according to the button text.

### Tooltip

Use a complete Jinja loop to generate four directions on the same page, without relying on external placement variables:

```jinja
        {% for placement, label, icon in [("top", _("Top"), "ri-arrow-up-line"), ("right", _("Right"), "ri-arrow-right-line"), ("bottom", _("Bottom"), "ri-arrow-down-line"), ("left", _("Left"), "ri-arrow-left-line")] %}
          <span class="om-tooltip" data-om-component="tooltip" data-om-placement="{{ placement }}">
            <button type="button" class="om-button om-button-light om-button-icon" data-om-tooltip-trigger aria-label="{{ _('Show placement help') }}"><i class="{{ icon }}" aria-hidden="true"></i></button>
            <span class="om-tooltip-content" data-om-tooltip-content hidden>{{ _("Placement: %(placement)s", placement=label) }}</span>
          </span>
        {% endfor %}
```

Tooltips are suitable for short descriptions. Trigger buttons retain accessible names that can be viewed on mouse hover or keyboard focus; don't restrict necessary actions to mouse hover.

### Popover and Drawer

The interactive content container on the same page is as follows:

```jinja
      <div class="om-popover" data-om-component="popover" data-om-placement="bottom-start" data-example-popover>
        <button type="button" class="om-button om-button-primary" data-om-popover-trigger aria-expanded="false">
          <i class="ri-team-line" aria-hidden="true"></i>{{ _("Deployment owners") }}
        </button>
        <div class="om-popover-content" data-om-popover-content hidden>
          <div class="flex items-start gap-3">
            <span class="om-avatar om-avatar-md om-avatar-primary">OP</span>
            <div><h3 class="font-semibold text-default-900">{{ _("Operations team") }}</h3><p class="mt-1 text-sm text-default-500">{{ _("Three operators can approve production releases.") }}</p></div>
          </div>
          <div class="mt-4 flex gap-2 border-t border-default-200 pt-3">
            <a class="om-button om-button-soft-primary om-button-sm" href="#popover">{{ _("View team") }}</a>
            <button type="button" class="om-button om-button-light om-button-sm">{{ _("Request review") }}</button>
          </div>
        </div>
      </div>
```

Popover can contain links and buttons, but neither traps focus nor creates a Modal backdrop. This remains a UI demonstration: View team's #popover and Request review have no corresponding business handlers and do not form a review workflow.

Use an [ordinary Modal](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/frontend.md#modal-只是容器) for a backdrop, focus trapping, or remote content container. Drawer on the same page imports modal from `oldman/dashboard/components/modal.html`, passing om-drawer and om-drawer-start/end/top/bottom through root_class. Its trigger's data-om-modal-target matches the macro-generated ID. Copy the trigger, macro import, and macro call together; a direction class alone cannot open the panel. Drawer reuses Modal loading, closing, and cleanup, without a separate submission protocol.

## Tabs

[tabs-disclosure.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/ui/tabs-disclosure.html) for `/examples/ui/tabs-disclosure` contains Tabs, native collapses, and step bars. Below is the complete Tabs area, including the non-selectable Billing tab and each corresponding panel:

```jinja
  <section class="om-card xl:col-span-2" data-om-component="tabs" data-example-ui-tabs>
    <div class="om-card-header">
      <div>
        <h2 class="om-card-title">{{ _("Workspace tabs") }}</h2>
        <p class="mt-1 text-sm text-default-500">{{ _("Use Arrow Left, Arrow Right, Home, and End to move between available tabs.") }}</p>
      </div>
    </div>
    <div class="om-card-body">
      <div class="om-tabs" role="tablist" aria-label="{{ _('Workspace sections') }}">
        <button type="button" class="om-tab" id="workspace-overview-tab" role="tab" data-om-tab aria-controls="workspace-overview-panel" aria-selected="true">{{ _("Overview") }}</button>
        <button type="button" class="om-tab" id="workspace-activity-tab" role="tab" data-om-tab aria-controls="workspace-activity-panel" aria-selected="false">{{ _("Activity") }}</button>
        <button type="button" class="om-tab" id="workspace-billing-tab" role="tab" data-om-tab aria-controls="workspace-billing-panel" aria-selected="false" disabled>{{ _("Billing") }}</button>
        <button type="button" class="om-tab" id="workspace-audit-tab" role="tab" data-om-tab aria-controls="workspace-audit-panel" aria-selected="false">{{ _("Audit log") }}</button>
      </div>

      <section class="om-tab-panel" id="workspace-overview-panel" role="tabpanel" aria-labelledby="workspace-overview-tab">
        <div class="grid gap-4 sm:grid-cols-3">
          <div><p class="text-sm text-default-500">{{ _("Active services") }}</p><strong class="mt-1 block text-2xl text-default-900">18</strong></div>
          <div><p class="text-sm text-default-500">{{ _("Requests today") }}</p><strong class="mt-1 block text-2xl text-default-900">84.2k</strong></div>
          <div><p class="text-sm text-default-500">{{ _("Error rate") }}</p><strong class="mt-1 block text-2xl text-emerald-600">0.08%</strong></div>
        </div>
      </section>
      <section class="om-tab-panel" id="workspace-activity-panel" role="tabpanel" aria-labelledby="workspace-activity-tab" hidden>
        <ul class="om-list">
          <li class="om-list-item"><div class="om-list-row"><span class="om-list-marker"></span><div class="om-list-content"><p class="om-list-title">{{ _("Configuration published") }}</p><p class="om-list-meta">{{ _("The production routing rules were updated five minutes ago.") }}</p></div></div></li>
          <li class="om-list-item"><div class="om-list-row"><span class="om-list-marker"></span><div class="om-list-content"><p class="om-list-title">{{ _("Health check recovered") }}</p><p class="om-list-meta">{{ _("All edge nodes are responding normally.") }}</p></div></div></li>
        </ul>
      </section>
      <section class="om-tab-panel" id="workspace-billing-panel" role="tabpanel" aria-labelledby="workspace-billing-tab" hidden>{{ _("Billing is unavailable in this environment.") }}</section>
      <section class="om-tab-panel" id="workspace-audit-panel" role="tabpanel" aria-labelledby="workspace-audit-tab" hidden>
        <p class="text-sm text-default-600">{{ _("Audit records remain available for ninety days and can be exported by authorized operators.") }}</p>
      </section>
    </div>
  </section>
```

IDs must be unique across the page. When copying instances, update id, aria-controls, and aria-labelledby together. Keep each tabpanel inside its own tabs root. The component synchronizes aria-selected, tabIndex, and hidden, supports Left/Right arrows and Home/End, and skips disabled tabs. It only switches existing content, without querying the database automatically; metrics and audit descriptions here are static.

Accordion/Collapse on the same page uses the browser's native details/summary and does not require a fictional accordion loader. For example, a complete separate fold area:

```jinja
      <details class="om-disclosure om-collapse" data-example-ui-collapse>
        <summary class="om-disclosure-summary">{{ _("Show advanced connection details") }}</summary>
        <div class="om-disclosure-content grid gap-3 sm:grid-cols-2">
          <div><p class="text-xs font-medium uppercase tracking-wide text-default-400">{{ _("Region") }}</p><p class="mt-1 text-default-800">us-west-2</p></div>
          <div><p class="text-xs font-medium uppercase tracking-wide text-default-400">{{ _("Protocol") }}</p><p class="mt-1 text-default-800">HTTPS / HTTP/2</p></div>
        </div>
      </details>
```

Multiple details of Accordion share a name, and the folding appearance comes from shared CSS such as om-disclosure. The step bar is just a status style; for actual step-by-step filling, field verification and final saving, see `/examples/forms/multi-step`.

## Form enhancement

Prioritize the [Backend Fields and Widget](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/forms.md) to output the DOM, instead of hand-crafting a second set of submission protocols on each page. The field class of Demo is in [forms.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/forms.py), and the general submission is in [views/forms.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/forms.py); for the specific source code and library boundaries, see [Form Example Index](demo-examples.md#forms-and-input).

| Need | Backend/frontend capability | Actual page |
| --- | --- | --- |
| Normal input, synchronous/asynchronous validation | WTForms field + TailwindForm + form / form-validator | /examples/forms/basics, validation |
| Date and time, color, number addition and subtraction, input mask | DateTimePickerWidget, ColorPickerField, InputSpinnerWidget, form-mask | /examples/forms/date-time, color-picker, input-spinner, masks |
| slug and delimiter tag | SlugField / slug-input; TagsField / tags-input; the two cannot be mixed | /examples/forms/slug, tags |
| Fixed option multi-select tags | TagsSelectWidget; still submit the multi-select value list | /examples/forms/tags |
| Search candidates, pictures and text, continue loading | AjaxSelectField / AjaxSelectMultipleField / AjaxAutocompleteWidget, reuse remote provider | /examples/forms/selects, autocomplete |
| Variable number of source URLs | JSONListField + form-repeater; the backend encodes a JSON list in Text | /examples/forms/json-list |
| Rich text, upload | RichTextField / UploadField; backend processing trusted content and file saving | /examples/forms/rich-text, upload |
| Multi-step input | FormLayout + FormStep / multi-step-form; one Form still validates and submits at the end | /examples/forms/multi-step |

Short names following commas on the same line follow the path prefix of that line. The ordinary field page mainly verifies and displays submission feedback, and does not automatically save a database record; slug, input-spinner, and tags also display the cleaned values. Multi-step projects, JSON list, Logo selection and upload each have real saving paths. Validation currently only displays JSON submissions, and HTML/JSON comparison uses dual-mode pages such as basics.

The front end can dynamically create HTML for the business, but it must go through Page's dynamic component lifecycle. The framework will not automatically generate an unknown form from the backend common schema. It is not mandatory to use enhanced plug-ins when the native input/select can meet the needs.

## Slider is a range selection, not Carousel

Open `/examples/forms/sliders`. This page uses a shared Slider to write the utilization value in the form.

The complete field class of [forms.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/forms.py) is as follows. TailwindForm comes from oldman.web.components.forms, IntegerField comes from WTForms, InputRequired/NumberRange comes from wtforms.validators, _ is gettext_lazy:

```python
class SliderExampleForm(TailwindForm):
    """Values synchronized from the existing noUiSlider component."""

    utilization = IntegerField(_("Utilization"), validators=[InputRequired(), NumberRange(min=0, max=100)], default=45)
```

The complete Slider macro corresponding to [forms/page.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/forms/page.html):

```jinja
{% macro slider_control(form_class) %}
  <div class="order-first mb-3 w-full">
    <div
      data-om-component="slider"
      data-om-slider-min-input="{{ example_page }}-utilization"
      data-om-slider-form-selector=".{{ form_class }}"
      data-om-slider-options='{"start":45,"connect":"lower","range":{"min":0,"max":100},"step":1,"tooltips":true}'
    ></div>
  </div>
{% endmacro %}
```

It is called within the form_cards loop in the same file as the following code, without missing the form_class and extra_buttons:

```jinja
        {% set form_class = "example-form-" ~ example_page ~ "-" ~ card.mode %}
        {{ card.form.render(
          action=card.action,
          form_mode=card.mode,
          form_class=form_class,
          submit_label=card.submit_label,
          validate=true,
          extra_buttons=slider_control(form_class) if show_slider else ""
        ) }}
```

views/forms.py sets example_page=sliders and show_slider=True for this page, creates a SliderExampleForm with prefix=sliders, and provides a card in JSON mode. Therefore, the field name searched for by the macro is sliders-utilization, and the form selector points to example-form-sliders-json; it is not a random selection of the first input on the page. The commit address is `/examples/forms/sliders/submit/json` and the backend still checks for integers and the 0–100 range. After success, the form message and Feedback are displayed. The database is not written, and the cleaned values are not listed like the slug page. Check the passed values to view the bound input and actual request content.

Dragging updates the bound input. This example adds no listener to move the slider when input is edited manually. For complete business filtering, see the confidence_min/max dual slider in [catalog_channels/index.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/catalog_channels/index.html). It also uses slider and updates the table through table-filter-form; preserve the filter form and backend fields when copying.

Slider is based on noUiSlider, exposing get, set, instance; the event is om:slider:update/change/slide/set. data-om-slider-min-input/max-input is used to bind input, and data-om-slider-form-selector specifies the form to which it belongs. Set data-om-slider-submit-on-change="true" only if automatic submission is explicitly required; the example page does not enable it. Formatting is available with data-om-slider-format-decimals, but backend numeric validation is always retained.

### Carousel and Gallery

Use carousel to view images or cards horizontally. The following is the complete carousel area in [carousel.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/ui/carousel.html) of `/examples/ui/carousel`, including configuration, buttons, static data, looping and paging. There is no need to write another page.ts:

```jinja
  <section
    class="om-card overflow-hidden"
    data-om-component="carousel"
    data-om-carousel-options='{"slidesPerView":1.1,"spaceBetween":16,"grabCursor":true,"breakpoints":{"640":{"slidesPerView":2},"1024":{"slidesPerView":3}}}'
    data-example-carousel
  >
    <div class="om-card-header">
      <div>
        <h2 class="om-card-title mb-1">{{ _("Responsive content carousel") }}</h2>
        <p class="text-sm text-default-500">{{ _("Drag, swipe, use the arrow keys, or choose the previous and next buttons. The number of visible cards follows the viewport width.") }}</p>
      </div>
      <div class="flex items-center gap-2">
        <button type="button" class="om-button om-button-light om-button-sm" data-om-carousel-prev aria-label="{{ _('Previous items') }}">
          <i class="ri-arrow-left-line" aria-hidden="true"></i>
        </button>
        <button type="button" class="om-button om-button-light om-button-sm" data-om-carousel-next aria-label="{{ _('Next items') }}">
          <i class="ri-arrow-right-line" aria-hidden="true"></i>
        </button>
      </div>
    </div>

    <div class="om-card-body">
      <div class="swiper" data-om-carousel-viewport>
        <div class="swiper-wrapper">
          {% set services = [
            ("stream-edge-01", "Los Angeles", "482 Mbps", _("Healthy"), "success", "ri-server-line"),
            ("stream-edge-02", "New York", "391 Mbps", _("Healthy"), "success", "ri-cloud-line"),
            ("stream-edge-03", "Frankfurt", "274 Mbps", _("Degraded"), "warning", "ri-pulse-line"),
            ("stream-edge-04", "Singapore", "356 Mbps", _("Healthy"), "success", "ri-global-line"),
            ("stream-edge-05", "Tokyo", "188 Mbps", _("Maintenance"), "info", "ri-tools-line")
          ] %}
          {% for name, region, throughput, status, tone, icon in services %}
          <article class="swiper-slide h-auto">
            <div class="h-full rounded border border-default-200 bg-default-50 p-5">
              <div class="mb-5 flex items-start justify-between gap-3">
                <span class="grid size-10 place-items-center rounded bg-primary-50 text-lg text-primary"><i class="{{ icon }}" aria-hidden="true"></i></span>
                <span class="om-badge om-badge-{{ tone }}">{{ status }}</span>
              </div>
              <h3 class="font-semibold text-default-900">{{ name }}</h3>
              <p class="mt-1 text-sm text-default-500">{{ region }}</p>
              <div class="mt-5 border-t border-default-200 pt-4">
                <span class="text-xs uppercase tracking-wide text-default-500">{{ _("Current throughput") }}</span>
                <strong class="mt-1 block text-xl text-default-900">{{ throughput }}</strong>
              </div>
            </div>
          </article>
          {% endfor %}
        </div>
      </div>

      <div class="mt-5 flex justify-center" data-om-carousel-pagination aria-label="{{ _('Carousel pagination') }}"></div>
    </div>
  </section>
```

services contains five illustrative records inside the template; throughput does not update live. Carousel manages Swiper touch, keyboard, navigation, pagination, and destruction. slideTo(index, speed=0) uses zero-based indexes.

Gallery `/examples/ui/gallery`'s [gallery.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/ui/gallery.html) combination Gallery + ordinary Modal + Carousel: the data-om-gallery-index of the thumbnail corresponds to the slide serial number, the data-om-modal-target opens the same container, and the gallery switches to the target item after the Modal is opened. The combination and the data-om-gallery-carousel tag are retained when copying, you cannot just copy the thumbnail button. The last item intentionally does not have images, and is used to view fallback; it is not another set of Lightbox, nor is it a web image searcher.

## Charts

Open `/examples/charts/trends`, composition, distribution, the data comes from the imported Example database. The complete sources are [chart_views.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/chart_views.py), [views/charts.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/charts.py) and [charts/gallery.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/charts/gallery.html).

Shared ApexChart turns off `dataLabels` by default and does not print values on each data point; explicitly write `{"dataLabels": {"enabled": True}}` in options when necessary, and the treemap example is declared in this way.

The complete shell helper function for views/charts.py is:

```python
async def _chart_shell(request: Request, key: str, html_id: str):
    chart = ExampleChartData(request=request)
    return await chart.render_shell(html_id=html_id, chart_key=key)
```

Request comes from oldman.web.request, and ExampleChartData is imported from chart_views in the same App. This class inherits SQLAlchemyChartView and uses TailwindChartRenderer; the view module registers it to `/examples/charts/data/<chart_key>` through as_view(). Ordinary page routing is checked by staff permissions, and then _chart_cards calls this function for each key to generate unique html_id; the auxiliary function cannot be regarded as an installed HTTP route.

The template outputs each chart in the context containing charts like this. item.chart is the component HTML generated by the above backend renderer:

```jinja
    {% for item in charts %}
      <section class="om-card" data-example-chart-card="{{ item.key }}">
        <div class="om-card-header">
          <div>
            <h2 class="om-card-title mb-1">{{ item.title }}</h2>
            <p class="mb-0 text-sm text-default-500">{{ _("Aggregated from the imported Example database rows.") }}</p>
          </div>
          <span class="om-badge om-badge-primary">{{ item.key }}</span>
        </div>
        <div class="om-card-body">{{ item.chart }}</div>
      </section>
    {% endfor %}
```

The complete read sequence is: page renders a component shell → apex-chart mounts → requests data-om-chart-src → backend checks chart key/permissions/parameters and queries the database → returns chart configuration → frontend renders. Success returns ApexCharts configuration with shared summary/meta, without a DefaultApiResponse wrapper. Failures use the corresponding HTTP error status and error JSON; do not continue rendering them as chart configuration.

The framework also supports inline data-om-chart-config. This is a public capability; the demo above uses a remote data entry point. ApexChart exposes load(url), renderChart(options), updateSeries(series), appendData(data), and updateOptions(options). Updating series need not destroy the whole component; leaving the Page destroys the chart and cancels unfinished requests.

The Normal, Empty, Slow 90 days, Latest 7 days, Error, and Permission denied buttons on `/examples/charts/states` use ExampleChart in [realtime-chart.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/components/examples/realtime-chart.ts) to call the mounted ApexChart.load. It is a private ExamplesPage loader; example-chart is not a framework default component. Errors and 403 are deliberate page test scenarios. Judge results through actual browser operations; template existence does not establish acceptance.

The SSE example is in `/examples/charts/realtime`: read the database sample first, and then receive the push; the publish button will write a sample. It is different from the read-only realtime table playback, see [Realtime wiring (in Chinese)](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/agents/realtime.md) for details, and does not describe the CPU data as having been collected from the real server.

## Feedback and other components

`/examples/messages/feedback` demonstrates lightweight toasts, alerts, message fallback, duplicate-message avoidance, and business errors. These five display buttons use declarative Actions and need no dedicated page.ts. The same page's review confirmation and rename prompt use a private component to handle choices before actual writes. Both reuse Page Feedback without another global instance.

The first button in [feedback.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/messages/feedback.html) looks as follows:

```jinja
      <button type="button" class="om-button om-button-primary" data-example-feedback="default" data-om-action="get" data-om-url="/examples/messages/feedback/default">{{ _("Show lightweight toast") }}</button>
```

Corresponding to the complete entry of [views/messages.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/messages.py):

```python
@router.get("/examples/messages/feedback/default", name="example_feedback_default")
@login_required()
async def example_feedback_default(request: Request):
    """Resolve one Feedback Action through the Page's default Feedback."""
    del request
    return api_response(
        DefaultApiResponse(
            actions=[FeedbackAction(title=_("Default Feedback Action completed."), icon="success")]
        )
    )
```

`router` comes from oldman.web, Request comes from oldman.web.request, login_required comes from oldman.web.auth; api_response comes from oldman.web.response, DefaultApiResponse/FeedbackAction comes from oldman.web.api, _ is gettext_lazy. The button requests the interface through the public data-om-action, and the response action is executed by the Runner of the current Page; when the target is not filled in, the existing Dashboard Page Feedback is used.

Another button request on the same page is `/examples/messages/feedback/target`. The backend action explicitly specifies target="#example-target-feedback", mode=FeedbackMode.ALERT, and the template also declares the target component:

```jinja
      <div id="example-target-feedback" data-om-component="feedback"></div>
```

Copy actions together with target DOM. A selector does not automatically create an instance. Other buttons return message-only, message + feedback action, and nonzero error_code, matching three actual endpoints in the same file. See the [Response reference](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/responses.md) for message fallback and action order.

toast uses Toastify, multiple messages can appear at the same time; alert/confirm/prompt uses SweetAlert2. Simply displaying the toast does not generate notification center records. When the confirmation result determines whether the business continues, the Page should call confirm or process a private action. A feedback action that does not need to return the selection result cannot be regarded as a confirmation protocol.

### Confirmation and input: modify real projects

First follow [Complete Demo Preparation Steps](demo-examples.md) to migrate, load fixtures, start the Web and sign in. Open "Confirm changes to a real project" in `/examples/messages/feedback`:

1. Select an item and click "Move to review". Canceling the dialog box does not send a POST; only confirming will save the status of this project as `review`. The saved ID, name, status, and success prompt are displayed below.
2. Submit the same project that is already under review again, and the server returns a business error; there are no new modifications and no successful actions. Buttons and loading masks are restored, and you can continue working.
3. Click “Rename project”. The prompt starts with the selected name. Whitespace-only input or a trimmed length over 150 characters displays an input error. Cancel sends no request; confirmation triggers server validation again and saves the trimmed name, **without changing slug**. The result also updates selection text, so reopening the prompt shows the new name.
4. Open the Demo path `/examples/tables/json`, and you can see the modifications to the same database record; this is actual operation, not a static demonstration of just "save successfully". The test will change the demo data. Do not try it on a real business database.

The page code is in [feedback-workflow.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/components/examples/feedback-workflow.ts), which is loaded on demand by the `feedback-workflow` loader of [ExamplesPage](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/pages/examples.ts). Corresponding to the native parameter form statement `data-om-component="feedback-workflow"`, it is not an ordinary Form component; the button `type="button"`, the native submit is blocked to avoid bypassing confirmation. The full template and server POST are in the source link earlier in this section.

After confirmation, the component is submitted through the existing `runAction(form, {params, signal})`, using the existing local Preloader, reusing CSRF, shared HTTP errors and ordered response actions. The result HTML and Feedback are returned only after the database transaction exits successfully. Project names are escaped properly in result templates and user input is not treated as HTML.

Disconnection, timeout, or HTTP 403 uses existing visible errors, without pretending a successful save. Buttons and overlays recover afterward. Use browser developer tools to go offline, confirm to observe the error, then restore the network and retry. Leaving the page cancels old requests and remaining UI actions, preventing old messages from entering a new page. **This does not guarantee undoing changes already committed by the server**; the database is authoritative on return.

`Feedback.confirm(options)` returns `Promise<boolean>`; explicitly pass `showCancelButton: true` for a cancel button. `prompt<string>(options)` returns results including `isConfirmed` and `value`; do not submit cancellation as an empty string. Page.feedback's public type guarantees only response presentation. The demo narrows it with `instanceof Feedback`. See the [Frontend reference](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/frontend.md#feedback-交互与真实请求) for extension wiring and complete execution order.

Other capabilities can be viewed further from these real pages:

| name or combination | Demo entry and necessary boundaries |
| --- | --- |
| avatar | /examples/ui/badges-avatars: pictures and failure placeholders; static letter avatars only require HTML/CSS |
| countdown | /examples/ui/countdown: The server generates the ISO time of countdown_target, and the browser updates the visible value; reopening the page will regenerate the target, not the background task timer |
| Native video and media aspect ratios | /examples/ui/video: browser controls with shared om-media, using demo static WebM without a separate video loader |
| scroll-area | /examples/ui/lists and /examples/plugins: actual SimpleBar containers; ordinary scrolling does not need a wrapper around every block |
| sortable-list | /examples/sortable/workflow: Drag or keyboard button to move the ExampleTask, verify and persist on the server, and restore the UI on failure; different from the static UI list |
| list | /examples/data-inputs/lists: Search/pagination of loaded DOM; big data query uses server-side Table |
| table-filter-form | /examples/tables/html, json: connect filtering Form to existing Table |
| sidebar-menu | Dashboard shell menu expansion, selection and navigation |
| language-switcher | Shell language menu and /examples/i18n/browser, use the existing language translation catalog, do not automatically generate translation |
| back-to-top, history-back, preloader | Return to top, history back and loading presentation; enabled by existing page wiring, does not require all pages to add placeholder components |

Corresponding to [UI Template Directory](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/ui) and [Complete Page Index](demo-examples.md), other layouts, pictures, Timeline, system status, etc. are displayed. For the complete library address, adding steps, generation commands and visual variables of the icons, see [Resource Reference](https://github.com/alexliyu7352/oldman/blob/main/docs/public/zh/developers/assets.md#图标). The currently used icons are not regarded as the entire icon library.

## How to check wiring

In the Demo, first open the page directly, then enter it dynamically from the sidebar, and finally leave and return. Operate according to the actual purpose of the component: menu switch/Escape, Tabs keyboard and disabled items, slider submission and out-of-bounds verification, Carousel navigation, chart failure/empty data, whether Feedback is repeated; do not just look at whether there are attributes in the source code.

If you encounter "no effect", check the resource loading, Page entry, loader of the Page, DOM structure, request address and response format in order. The static presentation button originally has no business request; interactive mounting failure and backend data error should also be distinguished. Do not copy the plug-in, add a global listener or modify the shared lifecycle to fill the single page wiring first.

<!-- source: zh/users/components.md @ db5eb607 -->
