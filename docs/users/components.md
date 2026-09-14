# Dashboard UI 与交互组件

本页帮助选择和接入现有组件。示例直接摘自 EPG Demo，保留实际类名、属性、路由和翻译调用；代码块是对应模板或类中的节选，不是完整的新页面。先按[入门步骤](getting-started.md)准备 Demo，再打开下面的路径。默认地址为 `http://127.0.0.1:17998`。

纯 Card、按钮外观只需要 HTML/CSS；Dropdown 等交互还需要 Page 挂载组件。Admin 与业务 Dashboard 共用组件和视觉变量，但各自启用的 loader 清单由页面入口决定，不是复制 HTML 后所有能力自动启动。完整 Form/Modal/Table 接线见[Demo 教程](tutorial-dashboard.md)，所有页面见[示例索引](demo-examples.md)。

## 示例为什么能直接工作

Demo 的 [views/ui.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/ui.py) 处理 `/examples/ui/<page>`，校验页面名并提供 `page_entry="examples"` 等模板上下文；入口受 Demo 的 staff 权限保护，先登录再操作。

模板和浏览器接线是：

1. UI 模板继承 [pages/examples/base.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/base.html)，把内容放进 example_content。该模板再继承应用 [base.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/base.html)，使用共享 Dashboard 壳、主内容 Frame 和资源标签。
2. [main.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/main.ts) 根据页面入口加载 [ExamplesPage](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/pages/examples.ts)。它继承应用 [BasePage](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/pages/base-page.ts)，后者使用 createDashboardComponentLoaders，已经包含下面这些共享交互组件。
3. ExamplesPage 另外注册 navigation-probe、example-chart、realtime-table、icon-catalog、feedback-workflow 五种 Demo 私有组件。普通 Tabs、Slider、Alert 已在共享 loader 中，不需要再注册成全局组件。
4. 初次访问和 Turbo 动态进入页面都通过 Page 生命周期挂载内容；离开时清理旧实例。远程 Modal 插入内容也走已有动态挂载，不要为它再写一套初始化插件的脚本。

这些步骤的完整代码见[前端入口与生命周期](../developers/frontend.md#demo-的-dashboard-页面入口)，构建和 CSS 接线见[资源参考](../developers/assets.md)。下文 `{{ _("...") }}` 是 Jinja 翻译调用，需要由后端渲染；不能原样保存成浏览器静态 HTML。data-example-* 是 Demo 的定位或私有交互标记，不是框架组件 API；复制私有交互时仍要保留对应属性和消费者。

## 先区分三种能力

| 需要 | 使用方式 |
| --- | --- |
| 按钮、Card、Badge、进度、排版、静态表格 | HTML 和共享 CSS，不强行创建 JS 组件 |
| Tabs、Dropdown、Tooltip、Modal、Slider 等交互 | 声明组件，由 Page 的 loader 挂载 |
| 写数据库、权限校验、持久通知 | 后端能力；组件只能提交和显示，不替代服务器 |

### Card、按钮与状态

打开 `/examples/ui/cards`，下面是 [cards.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/ui/cards.html) 中完整的 Standard card：

```jinja
    <article class="om-card">
      <div class="om-card-header"><h2 class="om-card-title">{{ _("Standard card") }}</h2><span class="om-badge om-badge-primary">{{ _("Live") }}</span></div>
      <div class="om-card-body"><p class="text-sm leading-6 text-content-muted">{{ _("Use a card for one coherent group of information or controls.") }}</p></div>
      <div class="om-card-footer justify-end"><button type="button" class="om-button om-button-light om-button-sm">{{ _("Cancel") }}</button><button type="button" class="om-button om-button-primary om-button-sm">{{ _("Save") }}</button></div>
    </article>
```

这张 Card 的 Save/Cancel 是外观展示按钮，没有保存接口。不要把视觉文字当成已经完成的业务操作；真正写数据库的例子在 Form/Table 教程。完整页面另有 compact、flat、accent、响应式内容卡片。

`/examples/ui/buttons` 的 [buttons.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/ui/buttons.html) 包含实色、柔和、描边、虚线、ghost、文字按钮，以及大小、圆角、图标按钮。下面的状态组是原样节选：

```jinja
      <div class="flex flex-wrap items-center gap-3">
        <button type="button" class="om-button om-button-primary" aria-pressed="true">{{ _("Pressed") }}</button>
        <button type="button" class="om-button om-button-primary" aria-busy="true"><span class="om-button-spinner" aria-hidden="true"></span>{{ _("Saving") }}</button>
        <button type="button" class="om-button om-button-primary" disabled>{{ _("Disabled") }}</button>
        <button type="button" class="om-button om-button-light" disabled><i class="ri-lock-line" aria-hidden="true"></i>{{ _("Unavailable") }}</button>
      </div>
```

aria-busy 和 spinner 在这里是静态演示，不是正在发送请求；真实请求由 Form/Action 的现有加载流程管理。disabled 使用原生按钮属性。用 Tab 检查焦点，纯图标按钮保留 aria-label 或 sr-only 文字。

语义颜色包括 primary、success、info、warning、danger；具体组件支持哪些变体以对应页面及共享样式为准，不随意拼接不存在的 class。不要用整张 Card 的点击代替其中明确的链接。Badge/头像看 `/examples/ui/badges-avatars`，进度和占位看 `/examples/ui/progress-loading`。

## Alert：页面内提示

`/examples/ui/alerts` 的 [alerts.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/ui/alerts.html) 同时展示静态提示和可关闭提示。下面这一项是完整的可关闭 Alert：

```jinja
      <div class="om-alert-warning om-alert-layout" role="alert" data-om-component="alert">
        <i class="om-alert-icon ri-error-warning-line" aria-hidden="true"></i>
        <div class="om-alert-content"><strong class="om-alert-title">{{ _("Review required") }}</strong><span class="om-alert-description">{{ _("Three channel mappings need a manual decision before publishing.") }}</span><a class="mt-2 inline-flex font-medium underline underline-offset-2" href="/match-decisions">{{ _("Open review queue") }}</a></div>
        <button type="button" class="om-alert-dismiss" data-om-alert-dismiss aria-label="{{ _('Dismiss alert') }}"><i class="ri-close-line" aria-hidden="true"></i></button>
      </div>
```

点击关闭只隐藏当前提示并发出 om:alert:dismiss，不写数据库，也不记录用户“已经读过”。这里的审核入口是 Demo 业务页面；复制到自己的业务时应替换链接与说明，不能沿用并不存在的审核地址。

静态 Alert 无须 data-om-component；需要关闭行为才声明 alert。Form 的服务器 message 由 Form 专用区域处理，Cookie 一次性消息和持久通知另有存储流程，都不由 Alert 组件负责。

## Dropdown、Tooltip 与 Popover

三者集中在 `/examples/ui/dropdowns-overlays`，源码为 [dropdowns-overlays.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/ui/dropdowns-overlays.html)。

### Dropdown

该页第一个 Dropdown 原样如下：

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

组件处理菜单开关、外部点击、Escape、滚动/窗口大小变化后的定位；不要另加 document click 监听。右对齐在菜单加 om-dropdown-menu-end；实例公开 toggleOpen(force?)、close()。

此处 Edit/Duplicate/Archive 仍是菜单内容样式，没有提交动作。需要真实编辑/删除时参考[Table 与 Modal 教程](tutorial-dashboard.md)，不要推断 Dropdown 会按按钮文字自动处理数据。

### Tooltip

同页用一个完整 Jinja 循环生成四个方向，不依赖外部 placement 变量：

```jinja
        {% for placement, label, icon in [("top", _("Top"), "ri-arrow-up-line"), ("right", _("Right"), "ri-arrow-right-line"), ("bottom", _("Bottom"), "ri-arrow-down-line"), ("left", _("Left"), "ri-arrow-left-line")] %}
          <span class="om-tooltip" data-om-component="tooltip" data-om-placement="{{ placement }}">
            <button type="button" class="om-button om-button-light om-button-icon" data-om-tooltip-trigger aria-label="{{ _('Show placement help') }}"><i class="{{ icon }}" aria-hidden="true"></i></button>
            <span class="om-tooltip-content" data-om-tooltip-content hidden>{{ _("Placement: %(placement)s", placement=label) }}</span>
          </span>
        {% endfor %}
```

Tooltip 适合短说明。触发按钮保留可访问名称，鼠标悬停或键盘聚焦可以查看；不要把必要操作只能放在鼠标 hover 中。

### Popover 与 Drawer

同页的交互内容容器如下：

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

Popover 可以容纳链接和按钮，但不约束焦点，也不产生 Modal 遮罩。这段内容仍是 UI 展示，View team 的 #popover 和 Request review 没有对应的业务处理，不是一次审核流程。

需要遮罩、焦点约束、远程内容容器时使用[普通 Modal](../developers/frontend.md#modal-只是容器)。同页 Drawer 从 `oldman/dashboard/components/modal.html` 导入 modal 宏，通过 root_class 传入 om-drawer 和 om-drawer-start/end/top/bottom；触发器的 data-om-modal-target 与宏生成的 ID 对应。复制 Drawer 时同时保留触发器、宏导入和宏调用，不是只添加方向 class 就能弹出面板。它复用 Modal 的加载、关闭和清理，没有独立 Drawer 提交协议。

## Tabs

`/examples/ui/tabs-disclosure` 的 [tabs-disclosure.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/ui/tabs-disclosure.html) 包含 Tabs、原生折叠和步骤条。下面是完整 Tabs 区域，包括不可选的 Billing 页签和每一个对应 panel：

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

ID 必须在整页唯一；复制多个实例时，id、aria-controls 和 aria-labelledby 成对修改。tabpanel 保留在自己的 tabs 根内。组件同步 aria-selected、tabIndex、hidden，支持左右方向键及 Home/End，并跳过禁用项。它只切换已有内容，不自动请求数据库；这里的指标和审计说明都是静态示意。

同页的 Accordion/Collapse 使用浏览器原生 details/summary，不需要虚构 accordion loader。例如完整的单独折叠区域：

```jinja
      <details class="om-disclosure om-collapse" data-example-ui-collapse>
        <summary class="om-disclosure-summary">{{ _("Show advanced connection details") }}</summary>
        <div class="om-disclosure-content grid gap-3 sm:grid-cols-2">
          <div><p class="text-xs font-medium uppercase tracking-wide text-default-400">{{ _("Region") }}</p><p class="mt-1 text-default-800">us-west-2</p></div>
          <div><p class="text-xs font-medium uppercase tracking-wide text-default-400">{{ _("Protocol") }}</p><p class="mt-1 text-default-800">HTTPS / HTTP/2</p></div>
        </div>
      </details>
```

Accordion 的多个 details 共用 name，折叠外观来自 om-disclosure 等共享 CSS。步骤条则只是状态样式；真正分步填写、字段校验和最终保存看 `/examples/forms/multi-step`。

## 表单增强

优先由[后端字段及 Widget](../developers/forms.md)输出 DOM，不在每个页面手拼第二套提交协议。Demo 的字段类在 [forms.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/forms.py)，普通提交在 [views/forms.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/forms.py)；具体源码和写库边界见[表单示例索引](demo-examples.md#表单与输入)。

| 使用需求 | 后端/前端能力 | 实际页面 |
| --- | --- | --- |
| 普通输入、同步/异步校验 | WTForms 字段 + TailwindForm + form / form-validator | /examples/forms/basics、validation |
| 日期时间、颜色、数字加减、输入 mask | DateTimePickerWidget、ColorPickerField、InputSpinnerWidget、form-mask | /examples/forms/date-time、color-picker、input-spinner、masks |
| slug 与分隔符标签 | SlugField / slug-input；TagsField / tags-input；二者不能混用 | /examples/forms/slug、tags |
| 固定选项多选标签 | TagsSelectWidget；仍提交多选值列表 | /examples/forms/tags |
| 搜索候选、图片与文字、继续加载 | AjaxSelectField / AjaxSelectMultipleField / AjaxAutocompleteWidget，复用远程 provider | /examples/forms/selects、autocomplete |
| 不定数量源地址 | JSONListField + form-repeater；后端在 Text 中编码 JSON list | /examples/forms/json-list |
| 富文本、上传 | RichTextField / UploadField；后端处理可信内容和文件保存 | /examples/forms/rich-text、upload |
| 分步骤填写 | FormLayout + FormStep / multi-step-form；最终仍由一个 Form 校验提交 | /examples/forms/multi-step |

同一行中逗号后的短名沿用该行的路径前缀。普通字段页主要校验并显示提交反馈，不自动保存一条数据库记录；slug、input-spinner、tags 还展示清洗后的值。多步骤项目、JSON list、Logo 选择和上传各有真实保存路径。validation 当前仅展示 JSON 提交，HTML/JSON 比较使用 basics 等双模式页面。

前端可以为业务动态创建 HTML，但必须经过 Page 的动态组件生命周期。框架不会从后端通用 schema 自动生成一张未知表单。原生 input/select 能满足需求时不强制使用增强插件。

## Slider 是范围选择，不是 Carousel

打开 `/examples/forms/sliders`。这个页面使用共享 Slider 写入表单中的 utilization 数值。

[forms.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/forms.py) 的完整字段类如下。TailwindForm 来自 oldman.web.components.forms，IntegerField 来自 WTForms，InputRequired/NumberRange 来自 wtforms.validators，_ 为 gettext_lazy：

```python
class SliderExampleForm(TailwindForm):
    """Values synchronized from the existing noUiSlider component."""

    utilization = IntegerField(_("Utilization"), validators=[InputRequired(), NumberRange(min=0, max=100)], default=45)
```

对应 [forms/page.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/forms/page.html) 的完整 Slider 宏：

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

它在同文件的 form_cards 循环内按下面的原样代码调用，不要漏掉 form_class 和 extra_buttons：

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

views/forms.py 为该页设置 example_page=sliders、show_slider=True，创建 prefix=sliders 的 SliderExampleForm，提供 JSON 模式的 card。因而宏寻找的字段名是 sliders-utilization，form selector 指向 example-form-sliders-json；不是随便选中页面上第一个 input。提交地址是 `/examples/forms/sliders/submit/json`，后端仍检查整数和 0–100 范围。成功后显示表单 message 和 Feedback，不写数据库，也没有像 slug 页那样列出清洗后的值；核对传值可查看绑定输入和实际请求内容。

拖动会更新绑定输入；这里没有实现“手改输入反向移动滑块”的额外监听。查看完整业务筛选可对照 [catalog_channels/index.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/catalog_channels/index.html) 的 confidence_min/max 双滑块，它同样使用 slider，并通过 table-filter-form 更新表格；不能只复制滑块而漏掉筛选表单和后端字段。

Slider 基于 noUiSlider，公开 get、set、instance；事件为 om:slider:update/change/slide/set。data-om-slider-min-input/max-input 用于绑定输入，data-om-slider-form-selector 指定所属表单。只有明确需要自动提交时才设 data-om-slider-submit-on-change="true"；示例页没有开启它。格式化可用 data-om-slider-format-decimals，但后端数值校验始终保留。

### Carousel 与 Gallery

横向浏览图片或卡片使用 carousel。下面是 `/examples/ui/carousel` 的 [carousel.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/ui/carousel.html) 中完整轮播区域，包含配置、按钮、静态数据、循环与分页，不需要另写 page.ts：

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

services 是模板内的五条示意数据，吞吐量不会实时更新。Carousel 管理 Swiper 的触摸、键盘、导航、分页与销毁，slideTo(index, speed=0) 使用从零开始的索引。

图集 `/examples/ui/gallery` 的 [gallery.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/ui/gallery.html) 组合 Gallery + 普通 Modal + Carousel：缩略图的 data-om-gallery-index 对应幻灯片序号，data-om-modal-target 打开同一个容器，gallery 在 Modal 打开后切到目标项。复制时保留该组合和 data-om-gallery-carousel 标记，不能只复制缩略图按钮。最后一项故意没有图片，用于查看 fallback；它不是另装一套 Lightbox，也不是网络图片搜索器。

## 图表

打开 `/examples/charts/trends`、composition、distribution，数据来自已导入的 Example 数据库。完整来源为 [chart_views.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/chart_views.py)、[views/charts.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/charts.py) 和 [charts/gallery.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/charts/gallery.html)。

views/charts.py 的完整外壳辅助函数是：

```python
async def _chart_shell(request: Request, key: str, html_id: str):
    chart = ExampleChartData(request=request)
    return await chart.render_shell(html_id=html_id, chart_key=key)
```

Request 来自 oldman.web.request，ExampleChartData 从同 App 的 chart_views 导入。该类继承 SQLAlchemyChartView，使用 TailwindChartRenderer；视图模块通过 as_view() 把它注册到 `/examples/charts/data/<chart_key>`。普通页面路由经过 staff 权限检查，再由 _chart_cards 为每个 key 调用此函数，产生互不重复的 html_id；不能把辅助函数当成已安装 HTTP 路由。

模板在包含 charts 的上下文里这样输出每张图，item.chart 是上述后端 renderer 生成的组件 HTML：

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

完整读取顺序是：页面渲染组件外壳 → apex-chart 挂载 → 请求 data-om-chart-src → 后端校验图表 key/权限/参数并查询数据库 → 返回图表配置 → 前端渲染。成功响应是 ApexCharts 配置，并包含共享摘要 summary/meta，不套 DefaultApiResponse；失败响应使用相应 HTTP 错误状态和错误 JSON，不把它当图表配置继续渲染。

框架还支持 data-om-chart-config 的内联配置；这是公开能力说明，上面的 Demo 采用远程数据入口。ApexChart 公开 load(url)、renderChart(options)、updateSeries(series)、appendData(data)、updateOptions(options)。更新序列不用销毁整个组件，离开 Page 则销毁图表并取消它的未完成请求。

`/examples/charts/states` 的 Normal、Empty、Slow 90 days、Latest 7 days、Error、Permission denied 按钮，由 [realtime-chart.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/components/examples/realtime-chart.ts) 的 ExampleChart 调用已挂载 ApexChart.load。它是 ExamplesPage 的私有 loader，不要将 example-chart 误当框架默认组件。错误和 403 是页面主动提供的测试场景；需要在实际浏览器操作后判断效果，模板存在不等于已经验收。

SSE 示例在 `/examples/charts/realtime`：先读取数据库样本，再接收推送；发布按钮会写一条样本。它与只读实时表格回放不同，具体见[实时接线](../agents/realtime.md)，不把示意 CPU 数据描述成已经采集真实服务器。

## Feedback 和其他组件

`/examples/messages/feedback` 展示轻量 toast、alert、message 兜底、避免重复提示和业务错误。这五个展示按钮使用声明式 Actions，不需要专门写 page.ts。同页的确认审核、输入改名则由页面私有组件处理用户选择，再发送真实写请求；两者都复用已有 Page Feedback，不创建第二个全局实例。

[feedback.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/messages/feedback.html) 中第一个按钮原样如下：

```jinja
      <button type="button" class="om-button om-button-primary" data-example-feedback="default" data-om-action="get" data-om-url="/examples/messages/feedback/default">{{ _("Show lightweight toast") }}</button>
```

对应 [views/messages.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/messages.py) 的完整入口：

```python
@app.get("/examples/messages/feedback/default", name="example_feedback_default")
@admin_required()
async def example_feedback_default(request: Request):
    """Resolve one Feedback Action through the Page's default Feedback."""
    del request
    return api_response(
        DefaultApiResponse(
            actions=[FeedbackAction(title=_("Default Feedback Action completed."), icon="success")]
        )
    )
```

app 来自 get_app()，Request 来自 oldman.web.request，admin_required 来自 Demo；api_response 来自 oldman.web.response，DefaultApiResponse/FeedbackAction 来自 oldman.web.api，_ 为 gettext_lazy。按钮经公共 data-om-action 请求接口，响应动作由当前 Page 的 Runner 执行；不填写 target 时使用已有 Dashboard Page Feedback。

同页另一个按钮请求 `/examples/messages/feedback/target`。该后端动作显式指定 target="#example-target-feedback"、mode=FeedbackMode.ALERT，而模板同时声明了目标组件：

```jinja
      <div id="example-target-feedback" data-om-component="feedback"></div>
```

必须把动作与目标 DOM 一起复制，不能把选择器当成自动创建实例的命令。其余按钮分别返回 message-only、message + feedback action、非零 error_code，可直接对照同文件的三个真实接口。message 兜底与动作顺序见[响应参考](../developers/responses.md)。

toast 使用 Toastify，可同时出现多条；alert/confirm/prompt 使用 SweetAlert2。仅展示 toast 不产生通知中心记录。确认结果决定业务是否继续时，应由 Page 调用 confirm 或处理私有 action，不能把一个无需返回选择结果的 feedback 动作当作确认协议。

### 确认和输入：实际修改项目

先按[完整 Demo 的准备步骤](demo-examples.md)迁移、加载 fixture、启动 Web 并用 staff 账户登录。打开 `/examples/messages/feedback` 中的“确认修改真实项目”：

1. 选择一个项目，点击“提交审核”。取消对话框不发送 POST；确认才将这个项目的状态保存为 `review`。下方显示保存后的 ID、名称、状态，并显示成功提示。
2. 再次提交同一个已在审核中的项目，服务器返回业务错误；没有新的修改，也没有成功动作。按钮和加载遮罩会恢复，可以继续操作。
3. 点击“重命名项目”。输入框初始值是当前选择的名称；纯空白或去空白后超过 150 字符会显示输入错误。取消不发送请求，确认后服务端再次校验，并保存去空白后的名称，**不改 slug**。返回值同时更新选择框文字，下一次打开输入框能看到新名称。
4. 打开 Demo 路径 `/examples/tables/json`，可以看到相同数据库记录的修改；这是实际操作，不是只弹“保存成功”的静态演示。测试会改 Demo 数据，别在真实业务数据库上试。

页面代码在 [feedback-workflow.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/components/examples/feedback-workflow.ts)，由 [ExamplesPage](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/pages/examples.ts) 的 `feedback-workflow` loader 按需加载。对应原生参数表单声明 `data-om-component="feedback-workflow"`，不是普通 Form 组件；按钮 `type="button"`，原生 submit 被阻止，避免绕过确认。完整模板和服务器 POST 都在本节前面的源码链接中。

确认后组件通过现有 `runAction(form, {params, signal})` 提交，使用现有局部 Preloader，复用 CSRF、公共 HTTP 错误和有序响应动作。数据库事务成功退出后才返回结果 HTML 与 Feedback。项目名称在结果模板中正常转义，不把用户输入当 HTML。

断网、超时或 HTTP 403 等失败走现有可见错误提示，不伪装成保存成功；结束后恢复按钮和遮罩。可以用浏览器开发工具切换离线，在确认后观察错误，再恢复网络重试。离开页面会取消旧请求及剩余 UI 动作，不让旧提示写进新页面；**这不保证撤销服务器已经提交的修改**，重新进入时以数据库为准。

`Feedback.confirm(options)` 返回 `Promise<boolean>`，要有取消按钮须显式传 `showCancelButton: true`；`prompt<string>(options)` 返回 `isConfirmed`、`value` 等结果，不能把取消当成空字符串提交。Page.feedback 的公共类型只保证响应展示接口，Demo 先用 `instanceof Feedback` 收窄具体对象。扩展接线及完整执行顺序见[前端参考](../developers/frontend.md#feedback-交互与真实请求)。

其他能力可以从这些真实页面继续查看：

| 名称或组合 | Demo 入口与必要边界 |
| --- | --- |
| avatar | /examples/ui/badges-avatars：图片及失败占位；静态字母头像只需 HTML/CSS |
| countdown | /examples/ui/countdown：服务端生成 countdown_target 的 ISO 时间，浏览器更新可见数值；重新打开页面会重新生成目标，不是后台任务计时器 |
| 原生 video 与媒体比例 | /examples/ui/video：浏览器 controls 加共享 om-media，使用 Demo 静态 WebM，不另造 video loader |
| scroll-area | /examples/ui/lists 和 /examples/plugins：实际声明了 SimpleBar 容器；普通滚动不需要逐块包裹 |
| sortable-list | /examples/sortable/workflow：拖动或键盘按钮移动 ExampleTask，服务端验证并持久保存，失败恢复 UI；不同于静态 UI 列表 |
| list | /examples/data-inputs/lists：已加载 DOM 的搜索/分页；大数据查询使用服务端 Table |
| table-filter-form | /examples/tables/html、json：连接筛选 Form 与已有 Table |
| sidebar-menu | Dashboard 壳菜单展开、选中与导航 |
| language-switcher | 壳语言菜单和 /examples/i18n/browser，使用已有语言词典，不自动生成翻译 |
| back-to-top、history-back、preloader | 返回顶部、历史后退与加载呈现；由已有页面接线启用，不要求所有页面添加占位组件 |

对应 [UI 模板目录](https://github.com/alexliyu7352/oldman-epg-dashboard/tree/main/templates/pages/examples/ui) 和[完整页面索引](demo-examples.md)给出其他排版、图片、Timeline、系统状态等展示。图标的完整图库地址、添加步骤、生成命令及视觉变量见[资源参考](../developers/assets.md#图标)，不把当前用到的几个图标当成整个图标库。

## 如何检查接线

在 Demo 中先直接打开页面，再从侧栏动态进入一次，最后离开后返回。按组件实际用途操作：菜单开关/Escape、Tabs 键盘与禁用项、滑块提交与越界校验、Carousel 导航、图表失败/空数据、Feedback 是否重复；不是只看源码里有没有属性。

遇到“没有效果”，依次检查资源加载、Page 入口、该 Page 的 loader、DOM 结构、请求地址和响应格式。静态演示按钮本来没有业务请求；交互挂载失败与后端数据错误也应区分。不要先复制插件、增加全局监听器或修改共享生命周期来补单页接线。
