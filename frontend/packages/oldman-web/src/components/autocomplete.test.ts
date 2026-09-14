import { describe, expect, it, vi } from "vitest";
import { Autocomplete } from "./autocomplete";

describe("Autocomplete", () => {
  it("搜索本地候选并选择结果", async () => {
    document.body.innerHTML = `
      <section>
        <input data-om-autocomplete-input>
        <div data-om-autocomplete-list hidden></div>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Autocomplete(root);
    const selected = vi.fn();
    root.addEventListener("om:autocomplete:select", selected);
    component.setOptions([
      { value: "alpha", label: "Alpha Stream" },
      { value: "beta", label: "Beta Stream" }
    ]);

    await component.start();
    const input = root.querySelector<HTMLInputElement>("[data-om-autocomplete-input]")!;
    input.value = "beta";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await vi.waitFor(() => expect(root.querySelectorAll("[data-om-autocomplete-item]")).toHaveLength(1));

    root.querySelector<HTMLButtonElement>("[data-om-autocomplete-item]")!.click();

    expect(input.value).toBe("Beta Stream");
    expect(input.dataset.omAutocompleteValue).toBe("beta");
    expect(selected).toHaveBeenCalledWith(
      expect.objectContaining({ detail: { component, option: { value: "beta", label: "Beta Stream" } } })
    );

    await component.stop();
  });

  it("选择结果时同步隐藏提交字段", async () => {
    document.body.innerHTML = `
      <section>
        <input type="hidden" name="channel_id" data-om-autocomplete-value-control>
        <input data-om-autocomplete-input>
        <div data-om-autocomplete-list hidden></div>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Autocomplete(root);
    component.setOptions([{ value: "42", label: "BBC One" }]);

    await component.start();
    const input = root.querySelector<HTMLInputElement>("[data-om-autocomplete-input]")!;
    input.value = "bbc";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await vi.waitFor(() => expect(root.querySelectorAll("[data-om-autocomplete-item]")).toHaveLength(1));

    root.querySelector<HTMLButtonElement>("[data-om-autocomplete-item]")!.click();

    expect(root.querySelector<HTMLInputElement>("[data-om-autocomplete-value-control]")!.value).toBe("42");
    expect(input.value).toBe("BBC One");

    await component.stop();
  });

  it("从声明式本地 JSON 加载候选并支持键盘选择", async () => {
    document.body.innerHTML = `
      <section data-om-autocomplete-options='["Apple", {"value":"banana","label":"Banana"}]'>
        <input data-om-autocomplete-input>
        <div data-om-autocomplete-list hidden></div>
        <div data-om-autocomplete-empty hidden></div>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Autocomplete(root);

    await component.start();
    const input = root.querySelector<HTMLInputElement>("[data-om-autocomplete-input]")!;
    input.value = "a";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await vi.waitFor(() => expect(root.querySelectorAll("[data-om-autocomplete-item]")).toHaveLength(2));

    input.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "ArrowDown" }));
    input.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Enter" }));

    expect(input.value).toBe("Banana");
    expect(input.dataset.omAutocompleteValue).toBe("banana");

    await component.stop();
  });

  it("从远程 JSON 加载候选", async () => {
    document.body.innerHTML = `
      <section data-om-autocomplete-src="/api/search">
        <input data-om-autocomplete-input>
        <div data-om-autocomplete-list hidden></div>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Autocomplete(root);
    Object.assign(component.http, {
      getJson: vi.fn().mockResolvedValue([{ value: "live", label: "Live Stream" }])
    });

    await component.start();
    const input = root.querySelector<HTMLInputElement>("[data-om-autocomplete-input]")!;
    input.value = "live";
    input.dispatchEvent(new Event("input", { bubbles: true }));

    await vi.waitFor(() => expect(root.querySelector("[data-om-autocomplete-item]")?.textContent).toBe("Live Stream"));
    expect(component.http.getJson).toHaveBeenCalledWith(
      "/api/search?q=live",
      expect.objectContaining({ signal: expect.anything() })
    );

    await component.stop();
  });

  it("远程 provider 搜索会发送 bind、搜索词和白名单依赖字段", async () => {
    document.body.innerHTML = `
      <form>
        <input name="country_id" value="uk">
        <section
          data-om-select-src="/admin/select/channels"
          data-om-select-bind="signed-context"
          data-om-select-dependent-fields="country_id"
          data-om-select-page-size="10">
          <input data-om-autocomplete-input>
          <div data-om-autocomplete-list hidden></div>
        </section>
      </form>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Autocomplete(root);
    Object.assign(component.http, {
      getJson: vi.fn().mockResolvedValue({
        results: [{ id: "bbc", text: "BBC One" }],
        more: false
      })
    });

    await component.start();
    const input = root.querySelector<HTMLInputElement>("[data-om-autocomplete-input]")!;
    input.value = "bbc";
    input.dispatchEvent(new Event("input", { bubbles: true }));

    await vi.waitFor(() => expect(root.querySelector("[data-om-autocomplete-item]")?.textContent).toBe("BBC One"));
    expect(component.http.getJson).toHaveBeenCalledWith(
      "/admin/select/channels?q=bbc&bind=signed-context&page=1&page_size=10&depends%5Bcountry_id%5D=uk",
      expect.objectContaining({ signal: expect.anything() })
    );

    await component.stop();
  });

  it("provider 返回 more 后可以继续按相同上下文加载下一页候选", async () => {
    document.body.innerHTML = `
      <form>
        <input name="country_id" value="uk">
        <section
          data-om-select-src="/admin/select/channels"
          data-om-select-bind="signed-context"
          data-om-select-dependent-fields="country_id"
          data-om-select-page-size="10">
          <input data-om-autocomplete-input>
          <div data-om-autocomplete-list hidden></div>
        </section>
      </form>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Autocomplete(root);
    Object.assign(component.http, {
      getJson: vi
        .fn()
        .mockResolvedValueOnce({ results: [{ id: "bbc", text: "BBC One" }], more: true })
        .mockResolvedValueOnce({ results: [{ id: "cnn", text: "CNN" }], more: false })
    });

    await component.start();
    const input = root.querySelector<HTMLInputElement>("[data-om-autocomplete-input]")!;
    input.value = "news";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await vi.waitFor(() => expect(root.querySelectorAll("[data-om-autocomplete-item]")).toHaveLength(1));

    const nextOptions = await component.loadNextPage();

    expect(component.http.getJson).toHaveBeenLastCalledWith(
      "/admin/select/channels?q=news&bind=signed-context&page=2&page_size=10&depends%5Bcountry_id%5D=uk",
      expect.objectContaining({ signal: expect.anything() })
    );
    expect(nextOptions.map((option) => option.value)).toEqual(["cnn"]);
    expect(Array.from(root.querySelectorAll("[data-om-autocomplete-item]")).map((item) => item.textContent)).toEqual(["BBC One", "CNN"]);

    await component.stop();
  });

  it("普通远程 provider 加载下一页候选时发送页码", async () => {
    document.body.innerHTML = `
      <section data-om-autocomplete-src="/api/search">
        <input data-om-autocomplete-input>
        <div data-om-autocomplete-list hidden></div>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Autocomplete(root);
    Object.assign(component.http, {
      getJson: vi
        .fn()
        .mockResolvedValueOnce({ results: [{ id: "a", text: "A" }], more: true })
        .mockResolvedValueOnce({ results: [{ id: "b", text: "B" }], more: false })
    });

    await component.start();
    const input = root.querySelector<HTMLInputElement>("[data-om-autocomplete-input]")!;
    input.value = "news";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await vi.waitFor(() => expect(root.querySelectorAll("[data-om-autocomplete-item]")).toHaveLength(1));
    await component.loadNextPage();

    expect(component.http.getJson).toHaveBeenLastCalledWith(
      "/api/search?q=news&page=2",
      expect.objectContaining({ signal: expect.anything() })
    );

    await component.stop();
  });

  it("远程 provider 初始请求会带 value 并回填输入框 label", async () => {
    document.body.innerHTML = `
      <section
        data-om-select-src="/admin/select/channels"
        data-om-select-bind="signed-context"
        data-om-select-page-size="10">
        <input type="hidden" name="channel_id" value="bbc" data-om-autocomplete-value-control>
        <input data-om-autocomplete-input>
        <div data-om-autocomplete-list hidden></div>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Autocomplete(root);
    Object.assign(component.http, {
      getJson: vi.fn().mockResolvedValue({
        results: [{ id: "bbc", text: "BBC One", selected: true }],
        more: false
      })
    });

    await component.start();

    expect(component.http.getJson).toHaveBeenCalledWith(
      "/admin/select/channels?bind=signed-context&page=1&page_size=10&value=bbc",
      expect.objectContaining({ signal: expect.anything() })
    );
    expect(root.querySelector<HTMLInputElement>("[data-om-autocomplete-input]")!.value).toBe("BBC One");
    expect(root.querySelector<HTMLInputElement>("[data-om-autocomplete-input]")!.dataset.omAutocompleteValue).toBe("bbc");

    await component.stop();
  });

  it("远程 provider 返回表单错误响应时触发 autocomplete 错误事件", async () => {
    document.body.innerHTML = `
      <section data-om-autocomplete-src="/admin/select/channels">
        <input data-om-autocomplete-input>
        <div data-om-autocomplete-list hidden></div>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Autocomplete(root);
    const failed = vi.fn();
    root.addEventListener("om:autocomplete:error", failed);
    Object.assign(component.http, {
      getJson: vi.fn().mockResolvedValue({
        error_code: 4000,
        message: "Invalid autocomplete bind",
        errors: { bind: "Invalid autocomplete bind" }
      })
    });

    await component.start();
    const input = root.querySelector<HTMLInputElement>("[data-om-autocomplete-input]")!;
    input.value = "bbc";
    input.dispatchEvent(new Event("input", { bubbles: true }));

    await vi.waitFor(() => expect(failed).toHaveBeenCalledWith(expect.objectContaining({
      detail: expect.objectContaining({
        component,
        message: "Invalid autocomplete bind",
        response: expect.objectContaining({ error_code: 4000 })
      })
    })));
    expect(root.dataset.omStatus).toBe("error");
    expect(root.querySelectorAll("[data-om-autocomplete-item]")).toHaveLength(0);

    await component.stop();
  });

  it("远程 provider 返回非法协议时触发 autocomplete 错误事件", async () => {
    document.body.innerHTML = `
      <section data-om-autocomplete-src="/admin/select/channels">
        <input data-om-autocomplete-input>
        <div data-om-autocomplete-list hidden></div>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Autocomplete(root);
    const failed = vi.fn();
    root.addEventListener("om:autocomplete:error", failed);
    Object.assign(component.http, { getJson: vi.fn().mockResolvedValue({ results: "bad", more: false }) });

    await component.start();
    const input = root.querySelector<HTMLInputElement>("[data-om-autocomplete-input]")!;
    input.value = "bbc";
    input.dispatchEvent(new Event("input", { bubbles: true }));

    await vi.waitFor(() => expect(failed).toHaveBeenCalledWith(expect.objectContaining({
      detail: expect.objectContaining({
        component,
        message: "Invalid select provider response"
      })
    })));
    expect(root.dataset.omStatus).toBe("error");

    await component.stop();
  });

  it("远程 JSON 搜索时同步加载态和空状态", async () => {
    document.body.innerHTML = `
      <section data-om-autocomplete-src="/api/search">
        <input data-om-autocomplete-input>
        <div data-om-autocomplete-list hidden></div>
        <div data-om-autocomplete-loading hidden></div>
        <div data-om-autocomplete-empty hidden></div>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Autocomplete(root);
    Object.assign(component.http, {
      getJson: vi.fn().mockResolvedValue([])
    });

    await component.start();
    const input = root.querySelector<HTMLInputElement>("[data-om-autocomplete-input]")!;
    input.value = "missing";
    input.dispatchEvent(new Event("input", { bubbles: true }));

    await vi.waitFor(() => expect(root.querySelector<HTMLElement>("[data-om-autocomplete-empty]")!.hidden).toBe(false));
    expect(root.querySelector<HTMLElement>("[data-om-autocomplete-loading]")!.hidden).toBe(true);

    await component.stop();
  });

  it("用户修改已选文本时立即清空隐藏值", async () => {
    document.body.innerHTML = `
      <section>
        <input type="hidden" value="42" data-om-autocomplete-value-control>
        <input value="BBC One" data-om-autocomplete-input data-om-autocomplete-value="42">
        <div data-om-autocomplete-list hidden></div>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Autocomplete(root);
    await component.start();
    const input = root.querySelector<HTMLInputElement>("[data-om-autocomplete-input]")!;

    input.value = "BBC";
    input.dispatchEvent(new Event("input", { bubbles: true }));

    expect(root.querySelector<HTMLInputElement>("[data-om-autocomplete-value-control]")!.value).toBe("");
    expect(input.dataset.omAutocompleteValue).toBeUndefined();
    await component.stop();
  });

  it("远程搜索取消旧请求并忽略迟到结果", async () => {
    vi.useFakeTimers();
    document.body.innerHTML = `
      <section data-om-autocomplete-src="/api/search">
        <input data-om-autocomplete-input>
        <div data-om-autocomplete-list hidden></div>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    let resolveFirst!: (value: unknown) => void;
    let resolveSecond!: (value: unknown) => void;
    const getJson = vi
      .fn()
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveSecond = resolve; }));
    const component = new Autocomplete(root);
    Object.assign(component.http, { getJson });
    await component.start();
    const input = root.querySelector<HTMLInputElement>("input")!;

    input.value = "b";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await vi.advanceTimersByTimeAsync(200);
    const firstSignal = getJson.mock.calls[0]?.[1]?.signal as AbortSignal;
    input.value = "bb";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await vi.advanceTimersByTimeAsync(200);

    expect(firstSignal.aborted).toBe(true);
    resolveSecond({ results: [{ id: "new", text: "New" }], more: false });
    await Promise.resolve();
    resolveFirst({ results: [{ id: "old", text: "Old" }], more: false });
    await Promise.resolve();
    await Promise.resolve();
    expect(root.querySelector("[data-om-autocomplete-item]")?.textContent).toBe("New");

    await component.stop();
    vi.useRealTimers();
  });

  it("HTML 模式只增强候选显示且图片失败时保留文字回退", async () => {
    document.body.innerHTML = `
      <section data-om-autocomplete-options='[{"value":"bbc","label":"BBC One","html":"<span><img src=bad.png>BBC One HD</span>"}]' data-om-select-label-mode="html">
        <input data-om-autocomplete-input>
        <div data-om-autocomplete-list hidden></div>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Autocomplete(root);
    await component.start();
    const input = root.querySelector<HTMLInputElement>("input")!;
    input.value = "bbc";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await vi.waitFor(() => expect(root.querySelector("[data-om-autocomplete-item] img")).not.toBeNull());

    const item = root.querySelector<HTMLElement>("[data-om-autocomplete-item]")!;
    expect(item.getAttribute("aria-label")).toBe("BBC One");
    const image = item.querySelector<HTMLImageElement>("img")!;
    image.dispatchEvent(new Event("error"));
    expect(image.hidden).toBe(true);
    item.click();
    expect(input.value).toBe("BBC One");

    await component.stop();
  });

  it("依赖字段变化会清空选择、候选和分页后重新查询", async () => {
    vi.useFakeTimers();
    document.body.innerHTML = `
      <form>
        <select name="country_id"><option value="uk" selected>UK</option><option value="us">US</option></select>
        <section data-om-select-src="/api/search" data-om-select-bind="signed" data-om-select-dependent-fields="country_id">
          <input type="hidden" value="bbc" data-om-autocomplete-value-control>
          <input value="BBC" data-om-autocomplete-input data-om-autocomplete-value="bbc">
          <div data-om-autocomplete-list hidden></div>
        </section>
      </form>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const getJson = vi.fn().mockResolvedValue({ results: [{ id: "bbc", text: "BBC" }], more: true });
    const component = new Autocomplete(root);
    Object.assign(component.http, { getJson });
    await component.start();

    const country = document.querySelector<HTMLSelectElement>("[name='country_id']")!;
    country.value = "us";
    country.dispatchEvent(new Event("change", { bubbles: true }));
    expect(root.querySelector<HTMLInputElement>("[data-om-autocomplete-value-control]")!.value).toBe("");
    expect(root.querySelector<HTMLInputElement>("[data-om-autocomplete-input]")!.value).toBe("");
    await vi.advanceTimersByTimeAsync(200);
    expect(getJson).toHaveBeenLastCalledWith("/api/search?bind=signed&page=1&depends%5Bcountry_id%5D=us", expect.anything());

    await component.stop();
    vi.useRealTimers();
  });

  it("下一页按钮保持可聚焦并按 value 去重", async () => {
    document.body.innerHTML = `
      <section data-om-autocomplete-src="/api/search">
        <input data-om-autocomplete-input>
        <div data-om-autocomplete-list hidden></div>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Autocomplete(root);
    Object.assign(component.http, {
      getJson: vi
        .fn()
        .mockResolvedValueOnce({ results: [{ id: "a", text: "A" }], more: true })
        .mockResolvedValueOnce({ results: [{ id: "a", text: "A again" }, { id: "b", text: "B" }], more: false })
    });
    await component.start();
    const input = root.querySelector<HTMLInputElement>("input")!;
    input.value = "a";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await vi.waitFor(() => expect(root.querySelector("[data-om-autocomplete-load-more]")).not.toBeNull());
    const list = root.querySelector<HTMLElement>("[data-om-autocomplete-list]")!;
    list.scrollTop = 29;
    expect(root.querySelector<HTMLButtonElement>("[data-om-autocomplete-load-more]")!.tabIndex).toBe(0);

    root.querySelector<HTMLButtonElement>("[data-om-autocomplete-load-more]")!.click();
    await vi.waitFor(() => expect(Array.from(root.querySelectorAll("[data-om-autocomplete-item]")).map((item) => item.textContent)).toEqual(["A", "B"]));
    expect(list.scrollTop).toBe(29);
    expect(root.querySelector<HTMLElement>("[data-om-autocomplete-load-more]")?.hidden).toBe(true);

    await component.stop();
  });

  it("下一页失败时保留候选并提供重试", async () => {
    document.body.innerHTML = `
      <section data-om-autocomplete-src="/api/search">
        <input data-om-autocomplete-input>
        <div data-om-autocomplete-list hidden></div>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Autocomplete(root);
    Object.assign(component.http, {
      getJson: vi
        .fn()
        .mockResolvedValueOnce({ results: [{ id: "a", text: "A" }], more: true })
        .mockRejectedValueOnce(new Error("offline"))
        .mockResolvedValueOnce({ results: [{ id: "b", text: "B" }], more: false })
    });

    await component.start();
    const input = root.querySelector<HTMLInputElement>("input")!;
    input.value = "a";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await vi.waitFor(() => expect(root.querySelector("[data-om-autocomplete-load-more]")).not.toBeNull());
    root.querySelector<HTMLButtonElement>("[data-om-autocomplete-load-more]")!.click();
    await vi.waitFor(() => expect(root.querySelector("[data-om-autocomplete-load-more]")?.textContent).toBe("Retry"));
    expect(Array.from(root.querySelectorAll("[data-om-autocomplete-item]")).map((item) => item.textContent)).toEqual(["A"]);

    root.querySelector<HTMLButtonElement>("[data-om-autocomplete-load-more]")!.click();
    await vi.waitFor(() => expect(Array.from(root.querySelectorAll("[data-om-autocomplete-item]")).map((item) => item.textContent)).toEqual(["A", "B"]));
    await component.stop();
  });
});
