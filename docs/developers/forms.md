# 表单、字段与远程选项

后端负责字段、校验和 HTML；浏览器负责提交与增强，不根据后端字段 schema 自动创建整张表单。普通页面与 Modal 内使用同一个 Form。完整 CRUD 接线见[Demo 的项目表格与 Modal](../users/tutorial-dashboard.md)。

本章业务代码摘自 EPG Demo 的 [apps/examples/forms.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/forms.py)，不另建示例 App。按[入门步骤](../users/getting-started.md)加载 fixture 并登录后，可在以下页面对照：

| 页面 | 对应类与实际效果 |
| --- | --- |
| `/examples/forms/basics` | BasicFieldsForm；同一声明演示 HTML/JSON 响应，只校验，不写库 |
| `/examples/forms/validation` | ValidationExampleForm；字段与跨字段错误，当前只有 JSON 表单 |
| `/examples/tables/html`、`/examples/tables/json` | Modal 中的 ExampleProjectForm；增改真实项目记录 |
| `/examples/forms/multi-step` | MultiStepProjectForm；一个多步骤 Form，最终创建一个项目 |
| `/examples/forms/json-list` | StreamProfileForm；不定数量 URL 与 Text 列之间的编码、解码及保存 |
| `/examples/forms/selects`、`/examples/forms/autocomplete` | LogoSelectForm、LogoAutocompleteForm；远程图文候选，保存所选 Logo 外键 |

类内字段、Meta 和方法节选不能单独执行；文件中的导入、模型、常量和配套路由仍需要保留。其他字段页面见[完整 Demo 索引](../users/demo-examples.md)。

## 选择基类

公开基类均在 `oldman.web.components.forms`：`OldmanForm` / `OldmanModelForm` 是无主题表单，`TailwindForm` / `TailwindModelForm` 是 Dashboard 使用的表单；`TableFilterForm` / `TailwindTableFilterForm` 用于 Table 筛选。Demo 的 BasicFieldsForm、ExampleProjectForm、ExampleProjectFilterForm 分别展示后三种实际用法。

普通字段和同步 validator 直接来自 WTForms。Oldman 提供请求绑定、异步清洗、数据库选择、ModelForm、布局和渲染；不要求用户继承一套重复的字段代理。Tailwind 子类使用共享 `om-*` 样式，适合 Dashboard/Admin；无主题基类用于自己提供 renderer 的应用。

一个表单实例属于一次请求，不能做进程级单例。

## 绑定与清洗

常用构造参数为 `request`、`data`、`files`、`obj`、`session`、`initial`、`prefix`、`csrf_token`、`select_secret_key`。`data` 是提交数据，`initial` 是初值；`data=` 与 WTForms `formdata=` 不能同时传。ModelForm 使用 `instance=`，不使用 `obj=`。

- `Form.from_request(request, ...)`：POST/PUT/PATCH 绑定 `request.form` 和 `request.files`；GET 为未绑定。
- `Form.from_query(request, ...)`：绑定查询参数，即使参数为空也是已绑定，适合筛选。
- `await form.validate()` / `await form.is_valid()`：执行同一校验生命周期。
- 未绑定校验返回 False，不生成错误，也不运行异步 choices 查询。
- `form.data` 是保存的输入映射；有效值读 `form.cleaned_data`，不要把全部用户输入直接写到模型。

例如 ExampleProjectForm 的以下两个完整方法分别处理唯一 slug 与日期范围。它们仍位于原类内部；`select` 来自 SQLAlchemy，`ValidationError` 来自 WTForms，`_` 是 `oldman.i18n.gettext_lazy`，ExampleProject 是 Demo 模型：

```python
    async def clean_slug(self) -> str:
        """Reject duplicate stable slugs before the database constraint fires."""
        slug = str(self.slug.data or "").strip()
        if self.session is None:
            raise RuntimeError("ExampleProjectForm validation requires a database session")
        result = await self.session.execute(select(ExampleProject).where(ExampleProject.slug == slug))
        existing = result.scalar_one_or_none()
        if existing is not None and int(existing.id) != int(getattr(self.instance, "id", 0) or 0):
            raise ValidationError(_("A project with this slug already exists."))
        return slug

    async def clean(self) -> dict[str, object] | None:
        """Validate the optional project date range."""
        start_date = self.cleaned_data.get("start_date")
        end_date = self.cleaned_data.get("end_date")
        if start_date is not None and end_date is not None and end_date < start_date:
            raise ValidationError(_("End date must not be earlier than start date."))
        return None
```

这里的查询用于友好提示，不替代模型上的唯一约束。并发提交仍可能在数据库写入时失败；不能把数据库异常一律变成“字段无效”。

顺序是准备异步字段 → WTForms 同步校验 → 无字段错误的 `clean_<name>()` → 整个 `clean()`。字段 cleaner 必须是异步方法，返回最终值；返回 None 就是最终值为 None。仅校验时也应返回原值，框架无法判断你是不是忘了 return。

即使部分字段失败，表单 `clean()` 仍会执行。它看到的 `cleaned_data` 只包含已通过字段校验的值；返回 None 保留原数据，返回 dict 替换它。`cleaned_data` 属性返回副本，不能通过原地改这个副本指望修改内部状态。

`ValidationError` 是正常校验失败：字段 cleaner 的异常写字段错误，表单 `clean()` 的异常写唯一 `error_message`。也可用 `add_error(field_name, message)` 添加真实字段错误，最终该字段从 cleaned_data 排除；Demo 的 StreamProfileForm.clean_name 使用这一方式。无效字段名和 `__all__` 会报错；TypeError、数据库异常等程序错误继续抛出，不掩盖为校验错误。

Python `form.errors` 保留完整错误列表；HTML 和 `to_api_response()` 每个字段只显示/输出第一条。跨字段错误优先挂到对应字段，无法归属时使用 `clean()` 的 ValidationError。没有独立 non-field errors 列表。

## 渲染与响应

`await form.render(...)` 返回完整 `<form>` 的 Markup，主要参数：

| 参数 | 默认及用途 |
| --- | --- |
| `action`, `method` | `""`, `"post"`；为空 action 使用当前地址 |
| `form_mode` | `"html"`；也可 `"json"`，指响应格式 |
| `target`, `swap` | 默认不指定；HTML 替换位置与 inner/outer |
| `submit_label`, `cancel_url`, `cancel_label` | 提交及取消按钮 |
| `component_name` | `"form"`；None 不声明前端 Form，适合原生浏览器提交 |
| `validate` | False；True 启用前端校验增强，后端仍必须校验 |
| `feedback_target`, `form_class`, `extra_buttons` | 明确反馈目标、容器类和附加按钮 HTML |

`render_field(field_or_name)` 渲染字段的 label、控件、帮助和错误；`render_actions()` 渲染操作区。自定义整张表单模板时保留字段真实 name、错误定位、顶部 message 和 CSRF 字段。多实例表单用不同 prefix，避免 id/name 冲突。

生成的 `<form>` 带 `novalidate`，前端组件按 `validate=True` 用浏览器约束 API 展示字段错误。字段插件和客户端验证不是保存安全边界；绕过浏览器发送无效输入仍必须失败。

Demo 的 [views/forms.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/forms.py) 在 `_form_card()` 中传递 mode，[page.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/forms/page.html) 调用 `form.render()`，POST 再使用相同 prefix 绑定。两张表单的 `html` / `json` prefix 不能在提交时丢掉，否则字段名对不上。

该文件的错误响应函数原样如下。这里由 Form 发出的 Accept 决定实际响应；`mode` 用于重新渲染出的 Form 配置，不能只看 URL 就假定后端已经返回某种格式：

```python
async def _form_error_response(request: Request, form: Any, *, action: str, mode: str):
    """Return the response contract selected by the mounted Form component."""
    if _accepts_json(request):
        return json_response(form.to_api_response().to_dict(), status=200)
    html = await form.render(action=action, form_mode=mode, submit_label=_("Submit example"))
    return html_response(str(html), status=422)
```

`_accepts_json()` 定义在同一文件；Request、Any、响应函数和翻译函数也在该文件导入。HTML 成功路径由 `_form_success_response()` 返回成功片段；JSON 成功路径返回 DefaultApiFormResponse 和 actions。普通字段示例不保存记录；`multi-step` 分支才在事务内调用 ModelForm.save。两条路径及前端事件顺序见[响应协议](responses.md)。

## ModelForm 的保存边界

ExampleProjectForm 继承 TailwindModelForm，类内 Meta 节选如下；上文的两个 cleaner 也属于这个类：

```python
    class Meta(TailwindModelForm.Meta):
        """Bind only fields exercised by the Table CRUD example."""

        model = ExampleProject
        fields = (
            "team_id",
            "name",
            "slug",
            "description",
            "status",
            "priority",
            "budget",
            "progress",
            "start_date",
            "end_date",
            "is_active",
        )
```

`Meta.fields` 必须显式列举，不支持 `"__all__"`。可在 Meta 中提供 `labels`、`help_texts`、`model_choices`。显式字段优先，不增加复杂类型的全局猜测器。

自动映射包括字符串/Text、整数、布尔、日期/日期时间、普通外键和带文件元数据的列。其他类型需要显式字段，例如 DecimalField；不是偷偷把所有未知类型当字符串。字符串列的长度会进入 maxlength，但业务需要的服务端 Length 等约束仍应显式声明。

实际创建入口在 [views/tables.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/tables.py)。该模块的 `app = get_app()` 来自 `oldman.web.routing`，db_manager 来自 `oldman.db`，权限装饰器来自 Demo `apps.auth.decorators`，CSRF 装饰器来自框架：

```python
@app.post("/examples/tables/projects/create", name="example_project_create")
@csrf_protect()
@admin_required()
async def example_project_create(request: Request):
    """Create one Project and reload the mounted HTML or JSON Table."""
    async with db_manager.get_session() as session:
        form = ExampleProjectForm.from_request(request, session=session)
        if not await form.validate():
            return json_response(form.to_api_response().to_dict())
        await form.save(commit=True, session=session)
    return _project_saved_response(_("Project created."))
```

GET `example_project_create_modal()` 先用 `@add_csrf_token()` 取得 token，在只读 Session 内渲染数据库选项，最后把完整 Form HTML 交给普通 Modal。`_project_saved_response()` 位于同一文件，在事务成功退出后才返回反馈、关闭 Modal、刷新 Table 的动作。成功响应的完整代码见[响应协议](responses.md#后端类型)。

`save()` 默认 commit=False，只准备模型实例；commit=True 使用提供的 Session 做 add/flush，**不自行 commit**。事务由外层管理。没通过校验就 save 会抛 ValueError。Demo 编辑入口先以 `_project_or_404()` 查询项目，再传 `instance=project`。当前 Demo 是 staff 共用数据；需要用户/租户隔离的业务还须在查询中限定范围，不能把 request 中的主键当可信的保存对象。

上传字段是例外：即使 commit=False，save 也可能把新文件写入 Storage。传入框架管理的 Session 才能关联已有文件生命周期处理；不要把 commit=False 理解为绝对没有外部副作用。

file_column、多个文件字段、替换/回滚/删除及 Storage 初始化的完整接线见[文件存储](storage.md#模型声明与-form)。

## 布局与多步骤

Demo `/examples/forms/layouts` 使用完整的 LayoutExampleForm。这里继承的是同文件中的 BasicFieldsForm；Actions、FieldLayout、FormLayout、FormStep、Row 均从 `oldman.web.components.forms` 导入：

```python
class LayoutExampleForm(BasicFieldsForm):
    """The same scalar fields arranged through Oldman's declarative layout."""

    layout = FormLayout(
        Row("name", "email", width="md:col-span-6"),
        Row("age", "budget", "enabled", width="md:col-span-4"),
        FieldLayout("notes"),
        Actions(submit=_("Submit layout")),
    )
```

`FieldLayout(name, width="md:col-span-12")` 控制单字段；Row 给同组字段同宽。MultiStepProjectForm 继承上面的 ExampleProjectForm，使用同文件内的 FormLayout/FormStep 分成 Identity、Planning、Details 三步，最后一个 Actions 提交整张表单。最终仍是一次后端校验和一次保存；不是每步提交数据库。服务端错误返回时仍需保留步骤与字段标记。动态模板必须经过 Page 的组件管理器挂载。

## 扩展字段清单

以下类都从 `oldman.web.components.forms` 导入：

| 字段或 Widget | 保存值与用途 |
| --- | --- |
| `SlugField` | 普通字符串；生成/编辑 URL slug，不是标签列表 |
| `TagsField(delimiter=",")` | 分隔符字符串；前端可增删标签，适合 String/Text |
| `TagsInputWidget` | 为普通文本字段增加 tags-input DOM；需要规范化时使用 TagsField |
| `TagsSelectWidget` | 用现有 Select 增强本地多选；提交选项列表，不变成分隔符字符串 |
| `JSONListField` | Text 中的 JSON 数组 ↔ 一维标量字段列表；新增/删除由 form-repeater 处理 |
| `InputSpinnerWidget` | Integer/Decimal 等字段的加减控件；底层仍是 number input |
| `DateTimePickerWidget` | 配合原有日期/时间字段增加选择器，字段负责实际格式验证 |
| `ColorPickerField` | 十六进制颜色；`allow_alpha` 控制透明度 |
| `RichTextField` | HTML 字符串；渲染编辑器不等于可信 HTML，应在服务端按业务要求清理 |
| `UploadField` | 普通 Form 中是 Sanic 上传文件对象；不是一个本地文件路径 |
| `FileSize(max_bytes)`、`FileExtension(extensions)` | 上传大小与扩展名验证；扩展名不证明真实文件内容安全 |

需要异步 Widget 的字段必须通过 `await form.render()` / `await form.render_field()` 或异步模板渲染，不直接同步调用 `field()`。

Demo 的 StreamProfileForm 字段节选如下。StringField、DataRequired、URL 仍来自 WTForms：

```python
    sources_json = JSONListField(
        StringField(_("Source URL"), validators=[DataRequired(), URL()]),
        min_entries=1,
        max_entries=8,
    )
```

对应模型是 [ExampleStreamProfile](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/models.py)，`sources_json` 是 Text 列，并在 Form.Meta.fields 中明确列出。模板 [json_list.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/forms/json_list.html) 的新建表单用 `prefix="create"` 和 HTML 响应，编辑表单用 `prefix="edit"` 和 JSON 响应。提交名称为 `create-sources_json-0`、`edit-sources_json-0` 等；不能忽略 prefix 或把字段改名为另一套后端协议。

普通 Form 的 cleaned_data 是 list；ModelForm 把对应模型字段编码为 JSON 文本，读取时解码。StreamProfileForm.clean() 还会去除 URL 首尾空白、拒绝重复 URL，并返回替换后的 cleaned_data。创建、编辑路由都在上面的 views/forms.py，均执行真实数据库事务。

只支持一维标量，不接受嵌套 FieldList/FormField。条目错误定位到具体名称，列表数量/JSON 错误写顶部 message；不能把超量输入静默截断当成功。

## 数据库选项和远程选择

少量候选可用 `ModelChoiceField(model_choice=ModelChoice(...))`，传入当前数据库 Session；准备 choices 后做同步选项校验。大量候选用远程 provider，不在页面初次加载时拉整张表。

远程链路是：Form Widget 签名绑定 → 浏览器请求 provider endpoint → 验证绑定和权限 → 搜索或初值回显 → JSON 候选。AjaxSelectField、AjaxSelectMultipleField、AjaxAutocompleteWidget 来自 `oldman.web.components.forms`；ModelSelectProvider、DataSelectProvider、SelectChoice、SelectResult、SelectProviderView、select_registry 来自 `oldman.web.components.selects`。

Demo 的 [providers.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/providers.py) 定义 ExampleLogoProvider、ExampleTagProvider 和 ExampleCountryProvider。`@select_registry.register("example_logos")` 注册类，provider 每次请求创建实例。ModelSelectProvider 提供 `model`、`search_fields`、`label_field`、`value_field` 等配置；业务查询覆盖 `get_queryset(request, context)`。ExampleLogoProvider 的查询只选可用 Logo，并按 name、id 排序；check_auth 要求已登录的 staff。`filter_queryset()` 再按签名允许的 country_code 过滤。ExampleCountryProvider 则继承 DataSelectProvider，用 `get_choices()` 返回有限的国家列表。

字段提供 `provider` 及 `endpoint` 或 `route_name`，可设 `page_size`、`dependent_fields`、`enhance_choices`、`label_mode`。endpoint 使用 `SelectProviderView.as_view(secret_key=key)` 注册，并让 Form 的 `select_secret_key` 使用同一个密钥。密钥应从统一 Web security 根密钥派生，不在字段、views 和 YAML 各放一份新随机值。

### 注册路由与提供密钥

[views/data_inputs.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/data_inputs.py) 在 App 视图加载期间导入 providers，不能只定义类却不让注册代码执行。以下是该模块的导入和初始化节选：

```python
from apps.examples import providers as _providers  # noqa: F401 - import registers providers.
```

```python
SELECT_BINDING_SECRET = configured_web_security_key(WebSecurityPurpose.SELECT_BINDING)

app = get_app()
app.add_route(
    SelectProviderView.as_view(secret_key=SELECT_BINDING_SECRET),
    "/examples/select/<provider_name:str>",
    name="example_select_provider",
)
```

SelectProviderView 默认要求登录和 staff；get_app 来自 `oldman.web.routing`，WebSecurityPurpose 和 configured_web_security_key 来自 `oldman.web.security`。这段初始化发生在服务配置已准备好的视图加载阶段，不在未初始化的裸 Python 进程中执行。

### 声明字段和加载初值

同一个 forms.py 中，LogoSelectForm 的字段节选：

```python
    country_code = SelectField(_("Country"), choices=LOGO_COUNTRY_CHOICES, validators=[Optional()])
    logo_id = AjaxSelectField(
        _("Logo"),
        provider="example_logos",
        route_name="example_select_provider",
        page_size=8,
        dependent_fields=("country_code",),
        enhance_choices=True,
        label_mode="html",
        validators=[DataRequired()],
    )
```

Meta.model 为 ExampleStreamProfile，Meta.fields 仅包含 `logo_id`；country_code 是查询条件，不保存成该模型的字段。字段通过刚注册的 route_name 生成 provider endpoint。

`render_remote_form_page()` 从数据库取得 profile 和当前 logo，再调用以下完整辅助函数（仍在 views/data_inputs.py）：

```python
def _select_form(request: Request, profile: ExampleStreamProfile | None, logo: ExampleLogo | None) -> LogoSelectForm | None:
    """Build the real edit Select form when fixture data exists."""
    if profile is None:
        return None
    return LogoSelectForm(
        request=request,
        instance=profile,
        initial_logo=logo,
        select_secret_key=SELECT_BINDING_SECRET,
    )
```

LogoSelectForm 自己的 `__init__()` 把 initial_logo 的国家、已选 option 和 ID 写入字段，只在未绑定时执行。这样首次 HTML 有已选值，远程初值查询也能继续回显；不能用搜索第一页代替已选值查询。没有 profile 时返回 None，页面提示准备 fixture，不伪造一个已保存对象。

### 提交仍需校验对象

POST `/examples/forms/selects/<profile_id>/edit` 由 `@csrf_protect()` 和 Demo 的 `@admin_required()` 保护，进入 `_update_logo()`：

1. 在框架写 Session 中查询 ExampleStreamProfile，不存在则 404。
2. 调用 LogoSelectForm.from_request，传入 instance、同一个 Session 和 SELECT_BINDING_SECRET。
3. `await form.validate()`；失败返回 HTTP 200 的字段错误，不保存。
4. 校验通过后 `save(commit=True, session=session)`，重新渲染包含已选 Logo 的表单。
5. 事务退出成功后，返回 FeedbackAction 和 ReplaceHtmlAction，替换 `#example-logo-select-form`。

LogoSelectForm 的完整字段校验和查询方法如下，保留了失败路径：

```python
    async def clean_logo_id(self) -> int:
        """Reject forged, unavailable or country-mismatched submitted IDs."""
        logo_id = int(str(self.logo_id.data))
        logo = await self._submitted_logo(logo_id)
        if logo is None or not logo.is_available:
            raise ValidationError(_("Select an available logo."))
        country_code = str(self.country_code.data or "")
        if country_code and logo.country_code != country_code:
            raise ValidationError(_("The selected logo does not belong to this country."))
        return logo_id

    async def _submitted_logo(self, logo_id: int) -> ExampleLogo | None:
        """Read the submitted Logo in the active write transaction."""
        if self.session is None:
            raise RuntimeError("LogoSelectForm validation requires a database session")
        return await self.session.get(ExampleLogo, logo_id)
```

这个 AjaxSelectField 先按默认整数 coerce 转换；转换失败不会继续执行 cleaner。LogoAutocompleteForm 使用 StringField 加 AjaxAutocompleteWidget，所以它自己的 cleaner 还显式捕获整数转换失败。不能复制前者的 cleaner 到任意字符串控件却省掉这一边界。

### 图文、分页和多选

provider 成功 JSON 顶层是 `results` 和 `more`，不是表单 actions；每个候选有 id、text，按需带 html/data。搜索读取 q/page，`more` 控制继续加载；初值通过 value/values 单独查询回显。服务端同时限制 provider、字段绑定、分页上限和允许的依赖字段。

ExampleLogoProvider.get_option() 用 SelectChoice 返回纯文本标签和可信 Markup；图片取自 fixture 的本地 SVG 路径，名称等变量先 escape。字段需 `label_mode="html"`，Select 还需 `enhance_choices=True`。普通 html 字符串会被转义，不是直接执行。Autocomplete 使用对应 AjaxAutocompleteWidget，复用相同 provider 协议。

LogoMultipleSelectForm 在同页演示多个已选值、图文搜索和继续加载，但没有声称把多个 Logo 保存到单个 logo_id 外键；它不是新增的一套多对多持久化 API。

远程选项不在初始 HTML choices 中，因此字段关闭 WTForms 的本地 choices 验证；**保存时仍必须验证提交 ID 存在且当前用户可选**。签名证明的是 Widget 绑定，不替代对象权限；不能因为搜索列表过滤过就信任手工构造的 POST。
