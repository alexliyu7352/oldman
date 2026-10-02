# `oldman.web.components.forms`

Generated from the source by `scripts/api_index.py`; do not edit by hand. [All packages](README.md)

后端 Form 组件包入口。

Import with `from oldman.web.components.forms import <name>`.

## `Actions`

class · defined in `oldman.web.components.forms.layouts`

```python
class Actions
```

声明表单底部动作按钮。

Members:

- `submit: str | LazyTranslation = _SAVE_LABEL`
- `cancel_url: str | None = None`
- `cancel_label: str | LazyTranslation = _CANCEL_LABEL`

## `AjaxAutocompleteField`

class · defined in `oldman.web.components.forms.fields`

```python
class AjaxAutocompleteField(RemoteChoiceValidationMixin, StringField)
```

远程 Autocomplete provider 的便捷字段封装：提交的是 ID，输入框显示标签。

Constructor:

```python
AjaxAutocompleteField(*args: Any, provider: str, endpoint: str | None=None, route_name: str | None=None, page_size: int=20, dependent_fields: Sequence[str]=(), label_mode: Literal['text', 'html']='text', route_kwargs: dict[str, object] | None=None, **kwargs: Any) -> None
```

Members:

- `def initial_choice(value: Any, label: Any) -> None` — 编辑页首屏回显：字段值放 ID，输入框里显示给用户看的标签。

## `AjaxAutocompleteWidget`

class · defined in `oldman.web.components.forms.widgets`

```python
class AjaxAutocompleteWidget
```

远程 Autocomplete provider 的 WTForms widget。

Constructor:

```python
AjaxAutocompleteWidget(*, provider: str, endpoint: str | None=None, route_name: str | None=None, page_size: int=20, dependent_fields: Sequence[str]=(), label_mode: Literal['text', 'html']='text', route_kwargs: dict[str, object] | None=None) -> None
```

Members:

- `def bind_attrs(field: Field, form: Any) -> dict[str, Any]` — 生成前端 Autocomplete 组件需要的 data 属性。
- `def resolve_endpoint(form: Any) -> str` — 返回远程 autocomplete provider endpoint。
- `async def render_async(field: Field, form: Any, **kwargs: Any) -> Markup` — 通过模板渲染 autocomplete 控件。

## `AjaxSelectField`

class · defined in `oldman.web.components.forms.fields`

```python
class AjaxSelectField(RemoteChoiceValidationMixin, SelectField)
```

远程 Select provider 的便捷字段封装。

Constructor:

```python
AjaxSelectField(*args: Any, provider: str, endpoint: str | None=None, route_name: str | None=None, page_size: int=20, dependent_fields: Sequence[str]=(), enhance_choices: bool=False, label_mode: Literal['text', 'html']='text', route_kwargs: dict[str, object] | None=None, coerce: Any=int, **kwargs: Any) -> None
```

Members:

- `def process_formdata(valuelist: list[Any]) -> None` — 清空远程 select 是合法提交：空值存成 None，由 validators 决定是否必填。
- `def initial_choice(value: Any, label: Any) -> None` — 编辑页首屏回显当前值。

## `AjaxSelectMultipleField`

class · defined in `oldman.web.components.forms.fields`

```python
class AjaxSelectMultipleField(RemoteChoiceValidationMixin, SelectMultipleField)
```

远程多选 Select provider 的便捷字段封装。

Constructor:

```python
AjaxSelectMultipleField(*args: Any, provider: str, endpoint: str | None=None, route_name: str | None=None, page_size: int=20, dependent_fields: Sequence[str]=(), enhance_choices: bool=False, tags: bool=False, label_mode: Literal['text', 'html']='text', route_kwargs: dict[str, object] | None=None, coerce: Any=int, **kwargs: Any) -> None
```

Members:

- `def process_formdata(valuelist: list[Any]) -> None` — 清空远程多选是合法提交：空值丢掉，结果是空列表。
- `def initial_choices(choices: Sequence[tuple[Any, Any]]) -> None` — 编辑页首屏回显已选的多个值，顺序就是传入顺序。空值会被跳过。

## `AjaxSelectWidget`

class · defined in `oldman.web.components.forms.widgets`

```python
class AjaxSelectWidget(SelectWidget)
```

远程 Select provider 的 WTForms widget。

Constructor:

```python
AjaxSelectWidget(*, provider: str, endpoint: str | None=None, route_name: str | None=None, page_size: int=20, dependent_fields: Sequence[str]=(), enhance_choices: bool=False, tags: bool=False, label_mode: Literal['text', 'html']='text', route_kwargs: dict[str, object] | None=None) -> None
```

Members:

- `def bind_attrs(field: Field, form: Any) -> dict[str, Any]` — 生成前端 Select 组件需要的 data 属性。
- `def resolve_endpoint(form: Any) -> str` — 返回远程 provider endpoint，优先使用显式 URL，其次使用 route name 反解。
- `async def render_async(field: Field, form: Any, **kwargs: Any) -> Markup` — 通过模板渲染远程 select 控件。

## `CheckboxGroupField`

class · defined in `oldman.web.components.forms.fields`

```python
class CheckboxGroupField(SelectMultipleField)
```

Several values from fixed choices, shown as a list of checkboxes instead of a list box.

## `CheckboxWidget`

class · defined in `oldman.web.components.forms.widgets`

```python
class CheckboxWidget(CheckboxInput)
```

Boolean field as a 16px checkbox row: box on the left, label and help text beside it.

## `ColorPickerField`

class · defined in `oldman.web.components.forms.fields`

```python
class ColorPickerField(StringField)
```

保存规范化的六位 RGB 或八位 RGBA HEX 颜色。

Constructor:

```python
ColorPickerField(*args: Any, allow_alpha: bool=True, **kwargs: Any) -> None
```

Members:

- `def process_formdata(valuelist: list[Any]) -> None` — 统一输出小写 HEX，便于模型和前端稳定比较。
- `def pre_validate(form: BaseForm) -> None` — 拒绝浏览器或客户端提交的非 HEX 值。

## `ColorPickerWidget`

class · defined in `oldman.web.components.forms.widgets`

```python
class ColorPickerWidget
```

输出原生颜色输入，并声明可选的 Pickr 渐进增强。

Constructor:

```python
ColorPickerWidget(*, allow_alpha: bool=True) -> None
```

Members:

- `async def render_async(field: Field, form: Any, **kwargs: Any) -> Markup` — 原生 input 负责无脚本提交，挂载后由隐藏字段承载完整 HEXA 值。

## `DateTimePickerWidget`

class · defined in `oldman.web.components.forms.widgets`

```python
class DateTimePickerWidget
```

显式 opt-in 的 Oldman flatpickr 日期时间 widget。

Constructor:

```python
DateTimePickerWidget(*, date_format: str='Y-m-d\\TH:i', enable_time: bool=True, provider: str='flatpickr', input_type: str='text', extra_attrs: dict[str, Any] | None=None) -> None
```

Members:

- `def bind_attrs(field: Field, form: Any) -> dict[str, Any]` — 生成前端 DateTimePicker 组件需要的 data 属性。

## `EmailField`

class · defined in `oldman.web.components.forms.fields`

```python
class EmailField(HTML5EmailField)
```

An `<input type="email">` that stores the address normalized (stripped, lowercased) and checks its shape.

Constructor:

```python
EmailField(*args: Any, **kwargs: Any) -> None
```

Members:

- `def process_formdata(valuelist: list[Any]) -> None`
- `def pre_validate(form: BaseForm) -> None` — Reject a malformed or oversized address; emptiness is left to DataRequired/Optional.

## `FieldGroup`

class · defined in `oldman.web.components.forms.layouts`

```python
class FieldGroup
```

声明一组带标题（和可选说明）的字段；渲染为 fieldset，字段仍在同一张表单里。

Constructor:

```python
FieldGroup(title: str | LazyTranslation, *items: object, description: str | LazyTranslation='') -> None
```

Members:

- `title: str | LazyTranslation`
- `items: tuple[object, ...]`
- `description: str | LazyTranslation = ''`

## `FieldLayout`

class · defined in `oldman.web.components.forms.layouts`

```python
class FieldLayout
```

表单字段布局定义。

Members:

- `name: str`
- `width: str = 'md:col-span-12'`
- `advanced: bool = False`
- `range_end: str | None = None`
- `range_label: str | LazyTranslation | None = None`

## `FieldRenderer`

class · defined in `oldman.web.components.forms.renderers`

```python
class FieldRenderer
```

无主题字段 renderer，负责字段上下文和 widget attrs。

Constructor:

```python
FieldRenderer(form: Any) -> None
```

Members:

- `async def render(field: Any) -> Markup` — 渲染单个字段 HTML。
- `async def render_radio_field(field: RadioField) -> Markup` — 把 RadioField 渲染为可正常布局的原生单选组。
- `async def render_checkbox_group_field(field: CheckboxGroupField) -> Markup` — Render a CheckboxGroupField as native checkboxes; grouped choices get a heading per group.
- `async def render_json_list_field(field: JSONListField) -> Markup` — 渲染标量列表现有行和供前端克隆的空白模板。
- `async def render_password_field(field: PasswordField) -> Markup` — 渲染带共享可见性控件的密码字段。
- `def password_toggle_enabled(field: PasswordField) -> bool` — 返回字段是否启用共享密码可见性控件。
- `def boolean_presentation(field: BooleanField) -> str` — 返回布尔字段的呈现方式：widget 自带的优先，否则用 renderer 默认。
- `async def render_boolean_field(field: BooleanField) -> Markup` — 渲染布尔字段：复选框行、开关行或开关卡片。
- `async def render_widget(field: Field, **extra_attrs: Any) -> Markup` — 渲染字段 widget，远程组件走可替换模板。
- `def template_name(name: str) -> str` — 返回当前字段 renderer 使用的模板路径。
- `async def render_range_field(start: Field, end: Field, *, label: object=None) -> Markup` — 栅格布局里的范围字段：范围标签（默认取起点字段标签）+ 两个控件并排。
- `async def render_filter_search(field: Field) -> Markup` — inline 筛选条的搜索框：无前缀，占满剩余宽度。
- `async def render_filter_control(field: Field) -> Markup` — inline 筛选条的控件：标签是控件左侧的前缀段。
- `async def render_filter_range(start: Field, end: Field, *, label: object=None) -> Markup` — inline 筛选条的范围控件：一个前缀（默认取起点字段标签），起止两个输入。
- `async def render_help(field: Field) -> Markup` — 渲染字段帮助文本。
- `async def render_field_errors(field: Field, *, error_id: str | None=None) -> Markup` — 渲染字段级错误。
- `def widget_attrs(field: Field) -> dict[str, Any]` — 根据字段类型返回控件属性。
- `def widget_base_class(field: Field) -> str` — 返回无主题默认控件 class。
- `def invalid_class() -> str` — 返回字段错误状态 class。

## `FileExtension`

class · defined in `oldman.web.components.forms.fields`

```python
class FileExtension
```

限制上传文件名最后一个扩展名。

Constructor:

```python
FileExtension(extensions: Collection[str], message: str | LazyTranslation | None=None) -> None
```

## `FileSize`

class · defined in `oldman.web.components.forms.fields`

```python
class FileSize
```

限制上传文件的字节数。

Constructor:

```python
FileSize(max_bytes: int, message: str | LazyTranslation | None=None) -> None
```

## `Form`

class · defined in `oldman.web.components.forms.base`

```python
class Form(WTForm)
```

Oldman 后端渲染表单基类。

Constructor:

```python
Form(*args: Any, request: Any=None, data: Mapping[str, Any] | SanicFormData | None=None, files: Mapping[str, Any] | None=None, obj: Any=None, session: Any=None, initial: dict[str, Any] | None=None, prefix: str='', csrf_token: str='', select_secret_key: str='', **kwargs: Any) -> None
```

Members:

- `field_layout: tuple[FieldLayout | str, ...] = ()`
- `layout: FormLayout | None = None`
- `def configure_remote_select_fields() -> None` — 配置远程 Select widget 的字段校验边界。
- `def add_error(field_name: str, message: str | LazyTranslation) -> None` — 向真实字段添加一条错误，拒绝拼错或伪造的字段名。
- `classmethod def from_request(request, *, obj: Any=None, session: Any=None, initial: dict[str, Any] | None=None, prefix: str='', csrf_token: str='', select_secret_key: str='', **kwargs: Any) -> Self` — 从 Sanic 请求创建表单实例。
- `classmethod def from_query(request, *, obj: Any=None, session: Any=None, initial: dict[str, Any] | None=None, prefix: str='', **kwargs: Any) -> Form` — 从 Sanic 查询参数创建 GET 筛选表单实例。
- `async def render(*, action: str='', method: str='post', form_mode: str='html', target: str | None=None, swap: str | None=None, submit_label: str | LazyTranslation=_SAVE_LABEL, cancel_url: str | None=None, cancel_label: str | LazyTranslation=_CANCEL_LABEL, extra_buttons: Markup | str='', form_class: str='', component_name: str | None='form', validate: bool=False, feedback_target: str | None=None) -> Markup` — 渲染完整表单 HTML。
- `def get_renderer() -> FormRenderer` — 返回当前表单的整体渲染器实例。
- `def get_field_renderer() -> FieldRenderer` — 返回当前表单的字段渲染器实例。
- `async def render_field(field: Field | str) -> Markup` — 渲染单个字段的 label、控件和错误。
- `async def render_actions(*, submit_label: str | LazyTranslation=_SAVE_LABEL, cancel_url: str | None=None, cancel_label: str | LazyTranslation=_CANCEL_LABEL, extra_buttons: Markup | str='') -> Markup` — 渲染表单底部操作区，供模板局部调用。
- `def visible_fields() -> list[Field]` — 返回可见字段列表。
- `def hidden_fields() -> list[Field]` — 返回隐藏字段列表。
- `def iter_layout() -> Iterable[FieldLayout]` — 返回表单布局字段。
- `def get_layout_steps() -> tuple[FormStep, ...]` — 返回布局中声明的多步骤字段分组。
- `def iter_step_layout(step: FormStep) -> Iterable[FieldLayout]` — 展开一个步骤中的字段布局。
- `def iter_layout_segments() -> Iterable[tuple[FieldGroup | None, tuple[FieldLayout, ...]]]` — 按分组切分顶层布局：连续的散字段成一段，每个 FieldGroup 自成一段。
- `def iter_step_segments(step: FormStep) -> Iterable[tuple[FieldGroup | None, tuple[FieldLayout, ...]]]` — 按分组切分一个步骤里的布局。
- `def get_layout_actions() -> Actions | None` — 返回布局中声明的 actions 配置。
- `async def is_valid() -> bool` — 执行异步表单校验并返回是否通过。
- `async def validate(extra_validators: dict[str, Any] | None=None) -> bool` — 执行 WTForms 同步校验和 Oldman 异步 clean 生命周期。
- `async def clean() -> dict[str, Any] | None` — 执行跨字段校验，业务子类可覆盖。
- `property data: dict[str, Any]` — 返回原始输入数据，和 cleaned_data 区分。
- `property cleaned_data: dict[str, Any]` — 返回通过验证后的字段数据。
- `def populate_obj(obj: Any) -> None` — 把 cleaned_data 中的字段写回普通对象。
- `property errors: dict[str, list[str | LazyTranslation]]` — 返回每个真实字段的完整错误列表。
- `property error_message: str | LazyTranslation | None` — 返回无法归属到具体字段的顶部校验消息。
- `def to_api_response() -> DefaultApiFormResponse` — 把当前表单状态转换为统一 API 响应对象。
- `async def prepare_async_fields() -> None` — 准备需要异步数据源的字段。

## `FormLayout`

class · defined in `oldman.web.components.forms.layouts`

```python
class FormLayout
```

声明式表单布局。

Constructor:

```python
FormLayout(*items: object) -> None
```

Members:

- `items: tuple[object, ...]`

## `FormRenderer`

class · defined in `oldman.web.components.forms.renderers`

```python
class FormRenderer
```

无主题表单整体 renderer。

Constructor:

```python
FormRenderer(form: Any) -> None
```

Members:

- `async def render(**kwargs: Any) -> Markup` — 渲染完整表单 HTML。
- `async def render_table_filter(**kwargs: Any) -> Markup` — 渲染 TableFilterForm 专用 HTML。
- `async def render_inline_filter(attrs: dict[str, Any], *, submit_label: object, extra_buttons: Markup | str) -> Markup` — 一行式筛选条：搜索框、带前缀标签的控件、范围控件、"更多筛选"面板和右端动作。
- `async def render_with_attrs(attrs: dict[str, Any], *, method: str, submit_label: object, cancel_url: str | None, cancel_label: object, extra_buttons: Markup | str, validator: bool=False) -> Markup` — 使用指定 form 属性渲染完整表单模板。
- `def template_name(name: str) -> str` — 返回当前 renderer 使用的模板路径。
- `async def render_fields() -> Markup` — 按字段布局渲染表单字段。
- `async def render_status() -> Markup` — 渲染前端 Form 组件用于显示提交状态的锚点。
- `async def render_actions(*, submit_label: object, cancel_url: str | None, cancel_label: object, extra_buttons: Markup | str) -> Markup` — 渲染表单底部按钮。
- `async def render_message() -> Markup` — 渲染唯一的表单顶部校验消息区域。

## `FormStep`

class · defined in `oldman.web.components.forms.layouts`

```python
class FormStep
```

声明多步骤表单中的一个字段分组。

Constructor:

```python
FormStep(title: str | LazyTranslation, *items: object, description: str | LazyTranslation='') -> None
```

Members:

- `title: str | LazyTranslation`
- `items: tuple[object, ...]`
- `description: str | LazyTranslation = ''`

## `InputSpinnerWidget`

class · defined in `oldman.web.components.forms.widgets`

```python
class InputSpinnerWidget
```

为 WTForms 数字字段输出可渐进增强的加减控件。

Members:

- `async def render_async(field: Field, form: Any, **kwargs: Any) -> Markup` — 保留原生 number input，并在外层声明 InputSpinner 组件。

## `JSONListField`

class · defined in `oldman.web.components.forms.fields`

```python
class JSONListField(FieldList)
```

把 Text 中的 JSON 数组绑定为 WTForms 标量字段列表。

Constructor:

```python
JSONListField(unbound_field: Any, *args: Any, **kwargs: Any) -> None
```

Members:

- `def process(formdata: Any, data: Any=unset_value, extra_filters: Any=None) -> None` — 解码模型值，并在 WTForms 截断前检查提交索引和数量。
- `def validate(form: BaseForm, extra_validators: Any=()) -> bool` — 保留子字段错误，并把列表级失败交给表单顶部消息。
- `def template_entry(index: str='__index__') -> Any` — 创建不写入 entries 的空白子字段，供 HTML template 克隆。
- `staticmethod def encode(value: list[Any]) -> str` — 返回数据库 Text 使用的稳定紧凑 JSON。

## `ModelChoice`

class · defined in `oldman.web.components.forms.choices`

```python
class ModelChoice
```

本地模型选择器配置。

Members:

- `model: type[Any]`
- `value_field: str = 'id'`
- `label_field: str = 'name'`
- `order_by: Sequence[str] = dataclass_field(default_factory=tuple)`
- `max_choices: int = 200`
- `empty_label: str | None = None`
- `async def get_queryset(request: Any, session: Any) -> Sequence[Any]` — 返回当前 request/session 可见的本地候选对象。
- `def value_from_instance(obj: Any) -> Any` — 从候选对象读取提交值。
- `def label_from_instance(obj: Any) -> str` — 从候选对象读取显示文本。

## `ModelChoiceField`

class · defined in `oldman.web.components.forms.fields`

```python
class ModelChoiceField(SelectField)
```

本地模型外键选择字段。

Constructor:

```python
ModelChoiceField(*args: Any, model_choice: ModelChoice, coerce: Any=int, **kwargs: Any) -> None
```

Members:

- `async def prepare_choices(form: Any) -> None` — 加载本地候选项并写入 WTForms choices。
- `def pre_validate(form: BaseForm) -> None` — 校验提交值必须来自当前可见 choices。

## `ModelForm`

class · defined in `oldman.web.components.forms.models`

```python
class ModelForm(Form)
```

Oldman 无主题模型表单基类。

Constructor:

```python
ModelForm(*args: Any, instance: Any=None, **kwargs: Any) -> None
```

Members:

- `classmethod def from_request(request, *, instance: Any=None, session: Any=None, initial: dict[str, Any] | None=None, prefix: str='', csrf_token: str='', select_secret_key: str='', **kwargs: Any) -> Self` — 从 Sanic 请求创建模型表单实例。
- `classmethod def from_query(request, *, instance: Any=None, session: Any=None, initial: dict[str, Any] | None=None, prefix: str='', **kwargs: Any) -> Self` — 从 Sanic 查询参数创建模型筛选表单实例。
- `classmethod def get_model() -> type[Any]` — 返回 Meta.model 声明的模型类。
- `classmethod def get_model_fields() -> tuple[str, ...]` — 返回 Meta.fields 声明的可编辑字段。
- `classmethod def inject_model_fields() -> None` — 把 SQLAlchemy 模型字段映射为 WTForms 字段。
- `async def validate(extra_validators: dict[str, Any] | None=None) -> bool` — 校验普通字段，并补充非空文件列的“新建必传、编辑可沿用”规则。
- `def populate_obj(obj: Any) -> None` — 把 cleaned_data 中允许的字段写回模型实例。
- `async def save(*, commit: bool=False, session: Any=None) -> Any` — 保存模型表单并返回模型实例，事务提交由外部负责。
- `async def before_save(instance: Any) -> None` — 派生字段的钩子：实例已经装好表单值和上传文件名，还没有写库。

## `RichTextField`

class · defined in `oldman.web.components.forms.fields`

```python
class RichTextField(TextAreaField)
```

使用原生 textarea 提交 HTML，并可在服务端显式清洗。

Constructor:

```python
RichTextField(*args: Any, sanitizer: Callable[[str], str] | None=None, **kwargs: Any) -> None
```

Members:

- `def process_formdata(valuelist: list[Any]) -> None` — 只在配置 sanitizer 时清洗提交值，不猜测业务信任策略。

## `RichTextWidget`

class · defined in `oldman.web.components.forms.widgets`

```python
class RichTextWidget
```

输出可由 Quill 渐进增强的原生 textarea。

Members:

- `async def render_async(field: Field, form: Any, **kwargs: Any) -> Markup` — 保留 textarea 作为真实提交控件，并提供编辑器挂载点。

## `Row`

class · defined in `oldman.web.components.forms.layouts`

```python
class Row
```

声明一行字段及其默认栅格宽度；``as_range=True`` 把恰好两个字段合成一个范围控件。

Constructor:

```python
Row(*fields: str, width: str='md:col-span-12', as_range: bool=False, advanced: bool=False, label: str | LazyTranslation | None=None) -> None
```

Members:

- `fields: tuple[str, ...]`
- `width: str = 'md:col-span-12'`
- `as_range: bool = False`
- `advanced: bool = False`
- `label: str | LazyTranslation | None = None`

## `SanicFormData`

class · defined in `oldman.web.components.forms.base`

```python
class SanicFormData
```

把 Sanic 表单数据适配为 WTForms 需要的 `getlist` 协议。

Constructor:

```python
SanicFormData(data: Mapping[str, Any] | None, files: Mapping[str, Any] | None=None)
```

Members:

- `def getlist(key: str) -> list[Any]` — 返回字段的多值列表。
- `def get(key: str, default: Any=None) -> Any` — 返回字段的第一个值，兼容普通 mapping 和 Sanic 参数对象。
- `def items()` — 返回原始字段项，供调试和测试读取。
- `def to_dict() -> dict[str, Any]` — 把原始输入转换为普通 dict，保留多值字段列表。

## `SlugField`

class · defined in `oldman.web.components.forms.fields`

```python
class SlugField(StringField)
```

把提交值规范为 URL slug，并可从同一表单的其他字段补全空值。

Constructor:

```python
SlugField(*args: Any, source_field: str | None=None, allow_unicode: bool=False, **kwargs: Any) -> None
```

Members:

- `def process_formdata(valuelist: list[Any]) -> None` — 只规范用户提交的值，不改写用于编辑展示的模型初始值。
- `def validate(form: BaseForm, extra_validators: Any=()) -> bool` — 空值可从指定源字段生成；用户已填写时始终保留其语义。

## `SwitchCardWidget`

class · defined in `oldman.web.components.forms.widgets`

```python
class SwitchCardWidget(SwitchWidget)
```

Boolean field as a bordered card: label and help text on the left, switch on the right.

## `SwitchWidget`

class · defined in `oldman.web.components.forms.widgets`

```python
class SwitchWidget(CheckboxInput)
```

Boolean field as an inline 18×32 switch row with the label and help text beside it.

## `TableFilterForm`

class · defined in `oldman.web.components.forms.base`

```python
class TableFilterForm(Form)
```

专门用于驱动 Table API 的筛选表单。

Members:

- `layout_style: str = 'inline'`
- `async def render(*, table_target: str='', action: str='', method: str='get', submit_label: str | LazyTranslation=_FILTER_LABEL, cancel_url: str | None=None, cancel_label: str | LazyTranslation=_CANCEL_LABEL, extra_buttons: Markup | str='', form_class: str='') -> Markup` — 渲染 Table 筛选组件 HTML。

## `TagsField`

class · defined in `oldman.web.components.forms.fields`

```python
class TagsField(StringField)
```

以单个字符串保存可渐进增强的文本标签。

Constructor:

```python
TagsField(*args: Any, delimiter: str=',', **kwargs: Any) -> None
```

Members:

- `def process_data(value: Any) -> None` — 规范模型或默认值，确保首次渲染与提交结果一致。
- `def process_formdata(valuelist: list[Any]) -> None` — 规范浏览器提交值，保留字符串数据合同。

## `TagsInputWidget`

class · defined in `oldman.web.components.forms.widgets`

```python
class TagsInputWidget(TextInput)
```

输出原生文本框，并声明 TagsInput 渐进增强。

Constructor:

```python
TagsInputWidget(*, delimiter: str=',') -> None
```

## `TagsSelectWidget`

class · defined in `oldman.web.components.forms.widgets`

```python
class TagsSelectWidget(SelectWidget)
```

用现有 Select 组件把本地多选项显示为可移除标签。

Constructor:

```python
TagsSelectWidget() -> None
```

## `TailwindFieldRenderer`

class · defined in `oldman.web.components.forms.renderers`

```python
class TailwindFieldRenderer(FieldRenderer)
```

Tailwind/Oldman 字段 renderer。

Members:

- `def widget_base_class(field: Field) -> str` — 返回 Tailwind 控件 class。
- `def invalid_class() -> str` — 返回字段错误 class。

## `TailwindForm`

class · defined in `oldman.web.components.forms.tailwind`

```python
class TailwindForm(Form)
```

业务默认 Tailwind 普通表单基类。

## `TailwindFormRenderer`

class · defined in `oldman.web.components.forms.renderers`

```python
class TailwindFormRenderer(FormRenderer)
```

Tailwind/Oldman 表单整体 renderer。

## `TailwindModelForm`

class · defined in `oldman.web.components.forms.tailwind`

```python
class TailwindModelForm(ModelForm)
```

业务默认 Tailwind 模型表单基类。

## `TailwindTableFilterForm`

class · defined in `oldman.web.components.forms.tailwind`

```python
class TailwindTableFilterForm(TableFilterForm)
```

业务默认 Tailwind 表格筛选表单基类。

## `UploadField`

class · defined in `oldman.web.components.forms.fields`

```python
class UploadField(FileField)
```

绑定 Sanic 单个上传文件的 WTForms 字段。

Members:

- `def process_data(value: Any) -> None` — 编辑模型时不把数据库中的逻辑文件名当作本次上传。

## Module `oldman.web.components.forms.models`

ModelForm 基类。

Import with `from oldman.web.components.forms.models import <name>`.

### `humanize_model_field_name`

function · defined in `oldman.web.components.forms.models`

```python
def humanize_model_field_name(name: str) -> str
```

把模型字段名转换为默认表单标签。

### `model_field_for_column`

function · defined in `oldman.web.components.forms.models`

```python
def model_field_for_column(column: Any, *, mapper: Any=None, label: str | None=None, description: str | None=None, model_choice: ModelChoice | None=None) -> Any
```

把 SQLAlchemy Column 转换为 WTForms 字段定义。

## Module `oldman.web.components.forms.renderers`

Form renderer 协议和模板化主题输出。

Import with `from oldman.web.components.forms.renderers import <name>`.

### `layout_width_classes`

function · defined in `oldman.web.components.forms.renderers`

```python
def layout_width_classes(width: str) -> str
```

返回声明式 Tailwind grid column span。
