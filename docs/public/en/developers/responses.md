# Browser responses and ordered actions

This protocol serves browsers with an active Oldman Page. Pure data APIs need not execute UI actions. See [Pages, components, and dynamic content](frontend.md) for page and object origins.

Agents: before writing code, read the [dashboard CRUD guide](../agents/dashboard-crud.md). It says which interface the task needs, how to wire it and what counts as done.

Runnable examples are at `/examples/modals/actions` and `/examples/modals/workflows` in the EPG demo; project saving appears at `/examples/tables/html` and `/examples/tables/json`. Follow [Run the EPG dashboard demo](../users/getting-started.md) to prepare data and sign in first. Do not copy functions below while omitting demo App, Page, component, or permission wiring.

## Backend types

Import public response models, Action subclasses, ApiErrorCode, ApiResponseAction, FeedbackMode, and HtmlSwap from `oldman.web.api`. Response helpers can be imported from `oldman.web` or `oldman.web.response`; demo views use the latter.

`DefaultApiResponse` has `error_code`, `message`, `data`, and `actions`. The default business code is 0, text is empty, and dictionaries/action lists initialize independently. `DefaultApiFormResponse` adds only `errors: dict[str, str | LazyTranslation]`, exposing the first error per actual field without `__all__`.

Actions are flat, strongly typed objects with msgspec tags. Creation/edit/deletion views in the demo's [views/tables.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/tables.py) call `modal_success_response(message, table_target="#example-projects-table")` after successful database-transaction exit. Its expanded payload looks like this (`message` is `str` or `LazyTranslation`):

```python
payload = DefaultApiFormResponse(
    error_code=ApiErrorCode.OK,
    message=message,
    actions=[
        FeedbackAction(title=message, icon="success"),
        CloseModalAction(),
        ReloadTableAction(target="#example-projects-table"),
    ],
)
return json_response(payload.to_dict())
```

LazyTranslation comes from `oldman.i18n`, and json_response from `oldman.web.response`. This is where translation resolves and a response is emitted within the request; lazy objects are not passed directly to arbitrary JSON libraries. `api_response(payload)` wraps the same `payload.to_dict()` plus JSON output. The next section's demo route uses this shorthand.

`oldman.web.api` also supplies Accept-negotiated Form helpers used by both Admin and the demo instead of constructing separate `DefaultApiFormResponse` objects. `accepts_json_form_response(request)` / `accepts_html_form_response(request)` read client requirements. `form_response(message, actions=, errors=, error_code=, status=)` creates the base payload. `form_error_response(message, errors=)` produces an HTTP-200 business error (default `FORM_INVALID`, optionally `INVALID_REQUEST`). `await form_invalid_response(request, form, fragment=, page=)` selects JSON, a 422 fragment, or a whole page. `form_success_response(request, url)` supplies JSON clients with `RedirectAction` and browsers with 303. `feedback_response`, `form_saved_response(message, url=, delay_ms=, actions=)`, and `modal_success_response(message, table_target=, text=, actions=)` represent success staying on the page, redirecting, and closing a modal/reloading a table respectively. Additional actions follow Feedback.

Responses have no singular `action`, top-level `html`, or multi-region `fragments` fields. No actions means `actions=[]`. `ApiResponseAction` manages framework action names; concrete subclasses need no handwritten names. Lazy translation uses existing `TranslatableMsgspecModel` support and resolves during HTTP output, without a custom recursive JSON converter.

## Five built-in actions

| Type | Parameters and behavior |
| --- | --- |
| `FeedbackAction` | Required `title`; `mode` defaults to toast, also supports alert; optional `text`, `icon`, `target`. Title/body are text |
| `ReplaceHtmlAction` | Required `html`; optional `target`, `swap`, supporting only inner/outer |
| `CloseModalAction` | Optional `target`; otherwise finds the nearest Modal containing the request source |
| `ReloadTableAction` | Requires a mounted Table's `target` and awaits reload completion |
| `RedirectAction` | Required `url`; optional nonnegative `delay_ms`, default 0; redirect ends the action loop |

The base shares optional `target` and `data`. Subclasses add their own fields directly without nested ActionData.

The Runner awaits actions in order. An action exception stops later actions without rolling back earlier ones. Toast delivery does not wait for disappearance; an alert waits for dismissal. Ordinary Feedback Actions return no business choice. Confirmation or complex interaction belongs in Page-private actions.

## HTML targets and component lifecycle

Target precedence: `action.target` → initiating element's `data-om-target` → initiating element itself. Swap precedence: `action.swap` → `data-om-swap` → inner.

The demo's [templates/pages/examples/modals/actions.html](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/templates/pages/examples/modals/actions.html) contains this actual button and declares its target in the same template. These are two separate excerpts:

```jinja
      <button type="button" class="om-button om-button-secondary" data-example-action="replace_html" data-om-action="get" data-om-url="/examples/modals/actions/replace-html" data-om-target="#replace-action-result">{{ _("Replace HTML") }}</button>
```

```jinja
      <p id="replace-action-result" class="mb-2 text-default-600">{{ _("Replace HTML target") }}</p>
```

The complete corresponding route in [views/modals.py](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/apps/examples/views/modals.py) follows. `router` comes from `oldman.web`, `login_required` from `oldman.web.auth`; Request, response types, and translation functions are imported as in the original file:

```python
@router.get("/examples/modals/actions/replace-html", name="example_action_replace_html")
@login_required()
async def example_action_replace_html(request: Request):
    """Let the trigger choose where a target-less Replace HTML Action renders."""
    del request
    return api_response(DefaultApiResponse(actions=[ReplaceHtmlAction(html=str(_("HTML replaced by an ordered Action.")))]))
```

Only because the backend omits target does the browser use the button's `data-om-target`. Other pages can choose different targets for the same endpoint, without server-side container-ID guesses. The framework also offers `replace_html_response()`. The following documents its public signature only; the demo route above actually uses complete models, not this helper:

```python
def replace_html_response(
    html: str | Markup, *, target: str | None = None,
    swap: HtmlSwap | None = None, status: int = 200,
) -> Response: ...
```

It generates exactly one replace_html action and requires 2xx. `Markup` comes from `markupsafe`, `Response` from `oldman.web`. Construct complete models for complex responses instead of passing extra feedback or other action parameters to this helper. Actual HTML HTTP responses still use `html_response()`.

CSS selectors search only the current Page root, without touching other cached pages. inner unmounts target contents, writes HTML, then mounts new components. outer also unmounts/replaces the target itself. The next action runs only after replacement. Do not bypass the manager with `innerHTML = ...` for content containing components.

Forms have special handling: when inner replaces the request-source Form itself and the fragment's first element is `<form>`, the framework synchronizes form attributes and replaces its contents rather than nesting another `<form>`. Finding a Form somewhere inside an arbitrary wrapper does not trigger this. For whole-region redraws, explicitly target an outer container or use outer.

## Three request consumers

| Consumer | Accepted business response | HTTP errors |
| --- | --- | --- |
| JSON Form | 2xx `DefaultApiFormResponse`; business failure has nonzero error_code | Non-2xx enters shared HTTP error handling |
| HTML Form | 2xx HTML; validation failure permits 422 HTML | Other non-2xx enters shared HTTP error handling |
| Remote `data-om-action` | 2xx `DefaultApiResponse` | Non-2xx does not execute response actions |

JSON Form describes the **response** format, not a JSON request body. Forms still submit ordinary form data and files.

HTML Form backends still return only HTML. At the receiving boundary, the browser converts it into an internal response: 2xx means business success, 422 means invalid form, and HTML becomes one replace_html action. The same Runner then handles it. This neither removes HTML HTTP interfaces nor requires backend JSON wrapping.

Initial remote Table/Modal loads have their own formats; using JSON does not make them `DefaultApiResponse`. Build Modal payloads through `oldman.web.api` helpers `modal_response(title, html=)`, `modal_response(title, body=, footer=)`, or `modal_not_found_response(title, message)`, rather than separate dicts. See [Static, HTML, and JSON Tables](tables.md) and [Modal](frontend.md#modal-is-only-a-container).

## Form execution order

1. Submit only after browser field validation passes; start loading and prevent duplicate submission of the same form.
2. On a valid response, clear previous messages/field errors before displaying current content.
3. Execute nonempty actions regardless of whether `error_code` is zero.
4. If an action throws, stop and show the exception through Page Feedback without fabricating field errors.
5. Only after actions finish, if the original Form remains mounted, set success/error state and dispatch events.

Business success requires `error_code == 0` and empty `errors`. `om:form:success` / `om:form:error` are lifecycle notifications. They do not themselves close Modals, reload Tables, or redirect. Actions or business listeners perform UI operations explicitly to avoid duplicate execution.

Field errors enter `[data-om-error-for="submitted-field-name"]`; the top message enters `[data-om-form-message]`. `[data-om-form-status]` holds only transient state such as submission progress. Network failure does not generate another business message.

On request failure, Form first stops loading and dispatches one `om:form:error`, then reuses `showResponseActionFailure` from ordinary `data-om-action` to notify through current Page Feedback. As with tables, dropdowns, and charts, `httpErrorMessage` supplies the text. If the server rejects using the framework response shape (numeric `error_code`, nonempty `message`, such as 503 + 1503 for unavailable permission storage), its request-language-translated `message` is shown. Otherwise, 403 shows "Permission denied" and other errors show "Request failed". Sanic's English diagnostic bodies are not shown. Non-request failures, such as action exceptions, also show only "Request failed", without exposing exception text. Shared components own this behavior; demo pages need no extra `onError` popups. HTTP Client retains the original rejection and installs no additional global popup by default, avoiding duplicate HTTP/component notifications. Custom application `onError` handlers should likewise avoid repeat popups for existing UI consumers.

Explicit cancellation and page-navigation aborts do not show this error. HTML 422 and JSON business errors remain form content rather than network failures, without another "Request failed" popup. Request exceptions fabricate neither top messages nor field errors and do not clear user-entered values.

## Ordinary API messages and Feedback

Remote `data-om-action` has no Form top-message area. If actions already include feedback, message is not shown again. Otherwise a nonempty message becomes default Feedback before actions run in order.

For `<form data-om-action="submit">`, the shared capture-phase listener sets `data-turbo="false"` to mark Actions ownership, preventing Turbo Frame from intercepting JSON first. Actual handling remains in the bubbling phase, allowing the form's component to prevent submission first. For example, the demo's FeedbackWorkflow asks for confirmation before explicitly calling `runAction()`. Ordinary Form/Turbo forms without `data-om-action` are unaffected. Dynamically inserted Actions forms likewise require no manual business Turbo configuration.

Feedback resolution checks the action target, source Form's `data-om-feedback-target`, then Page default Feedback. Non-Form sources check this attribute only on their nearest Form; adding it to arbitrary buttons does not work. Explicit targets must identify mounted Feedback within the Page. Invalid targets do not silently fall back elsewhere.

DashboardPage already has a default instance in its shell, serving as current Dashboard Page feedback. Business pages need neither another instance nor a global singleton. The demo's ExamplesPage inherits application BasePage, then DashboardPage, without another notification system. Direct subclasses of low-level Page should provide suitable feedback. Without Feedback, message fallback only logs; an explicit feedback Action fails if it cannot obtain an instance. Logs do not establish that the user saw a notification.

Business error codes do not trigger network retries, and action failures are not retried. Ordinary form POSTs should not automatically retry writes. Shared HTTP handling still owns 401 authentication redirects, 403 permission failures, and 5xx service errors.

## Page departure and private actions

Requests/response handling bind to the originating Page and Turbo Frame. Leaving the page, replacing the source Frame, or destroying the Page cancels further processing so old-response actions do not affect new pages. Browser cancellation does not imply server transaction rollback; UI does not own database rollback.

The Runner uses normal Promise return/throw without a second termination-state protocol. redirect ends the loop. After Form replacement, DOM connection state prevents updates to a departed form.

Project-private actions can define their own tags. Actual declarations in demo views/modals.py follow. LazyTranslation comes from `oldman.i18n`, ResponseAction from `oldman.web.api`:

```python
class _ExampleMarkAction(ResponseAction, tag="example_mark", kw_only=True):
    """Update one Demo-owned output through the Page extension hook."""

    text: str | LazyTranslation
```

The complete publishing route in the same file:

```python
@router.get("/examples/modals/actions/private", name="example_action_private")
@login_required()
async def example_action_private(request: Request):
    """Return one Demo-owned Action handled by ExamplesPage."""
    del request
    return api_response(
        DefaultApiResponse(actions=[_ExampleMarkAction(target="#private-action-result", text=_("Private Page Action completed."))])
    )
```

The complete corresponding browser method in [frontend/src/pages/examples.ts](https://github.com/alexliyu7352/oldman-epg-dashboard/blob/main/frontend/src/pages/examples.ts) follows, still inside ExamplesPage. ResponseAction and ResponseActionContext come from `oldman-web/core`:

```typescript
  override async handleResponseAction(
    action: ResponseAction,
    context: ResponseActionContext
  ): Promise<boolean> {
    if (action.action !== "example_mark") return super.handleResponseAction(action, context);
    if (typeof action.target !== "string" || typeof action.text !== "string") {
      throw new Error("Example mark Action requires a target and text");
    }
    const target = this.root.querySelector<HTMLElement>(action.target);
    if (!target) throw new Error(`Example mark Action target was not found: ${action.target}`);
    target.textContent = action.text;
    return true;
  }
```

Page overrides `async handleResponseAction(action, context): Promise<boolean>`, returning true when handled and delegating unknown actions to `super.handleResponseAction()`. A final false makes the Runner fail and stop. Framework enums manage only built-ins; third-party Apps need not modify them.

This demo view passes `page_entry="examples"`; main.ts loads examples.ts, whose final `setupPage("examples", ExamplesPage)` registers the class. Private handlers receive actions only on the actually mounted Page. A method on a never-loaded class has no effect. See [the frontend runtime](frontend.md#demo-dashboard-page-entry-point) for complete entry-point relationships.

Do not execute arbitrary JavaScript through the protocol, call strings as function names, or write scripts in HTML attributes. Explicit Page methods still implement private actions and validate their required input fields.

## Verifying success and failure in the demo

These existing-page operations let developers recheck changes. This documentation alignment did not rerun browser acceptance tests.

- `/examples/modals/actions`: click feedback, HTML replacement, Reload Table, Redirect, and Private Page Action. Every button targets a real views/modals.py route.
- Missing target and Unknown Action should show action failure rather than waiting forever. Fail in the middle first updates `#action-chain-result`, then fails because the second action's target is absent. The final `later Action must not run` must not appear. Earlier results are not rolled back.
- `/examples/modals/workflows`: the first GET returns Modal title/body/footer rather than actions. The first Form submission returns ReplaceHtmlAction to update the Form; the second succeeds with feedback and closure. Both steps validate ordinary fields without database writes; this is not a cross-request database transaction.
- `/examples/forms/basics`: compare HTML/JSON validation failures: 422 HTML versus 200 plus a business code. Browser constraints may prevent submission first. Inspect Network to distinguish "not requested yet" from "backend validation failed."
- `/examples/tables/json`: creation/editing completes the actual transaction before executing the three actions in this chapter's first function. Distinguish network, database, and action failures. A reload error, for example, does not undo the preceding database transaction.

<!-- source: zh/developers/responses.md @ 84e6ddf1 -->
