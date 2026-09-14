import { describe, expect, it, vi } from "vitest";
import { createI18n } from "../core/i18n";
import { Select, normalizeSelectOptions, type SelectOption } from "./select";

describe("Select", () => {
  it("完整保留 provider 候选状态", () => {
    expect(normalizeSelectOptions({
      results: [{ id: 12, text: "BBC", html: "<b>BBC</b>", selected: true, disabled: true, data: { country: "uk" } }],
      more: false
    })).toEqual([{
      value: "12",
      label: "BBC",
      html: "<b>BBC</b>",
      selected: true,
      disabled: true,
      data: { country: "uk" }
    }]);
  });

  it("读取单选和多选值并派发变更事件", async () => {
    document.body.innerHTML = `
      <section>
        <select data-om-select-control multiple>
          <option value="a" selected>Alpha</option>
          <option value="b" selected>Beta</option>
        </select>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Select(root);
    const changed = vi.fn();
    root.addEventListener("om:select:change", changed);

    await component.start();
    root.querySelector<HTMLSelectElement>("[data-om-select-control]")!.dispatchEvent(new Event("change", { bubbles: true }));

    expect(component.selectedValues()).toEqual(["a", "b"]);
    expect(changed).toHaveBeenCalledWith(expect.objectContaining({ detail: { component, values: ["a", "b"] } }));

    await component.stop();
  });

  it("按搜索输入隐藏不匹配的选项", async () => {
    document.body.innerHTML = `
      <section>
        <input data-om-select-search>
        <select data-om-select-control>
          <option value="a">Alpha</option>
          <option value="b">Beta</option>
        </select>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Select(root);

    await component.start();
    const search = root.querySelector<HTMLInputElement>("[data-om-select-search]")!;
    search.value = "beta";
    search.dispatchEvent(new Event("input", { bubbles: true }));

    const options = Array.from(root.querySelectorAll<HTMLOptionElement>("option"));
    expect(options.map((option) => option.hidden)).toEqual([true, false]);

    await component.stop();
  });

  it("从远程 JSON 加载选项", async () => {
    document.body.innerHTML = `
      <section data-om-select-src="/api/options">
        <select data-om-select-control></select>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const options = [{ id: "vod", text: "VOD" }];
    const component = new Select(root);
    Object.assign(component.http, { getJson: vi.fn().mockResolvedValue(options) });

    await component.start();

    expect(component.http.getJson).toHaveBeenCalledWith("/api/options", expect.objectContaining({ signal: expect.anything() }));
    expect(root.querySelector("option")?.value).toBe("vod");
    expect(root.querySelector("option")?.textContent).toBe("VOD");

    await component.stop();
  });

  it("归一化后端 Select provider 的 results/more 协议", async () => {
    document.body.innerHTML = `
      <section data-om-select-src="/admin/select/channels">
        <select data-om-select-control></select>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Select(root);
    Object.assign(component.http, {
      getJson: vi.fn().mockResolvedValue({
        results: [{ id: 12, text: "BBC One", html: "<span>BBC One</span>", selected: true, disabled: false, data: { country: "uk" } }],
        more: false
      })
    });

    await component.start();

    expect(root.querySelector("option")?.value).toBe("12");
    expect(root.querySelector("option")?.textContent).toBe("BBC One");
    expect(root.querySelector<HTMLOptionElement>("option")?.selected).toBe(true);

    await component.stop();
  });

  it("普通远程 provider 加载下一页时发送页码", async () => {
    document.body.innerHTML = `
      <section data-om-select-src="/api/options">
        <select data-om-select-control></select>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Select(root);
    Object.assign(component.http, {
      getJson: vi
        .fn()
        .mockResolvedValueOnce({ results: [{ id: "a", text: "A" }], more: true })
        .mockResolvedValueOnce({ results: [{ id: "b", text: "B" }], more: false })
    });

    await component.start();
    await component.loadNextPage();

    expect(component.http.getJson).toHaveBeenLastCalledWith(
      "/api/options?page=2",
      expect.objectContaining({ signal: expect.anything() })
    );

    await component.stop();
  });

  it("原生多选加载下一页时保留当前选择", async () => {
    document.body.innerHTML = `
      <section data-om-select-src="/api/options">
        <select data-om-select-control multiple></select>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Select(root);
    Object.assign(component.http, {
      getJson: vi
        .fn()
        .mockResolvedValueOnce({ results: [{ id: "a", text: "A" }], more: true })
        .mockResolvedValueOnce({ results: [{ id: "b", text: "B" }], more: false })
    });

    await component.start();
    root.querySelector<HTMLOptionElement>("option[value='a']")!.selected = true;
    await component.loadNextPage();

    expect(component.selectedValues()).toEqual(["a"]);
    expect(Array.from(root.querySelectorAll("option"), (option) => option.value)).toEqual(["a", "b"]);

    await component.stop();
  });

  it("远程 provider 返回表单错误响应时触发 select 错误事件", async () => {
    document.body.innerHTML = `
      <section data-om-select-src="/admin/select/channels">
        <select data-om-select-control>
          <option value="old">Old</option>
        </select>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Select(root);
    const failed = vi.fn();
    root.addEventListener("om:select:error", failed);
    Object.assign(component.http, {
      getJson: vi.fn().mockResolvedValue({
        error_code: 4000,
        message: "Invalid select bind",
        errors: { bind: "Invalid select bind" }
      })
    });

    await component.start();

    expect(failed).toHaveBeenCalledWith(expect.objectContaining({
      detail: expect.objectContaining({
        component,
        message: "Invalid select bind",
        response: expect.objectContaining({ error_code: 4000 })
      })
    }));
    expect(root.dataset.omStatus).toBe("error");
    expect(root.querySelector("option")?.value).toBe("old");

    await component.stop();
  });

  it("远程 provider 返回非法协议时触发 select 错误事件", async () => {
    document.body.innerHTML = `
      <section data-om-select-src="/admin/select/channels">
        <select data-om-select-control></select>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Select(root);
    const failed = vi.fn();
    root.addEventListener("om:select:error", failed);
    Object.assign(component.http, { getJson: vi.fn().mockResolvedValue({ results: "bad", more: false }) });

    await component.start();

    expect(failed).toHaveBeenCalledWith(expect.objectContaining({
      detail: expect.objectContaining({
        component,
        message: "Invalid select provider response"
      })
    }));
    expect(root.dataset.omStatus).toBe("error");

    await component.stop();
  });

  it("远程 provider 请求会带上 bind 和白名单依赖字段", async () => {
    document.body.innerHTML = `
      <form>
        <input name="country_id" value="uk">
        <input name="category_id" value="">
        <input name="ignored" value="x">
        <section
          data-om-select-src="/admin/select/channels"
          data-om-select-bind="signed-context"
          data-om-select-dependent-fields="country_id,category_id"
          data-om-select-page-size="30">
          <select data-om-select-control></select>
        </section>
      </form>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Select(root);
    Object.assign(component.http, { getJson: vi.fn().mockResolvedValue({ results: [], more: false }) });

    await component.start();

    expect(component.http.getJson).toHaveBeenCalledWith(
      "/admin/select/channels?bind=signed-context&page=1&page_size=30&depends%5Bcountry_id%5D=uk",
      expect.objectContaining({ signal: expect.anything() })
    );

    await component.stop();
  });

  it("远程 provider 初始请求会带上单选 value 用于回显", async () => {
    document.body.innerHTML = `
      <section
        data-om-select-src="/admin/select/channels"
        data-om-select-bind="signed-context"
        data-om-select-page-size="20">
        <select data-om-select-control>
          <option value="bbc" selected>BBC One</option>
        </select>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Select(root);
    Object.assign(component.http, {
      getJson: vi.fn().mockResolvedValue({
        results: [{ id: "bbc", text: "BBC One" }],
        more: false
      })
    });

    await component.start();

    expect(component.http.getJson).toHaveBeenCalledWith(
      "/admin/select/channels?bind=signed-context&page=1&page_size=20&value=bbc",
      expect.objectContaining({ signal: expect.anything() })
    );
    expect(root.querySelector<HTMLOptionElement>("option[value='bbc']")?.selected).toBe(true);

    await component.stop();
  });

  it("远程搜索不会丢失当前选择", async () => {
    document.body.innerHTML = `
      <section data-om-select-src="/api/options">
        <select data-om-select-control><option value="bbc" selected>BBC One</option></select>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Select(root);
    Object.assign(component.http, {
      getJson: vi
        .fn()
        .mockResolvedValueOnce({ results: [{ id: "bbc", text: "BBC One" }], more: false })
        .mockResolvedValueOnce({ results: [{ id: "cnn", text: "CNN" }], more: false })
    });

    await component.start();
    await component.loadOptions("/api/options", "cnn");

    expect(component.selectedValues()).toEqual(["bbc"]);
    expect(Array.from(root.querySelectorAll("option")).map((option) => option.value)).toEqual(["cnn", "bbc"]);
    await component.stop();
  });

  it("远程 provider 初始请求会按顺序带上多选 values 用于回显", async () => {
    document.body.innerHTML = `
      <section
        data-om-select-src="/admin/select/channels"
        data-om-select-bind="signed-context"
        data-om-select-page-size="20">
        <select data-om-select-control multiple>
          <option value="bbc" selected>BBC One</option>
          <option value="cnn" selected>CNN</option>
        </select>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Select(root);
    Object.assign(component.http, {
      getJson: vi.fn().mockResolvedValue({
        results: [
          { id: "bbc", text: "BBC One" },
          { id: "cnn", text: "CNN" }
        ],
        more: false
      })
    });

    await component.start();

    expect(component.http.getJson).toHaveBeenCalledWith(
      "/admin/select/channels?bind=signed-context&page=1&page_size=20&values=bbc&values=cnn",
      expect.objectContaining({ signal: expect.anything() })
    );
    expect(component.selectedValues()).toEqual(["bbc", "cnn"]);

    await component.stop();
  });

  it("远程搜索输入会带 q 重新请求 provider", async () => {
    document.body.innerHTML = `
      <section
        data-om-select-src="/admin/select/channels"
        data-om-select-bind="signed-context"
        data-om-select-page-size="20">
        <input data-om-select-search>
        <select data-om-select-control></select>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Select(root);
    Object.assign(component.http, { getJson: vi.fn().mockResolvedValue({ results: [], more: false }) });

    await component.start();
    const search = root.querySelector<HTMLInputElement>("[data-om-select-search]")!;

    search.value = "bbc";
    search.dispatchEvent(new Event("input", { bubbles: true }));

    await vi.waitFor(() =>
      expect(component.http.getJson).toHaveBeenLastCalledWith(
        "/admin/select/channels?bind=signed-context&page=1&page_size=20&q=bbc",
        expect.objectContaining({ signal: expect.anything() })
      )
    );

    await component.stop();
  });

  it("provider 返回 more 后可以继续按相同上下文加载下一页", async () => {
    document.body.innerHTML = `
      <form>
        <input name="country_id" value="uk">
        <section
          data-om-select-src="/admin/select/channels"
          data-om-select-bind="signed-context"
          data-om-select-dependent-fields="country_id"
          data-om-select-page-size="20">
          <select data-om-select-control></select>
        </section>
      </form>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Select(root);
    Object.assign(component.http, {
      getJson: vi
        .fn()
        .mockResolvedValueOnce({ results: [], more: false })
        .mockResolvedValueOnce({ results: [{ id: "bbc", text: "BBC One" }], more: true })
        .mockResolvedValueOnce({ results: [{ id: "cnn", text: "CNN" }], more: false })
    });

    await component.start();
    await component.loadOptions("/admin/select/channels", "bbc");
    const nextOptions = await component.loadNextPage();

    expect(component.http.getJson).toHaveBeenLastCalledWith(
      "/admin/select/channels?bind=signed-context&page=2&page_size=20&q=bbc&depends%5Bcountry_id%5D=uk",
      expect.objectContaining({ signal: expect.anything() })
    );
    expect(nextOptions.map((option) => option.value)).toEqual(["cnn"]);
    expect(Array.from(root.querySelectorAll("option")).map((option) => option.value)).toEqual(["bbc", "cnn"]);

    await component.stop();
  });

  it("Choices 搜索事件会带 q 重新请求 provider", async () => {
    document.body.innerHTML = `
      <section
        data-om-select-src="/admin/select/channels"
        data-om-select-bind="signed-context"
        data-om-select-page-size="20"
        data-om-select-enhance="choices">
        <select data-om-select-control data-choices></select>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const select = root.querySelector<HTMLSelectElement>("select")!;
    const component = new Select(root);
    Object.assign(component.http, { getJson: vi.fn().mockResolvedValue({ results: [], more: false }) });

    await component.start();
    select.dispatchEvent(new CustomEvent("search", { bubbles: true, detail: { value: "cnn" } }));

    await vi.waitFor(() =>
      expect(component.http.getJson).toHaveBeenLastCalledWith(
        "/admin/select/channels?bind=signed-context&page=1&page_size=20&q=cnn",
        expect.objectContaining({ signal: expect.anything() })
      )
    );

    await component.stop();
  });

  it("Choices 可见搜索框输入会带 q 重新请求 provider", async () => {
    document.body.innerHTML = `
      <section
        data-om-select-src="/admin/select/channels"
        data-om-select-bind="signed-context"
        data-om-select-page-size="20"
        data-om-select-enhance="choices">
        <select data-om-select-control data-choices></select>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Select(root);
    Object.assign(component.http, { getJson: vi.fn().mockResolvedValue({ results: [], more: false }) });

    await component.start();
    const searchInput = document.querySelector<HTMLInputElement>(".choices__input--cloned")!;
    searchInput.value = "news";
    searchInput.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: "news" }));

    await vi.waitFor(() =>
      expect(component.http.getJson).toHaveBeenLastCalledWith(
        "/admin/select/channels?bind=signed-context&page=1&page_size=20&q=news",
        expect.objectContaining({ signal: expect.anything() })
      )
    );

    await component.stop();
  });

  it("根节点为 select 时 Choices 可见搜索框输入会带 q 重新请求 provider", async () => {
    document.body.innerHTML = `
      <select
        data-om-component="select"
        data-om-select-control
        data-om-select-src="/admin/select/channels"
        data-om-select-bind="signed-context"
        data-om-select-page-size="20"
        data-choices>
      </select>
    `;
    const root = document.querySelector<HTMLElement>("select")!;
    const component = new Select(root);
    Object.assign(component.http, { getJson: vi.fn().mockResolvedValue({ results: [], more: false }) });

    await component.start();
    const searchInput = document.querySelector<HTMLInputElement>(".choices__input--cloned")!;
    searchInput.value = "music";
    searchInput.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: "music" }));

    await vi.waitFor(() =>
      expect(component.http.getJson).toHaveBeenLastCalledWith(
        "/admin/select/channels?bind=signed-context&page=1&page_size=20&q=music",
        expect.objectContaining({ signal: expect.anything() })
      )
    );

    await component.stop();
  });

  it("同步启用和禁用 Choices 增强控件", async () => {
    document.body.innerHTML = `
      <select class="form-control" data-choices>
        <option value="a" selected>A</option>
      </select>
    `;
    const root = document.querySelector<HTMLElement>("[data-choices]")!;
    const component = new Select(root);

    await component.start();

    component.disable();
    expect((root as HTMLSelectElement).disabled).toBe(true);
    expect(document.querySelector(".choices")?.classList.contains("is-disabled")).toBe(true);

    component.enable();
    expect((root as HTMLSelectElement).disabled).toBe(false);
    expect(document.querySelector(".choices")?.classList.contains("is-disabled")).toBe(false);

    await component.stop();
  });

  it("从声明式本地 JSON 加载选项", async () => {
    document.body.innerHTML = `
      <section data-om-select-options='["Live TV", {"value":"vod","label":"VOD","selected":true}]'>
        <select data-om-select-control></select>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Select(root);

    await component.start();

    expect(root.querySelectorAll("option")).toHaveLength(2);
    expect(root.querySelector<HTMLOptionElement>("option[value='vod']")?.selected).toBe(true);
    expect(component.selectedValues()).toEqual(["vod"]);

    await component.stop();
  });

  it("管理 data-choices 增强控件并在销毁时恢复原始 DOM", async () => {
    document.body.innerHTML = `
      <select class="form-control" data-choices data-choices-search-false data-choices-removeItem>
        <option value="">Choose one</option>
        <option value="a" selected>A</option>
        <option value="b">B</option>
      </select>
    `;
    const root = document.querySelector<HTMLElement>("[data-choices]")!;
    const component = new Select(root);

    await component.start();

    expect(document.querySelector(".choices")).not.toBeNull();
    expect(document.querySelector(".choices__input--cloned")).toBeNull();
    expect(component.selectedValues()).toEqual(["a"]);

    await component.stop();

    expect(document.querySelector(".choices")).toBeNull();
    expect(document.querySelector("[data-choices]")).toBe(root);
  });

  it("使用共享 i18n 翻译 Choices 的空候选提示", async () => {
    document.body.innerHTML = '<select data-choices></select>';
    const root = document.querySelector<HTMLElement>("[data-choices]")!;
    const component = new Select(root, {
      i18n: createI18n({
        locale: "zh-Hans",
        messages: { "No choices available": "没有可选项" }
      })
    });

    await component.start();

    expect(document.querySelector(".choices__list--dropdown")?.textContent).toContain("没有可选项");

    await component.stop();
  });

  it("先加载远程选项再初始化 Choices 可见内容", async () => {
    document.body.innerHTML = `
      <section data-om-select-src="/api/options" data-om-select-enhance="choices">
        <select data-om-select-control data-choices></select>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const options: SelectOption[] = [
      { value: "live", label: "Live TV" },
      { value: "vod", label: "VOD" }
    ];
    const component = new Select(root);
    Object.assign(component.http, { getJson: vi.fn().mockResolvedValue(options) });

    await component.start();

    expect(component.http.getJson).toHaveBeenCalledWith("/api/options", expect.objectContaining({ signal: expect.anything() }));
    expect(document.querySelector(".choices__list--single")?.textContent).toContain("Live TV");
    expect(document.querySelectorAll(".choices__list--single .choices__item")).toHaveLength(1);

    await component.stop();
  });

  it("Choices 初始化时不会重复创建远程回显的已选项", async () => {
    document.body.innerHTML = `
      <section data-om-select-src="/api/options" data-om-select-enhance="choices">
        <select data-om-select-control data-choices>
          <option value="atlas" selected>Atlas GB</option>
        </select>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Select(root);
    Object.assign(component.http, {
      getJson: vi.fn().mockResolvedValue({
        results: [{ id: "atlas", text: "Atlas GB" }],
        more: false
      })
    });

    await component.start();

    expect(root.querySelectorAll("option[value='atlas']")).toHaveLength(1);
    expect(root.querySelectorAll(".choices__list--single .choices__item")).toHaveLength(1);
    expect(root.querySelectorAll(".choices__item--choice[data-value='atlas']")).toHaveLength(1);

    await component.stop();
  });

  it("远程搜索取消旧请求并忽略迟到结果", async () => {
    vi.useFakeTimers();
    document.body.innerHTML = `
      <section data-om-select-src="/api/options">
        <input data-om-select-search>
        <select data-om-select-control></select>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    let resolveFirst!: (value: unknown) => void;
    let resolveSecond!: (value: unknown) => void;
    const getJson = vi
      .fn()
      .mockResolvedValueOnce({ results: [], more: false })
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveSecond = resolve; }));
    const component = new Select(root);
    Object.assign(component.http, { getJson });

    await component.start();
    const search = root.querySelector<HTMLInputElement>("[data-om-select-search]")!;
    search.value = "b";
    search.dispatchEvent(new Event("input", { bubbles: true }));
    await vi.advanceTimersByTimeAsync(200);
    const firstSignal = getJson.mock.calls[1]?.[1]?.signal as AbortSignal;

    search.value = "bb";
    search.dispatchEvent(new Event("input", { bubbles: true }));
    await vi.advanceTimersByTimeAsync(200);

    expect(firstSignal.aborted).toBe(true);
    resolveSecond({ results: [{ id: "new", text: "New" }], more: false });
    await Promise.resolve();
    resolveFirst({ results: [{ id: "old", text: "Old" }], more: false });
    await Promise.resolve();
    await Promise.resolve();
    expect(Array.from(root.querySelectorAll("option")).map((option) => option.value)).toEqual(["new"]);

    await component.stop();
    vi.useRealTimers();
  });

  it("增强下拉只在候选中显示可信 HTML，并保留完整选项状态", async () => {
    document.body.innerHTML = `
      <section data-om-select-src="/api/options" data-om-select-label-mode="html" data-om-select-enhance="choices">
        <select data-om-select-control data-choices></select>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Select(root);
    Object.assign(component.http, {
      getJson: vi.fn().mockResolvedValue({
        results: [{ id: "bbc", text: "BBC One", html: '<span><img src="bad.png">BBC One HD</span>', disabled: true, data: { country: "uk" } }],
        more: false
      })
    });

    await component.start();

    const native = root.querySelector<HTMLOptionElement>("option")!;
    const candidate = root.querySelector<HTMLElement>(".choices__item--choice")!;
    expect(native.textContent).toBe("BBC One");
    expect(native.disabled).toBe(true);
    expect(candidate.querySelector("img")).not.toBeNull();
    expect(candidate.getAttribute("aria-label")).toBe("BBC One");
    const image = candidate.querySelector<HTMLImageElement>("img")!;
    image.dispatchEvent(new Event("error"));
    expect(image.hidden).toBe(true);

    await component.stop();
  });

  it("依赖字段变化会清空旧选择和分页状态并重新查询", async () => {
    vi.useFakeTimers();
    document.body.innerHTML = `
      <form>
        <select name="country_id"><option value="uk" selected>UK</option><option value="us">US</option></select>
        <section data-om-select-src="/api/options" data-om-select-dependent-fields="country_id" data-om-select-enhance="choices">
          <select data-om-select-control data-choices><option value="bbc" selected>BBC</option></select>
        </section>
      </form>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const getJson = vi.fn().mockResolvedValue({ results: [{ id: "bbc", text: "BBC" }], more: true });
    const component = new Select(root);
    Object.assign(component.http, { getJson });
    await component.start();

    const country = document.querySelector<HTMLSelectElement>("[name='country_id']")!;
    country.value = "us";
    country.dispatchEvent(new Event("change", { bubbles: true }));
    expect(component.selectedValues()).toEqual([]);
    await vi.advanceTimersByTimeAsync(200);
    expect(getJson).toHaveBeenLastCalledWith("/api/options?page=1&depends%5Bcountry_id%5D=us", expect.anything());

    await component.stop();
    vi.useRealTimers();
  });

  it("增强下拉提供可点击的下一页入口并按 value 去重", async () => {
    document.body.innerHTML = `
      <section data-om-select-src="/api/options" data-om-select-enhance="choices">
        <select data-om-select-control data-choices></select>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Select(root);
    Object.assign(component.http, {
      getJson: vi
        .fn()
        .mockResolvedValueOnce({ results: [{ id: "a", text: "A" }], more: true })
        .mockResolvedValueOnce({ results: [{ id: "a", text: "A again" }, { id: "b", text: "B" }], more: false })
    });

    await component.start();
    const choicesList = root.querySelector<HTMLElement>(".choices__list--dropdown .choices__list")!;
    choicesList.scrollTop = 37;
    const more = root.querySelector<HTMLButtonElement>("[data-om-select-load-more]")!;
    expect(more).not.toBeNull();
    expect(more.tabIndex).toBe(0);
    more.click();
    await vi.waitFor(() => expect(Array.from(root.querySelectorAll("option")).map((option) => option.value)).toEqual(["a", "b"]));
    await vi.waitFor(() => expect(choicesList.scrollTop).toBe(37));
    expect(root.querySelector<HTMLElement>("[data-om-select-load-more]")?.hidden).toBe(true);

    await component.stop();
  });

  it("下一页失败时保留候选并提供重试", async () => {
    document.body.innerHTML = `
      <section data-om-select-src="/api/options" data-om-select-enhance="choices">
        <select data-om-select-control data-choices></select>
      </section>
    `;
    const root = document.querySelector<HTMLElement>("section")!;
    const component = new Select(root);
    Object.assign(component.http, {
      getJson: vi
        .fn()
        .mockResolvedValueOnce({ results: [{ id: "a", text: "A" }], more: true })
        .mockRejectedValueOnce(new Error("offline"))
        .mockResolvedValueOnce({ results: [{ id: "b", text: "B" }], more: false })
    });

    await component.start();
    root.querySelector<HTMLButtonElement>("[data-om-select-load-more]")!.click();
    await vi.waitFor(() => expect(root.querySelector("[data-om-select-load-more]")?.textContent).toBe("Retry"));
    expect(Array.from(root.querySelectorAll("option")).map((option) => option.value)).toEqual(["a"]);

    root.querySelector<HTMLButtonElement>("[data-om-select-load-more]")!.click();
    await vi.waitFor(() => expect(Array.from(root.querySelectorAll("option")).map((option) => option.value)).toEqual(["a", "b"]));
    await component.stop();
  });
});
