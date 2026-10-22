import { type Download, type Job, type Prepared, type Release, Reports } from "financial/native";
import {
  cleanup,
  effect,
  Input,
  type JSX,
  Scroll,
  type Signal,
  signal,
  Text,
  View,
  type YNode,
} from "nsh";
import { AlertDialog, Button as NativeButton } from "nsh/base";
import { Clipboard } from "nsh/clipboard";
import { Menu, Window } from "nsh/desktop";
import { keymap } from "nsh/keymap";
import { type Batch, batchPhaseLabel, createBatch } from "./batches";
import { readUploadClipboard, type UploadClipboard } from "./clipboard";
import {
  Button,
  Card,
  DateField,
  Field,
  Label,
  PriceField,
  palette,
  theme,
  typography,
} from "./controls";
import { Preview, type PreviewRequest } from "./Preview";

const imageCategories = [
  "国通1",
  "国通2",
  "团油",
  "货车帮",
  "滴滴加油",
  "POS",
  "超市销售收入",
  "抖音",
];
const tableCategories = [
  "油品时间统计",
  "油品优惠",
  "加油明细",
  "充值明细",
  "油品时间统计(调价后)",
  "通联",
];
const titles: Record<string, string> = { simple: "简表", daily: "日报" };
export function Workstation(
  p: {
    initialFiles?: Record<string, string[]>;
    clipboard?: UploadClipboard;
    prepare?: (job: Job) => Promise<Prepared>;
  } = {},
) {
  const sessionId = `batch-${Date.now()}`;
  let nextBatch = 1;
  const batches = signal([createBatch(`${sessionId}-1`, 1, p.initialFiles)]);
  const selectedId = signal(batches()[0].id);
  const current = () => batches().find((b) => b.id === selectedId()) || batches()[0];
  // These bindings are for synchronous view code only. Async operations capture a Batch.
  function field<T>(read: (batch: Batch) => Signal<T>): Signal<T> {
    return Object.assign(() => read(current())(), {
      set: (value: T) => read(current()).set(value),
      update: (fn: (value: T) => T) => read(current()).update(fn),
    });
  }
  const files = field((b) => b.files),
    busy = field((b) => b.busy),
    message = field((b) => b.message),
    error = field((b) => b.error),
    optionalOpen = field((b) => b.optionalOpen),
    parametersOpen = field((b) => b.parametersOpen),
    date = field((b) => b.date),
    workStart = field((b) => b.workStart),
    shiftTime = field((b) => b.shiftTime),
    gasPrice = field((b) => b.gasPrice),
    divisor = field((b) => b.divisor),
    countDivisor = field((b) => b.countDivisor),
    balance = field((b) => b.balance),
    results = field((b) => b.results),
    progress = field((b) => b.progress);
  const page = signal("home");
  const anyBusy = () => batches().some((b) => b.busy());
  const queue: { batch: Batch; jobs: Job[] }[] = [];
  const running = signal(false);
  const apiKey = signal(""),
    apiBase = signal("https://generativelanguage.googleapis.com"),
    model = signal("gemini-2.0-flash");
  const preview = signal<PreviewRequest | null>(null);
  const settingsMessage = signal("");
  const logs = signal(""),
    release = signal<Release | null>(null),
    updateMessage = signal(""),
    checking = signal(false),
    downloading = signal(false),
    download = signal<Download | null>(null);
  let cursor = 0,
    logScroll: YNode | undefined,
    hoverCategory = "",
    alive = true;
  function fail(e: unknown, batch = current()) {
    const text = e instanceof Error ? e.message : String(e);
    batch.error.set(text);
    Reports.logError(`[${batch.id}] ${text}`);
  }
  effect(() => Reports.setBusy(anyBusy() || downloading()));
  function setBusy(value: boolean, batch = current()) {
    batch.busy.set(value);
  }
  function invalidate(batch = current()) {
    for (const r of Object.values(batch.results())) Reports.discard(r.id);
    batch.results.set({});
    batch.progress.set([]);
    Reports.begin(batch.id);
    batch.message.set("");
    batch.error.set("");
    batch.phase.set("draft");
  }
  function switchBatch(batch: Batch) {
    preview.set(null);
    hoverCategory = "";
    selectedId.set(batch.id);
  }
  function newBatch() {
    if (downloading()) return;
    const number = ++nextBatch;
    const batch = createBatch(`${sessionId}-${number}`, number);
    batches.update((items) => [...items, batch]);
    switchBatch(batch);
  }
  async function closeBatch(batch: Batch) {
    if (batch.busy() || downloading()) return;
    const hasContents =
      Object.values(batch.files()).some((paths) => paths.length) ||
      Object.keys(batch.results()).length > 0;
    if (hasContents) {
      const choice = await AlertDialog.show({
        title: "关闭加油站",
        description: `关闭「${batch.name()}」并清理该加油站的文件选择和结果？原始文件会保留。`,
        actions: [
          { label: "取消", role: "cancel", id: "cancel" },
          { label: "关闭加油站", role: "destructive", id: "close" },
        ],
      });
      if (choice !== "close") return;
    }
    if (batch.busy() || downloading() || !alive || !batches().includes(batch)) return;
    Reports.reset(batch.id);
    const index = batches().indexOf(batch);
    const remaining = batches().filter((b) => b !== batch);
    if (!remaining.length) {
      const number = ++nextBatch;
      remaining.push(createBatch(`${sessionId}-${number}`, number));
    }
    if (selectedId() === batch.id) switchBatch(remaining[Math.min(index, remaining.length - 1)]);
    batches.set(remaining);
  }
  function change(set: (v: string) => void, value: string) {
    if (busy() || downloading()) return;
    invalidate();
    set(value);
  }
  function refresh() {
    try {
      const activity = Reports.activity(cursor);
      cursor = activity.cursor;
      for (const batch of batches()) {
        batch.progress.set(activity.progress.filter((item) => item.batchId === batch.id));
      }
      if (activity.logs) {
        logs.set((logs() + activity.logs).slice(-100000));
        if (page() === "logs") logScroll?.scrollTo({ y: 10000000, animated: false });
      }
      if (downloading()) download.set(Reports.updateProgress());
    } catch (e) {
      error.set(String(e));
    }
  }
  try {
    const p = Reports.preferences();
    theme.set(p.theme);
    apiKey.set(p.apiKey);
    apiBase.set(p.apiBase);
    model.set(p.model);
  } catch (e) {
    fail(e);
  }
  refresh();
  const poll = setInterval(refresh, 1000);
  cleanup(() => {
    alive = false;
    clearInterval(poll);
    queue.splice(0);
    for (const batch of batches()) {
      if (!batch.busy() || batch.phase() === "queued") Reports.reset(batch.id);
    }
    if (!anyBusy() && !downloading()) Reports.setBusy(false);
  });
  async function checkUpdate(manual = false) {
    if (checking() || downloading()) return;
    checking.set(true);
    if (manual) updateMessage.set("正在检查更新…");
    try {
      const r = await Reports.checkUpdate();
      if (!alive) return;
      release.set(r);
      updateMessage.set(r.available ? `发现新版本 ${r.version}` : "当前已是最新版本");
    } catch {
      if (alive) {
        Reports.logError("检查更新失败");
        if (manual) updateMessage.set("检查更新失败，请检查网络后重试。");
      }
    } finally {
      if (alive) checking.set(false);
    }
  }
  const checkTimer = setTimeout(() => {
    if (Reports.autoCheckUpdate()) checkUpdate();
  }, 3000);
  cleanup(() => clearTimeout(checkTimer));
  function saveSettings() {
    try {
      Reports.savePreferences({
        theme: theme(),
        apiKey: apiKey(),
        apiBase: apiBase(),
        model: model(),
      });
      settingsMessage.set("设置已保存");
    } catch (e) {
      fail(e);
    }
  }
  function changeTheme(value: string) {
    theme.set(value);
    saveSettings();
  }
  effect(() =>
    Menu.setApplicationMenu([
      {
        label: "站务报表",
        submenu: [
          { role: "about" },
          { type: "separator" },
          {
            label: "退出",
            shortcut: "mod+q",
            disabled: anyBusy() || downloading(),
            onSelect: () => {
              if (anyBusy() || downloading()) return;
              for (const batch of batches()) Reports.reset(batch.id);
              Window.close();
            },
          },
        ],
      },
      {
        label: "编辑",
        submenu: [
          { role: "undo" },
          { role: "redo" },
          { type: "separator" },
          { role: "cut" },
          { role: "copy" },
          { role: "paste" },
          { role: "selectAll" },
        ],
      },
      {
        label: "设置",
        submenu: [
          { label: "浅色主题", checked: theme() === "light", onSelect: () => changeTheme("light") },
          { label: "深色主题", checked: theme() === "dark", onSelect: () => changeTheme("dark") },
          { label: "识别设置", onSelect: () => page.set("settings") },
          { label: "日志", onSelect: () => page.set("logs") },
          {
            label: "检查更新",
            onSelect: () => {
              page.set("settings");
              checkUpdate(true);
            },
          },
        ],
      },
    ]),
  );
  cleanup(() => Menu.setApplicationMenu(null));
  function categoryKind(category: string) {
    return imageCategories.includes(category)
      ? "image"
      : category.endsWith("模板")
        ? "template"
        : "table";
  }
  async function addTo(batch: Batch, category: string, paths: string[]) {
    if (!paths.length) return;
    const kind = categoryKind(category);
    if (kind !== "image" && paths.length > 1) throw new Error("每个表格位置请选择一个文件。");
    const validated: string[] = [];
    for (const path of paths) validated.push(await Reports.validateFile(path, kind));
    if (!alive) return;
    invalidate(batch);
    batch.files.update((f) => ({
      ...f,
      [category]: kind === "image" ? [...(f[category] || []), ...validated] : validated,
    }));
  }
  async function upload(category: string, read: (batch: Batch) => Promise<string[]>) {
    const batch = current();
    if (batch.busy() || downloading()) return;
    setBusy(true, batch);
    try {
      const paths = await read(batch);
      await addTo(batch, category, paths);
    } catch (e) {
      if (alive) fail(e, batch);
    } finally {
      setBusy(false, batch);
      if (!alive) Reports.reset(batch.id);
    }
  }
  function add(category: string, paths: string[]) {
    return upload(category, async () => paths);
  }
  function choose(category: string) {
    return upload(category, async () => {
      const path = await Reports.pickFile(categoryKind(category));
      return path ? [path] : [];
    });
  }
  function paste(category: string) {
    return upload(category, async (batch) => {
      const content = await readUploadClipboard(
        p.clipboard || Clipboard,
        categoryKind(category) === "image",
      );
      if (!content) throw new Error("请先复制文件或截图，再粘贴到对应位置。");
      return "paths" in content
        ? content.paths
        : [await Reports.pasteImage(content.image, batch.id)];
    });
  }
  keymap.bind("mod+v", () => {
    if (page() === "home" && hoverCategory) paste(hoverCategory);
  });
  keymap.bind(
    "ctrl+v",
    () => {
      if (page() === "home" && hoverCategory) paste(hoverCategory);
    },
    { when: "notEditing" },
  );
  function remove(category: string, index?: number) {
    if (busy() || downloading()) return;
    invalidate();
    files.update((f) => ({
      ...f,
      [category]: index === undefined ? [] : (f[category] || []).filter((_, i) => i !== index),
    }));
  }
  function showPreview(category: string, index = 0) {
    const paths = files()[category] || [];
    if (paths.length)
      preview.set({ paths, index, image: categoryKind(category) === "image", title: category });
  }
  const sourceStatus = (category: string, path: string) =>
    progress().find((p) => p.category === category && p.path === path);
  const uploadedCount = () => Object.values(files()).reduce((sum, paths) => sum + paths.length, 0);
  function uploadSummary() {
    const daily = !!files().日报模板?.length;
    const simple = !!files().简表模板?.length;
    const prefix = `已上传 ${uploadedCount()} 个文件`;
    if (!daily && !simple) return `${prefix} · 请选择日报或简表模板`;
    const missing = ["油品时间统计", "加油明细", "充值明细"].filter(
      (category) => !files()[category]?.length,
    );
    if (daily && !files().油品优惠?.length) missing.push("油品优惠（日报）");
    return `${prefix} · ${missing.length ? `还缺：${missing.join("、")}` : "必填表格已齐，可以开始处理"}`;
  }
  function Section(p: { title: string; children: JSX.Element }) {
    return (
      <View style={{ gap: 8 }}>
        <Text style={{ ...typography.section, color: palette().ink }}>{p.title}</Text>
        {p.children}
      </View>
    );
  }
  function UploadGrid(p: { categories: string[]; templates?: boolean }) {
    const width = signal(0);
    const columns = () =>
      p.templates ? (width() >= 468 ? 2 : 1) : width() >= 948 ? 4 : width() >= 468 ? 2 : 1;
    return (
      <View
        onLayout={(e) => width.set(e.size.width)}
        style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, alignItems: "flex-start" }}
      >
        {p.categories.map((category) => (
          <View
            style={{
              width: width() > 0 ? Math.floor((width() - (columns() - 1) * 8) / columns()) : "100%",
            }}
          >
            <Slot category={category} />
          </View>
        ))}
      </View>
    );
  }
  function Slot(p: { category: string }) {
    const dragging = signal(false),
      expanded = signal(false);
    const paths = () => files()[p.category] || [];
    const isImage = imageCategories.includes(p.category);
    const failures = () =>
      paths().filter((path) => sourceStatus(p.category, path)?.status === "失败");
    const status = () => {
      if (failures().length) return `${failures().length} 个失败 · 展开查看`;
      const active = paths()
        .map((path) => sourceStatus(p.category, path)?.status)
        .filter(Boolean);
      if (active.length) return [...new Set(active)].join(" / ");
      if (paths().length) return "已上传";
      if (["油品时间统计", "加油明细", "充值明细"].includes(p.category)) return "必填";
      if (p.category === "油品优惠") return files().日报模板?.length ? "日报必填" : "可选";
      return p.category.endsWith("模板") ? "按需选择" : "可选";
    };
    return (
      <View
        testID={`slot-${p.category}`}
        onHoverIn={() => {
          hoverCategory = p.category;
        }}
        onHoverOut={() => {
          if (hoverCategory === p.category) hoverCategory = "";
        }}
        onFileDragEnter={() => dragging.set(true)}
        onFileDragLeave={() => dragging.set(false)}
        onFileDrop={(e) => {
          dragging.set(false);
          add(p.category, e.uris);
        }}
        style={{
          padding: 8,
          gap: 6,
          borderWidth: 1,
          borderColor: dragging()
            ? palette().green
            : failures().length
              ? palette().error
              : palette().line,
          borderRadius: 8,
          backgroundColor: palette().card,
        }}
      >
        <NativeButton
          testID={`upload-${p.category}`}
          accessibilityLabel={`${paths().length ? (isImage ? "添加" : "替换") : "上传"}${p.category}`}
          disabled={busy()}
          onPress={() => choose(p.category)}
          style={{ padding: 4, gap: 5, borderRadius: 4 }}
          hoverStyle={{ backgroundColor: palette().button }}
          disabledStyle={{ opacity: 0.5 }}
        >
          <View style={{ flexDirection: "row", gap: 6, alignItems: "center" }}>
            <Text numberOfLines={1} style={{ flex: 1, ...typography.item, color: palette().ink }}>
              {p.category}
            </Text>
            <Text
              style={{
                fontSize: 12,
                color: failures().length
                  ? palette().error
                  : paths().length
                    ? palette().green
                    : palette().muted,
              }}
            >
              {status()}
            </Text>
          </View>
          <Text
            numberOfLines={1}
            ellipsizeMode="middle"
            style={{ ...typography.file, color: palette().muted }}
          >
            {paths().length
              ? isImage
                ? `${paths().length} 张图片 · 点击继续添加`
                : Reports.fileName(paths()[0])
              : "+ 点击上传或拖入文件"}
          </Text>
        </NativeButton>
        <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
          <Button quiet compact disabled={busy()} onPress={() => paste(p.category)}>
            粘贴
          </Button>
          <If when={!!paths().length}>
            <Button quiet compact onPress={() => showPreview(p.category)}>
              预览
            </Button>
            <Button
              quiet
              compact
              testID={`manage-${p.category}`}
              onPress={() => expanded.set(!expanded())}
            >
              {expanded() ? "收起" : isImage ? "管理" : "详情"}
            </Button>
            <If when={!isImage}>
              <Button quiet compact disabled={busy()} onPress={() => remove(p.category)}>
                移除
              </Button>
            </If>
          </If>
        </View>
        <If when={expanded() && !!paths().length}>
          <Each of={paths()}>
            {(path, index) => (
              <View
                style={{ gap: 5, paddingTop: 6, borderTopWidth: 1, borderColor: palette().line }}
              >
                <Text selectable style={{ ...typography.file, color: palette().ink }}>
                  {Reports.fileName(path())}
                </Text>
                <Text
                  selectable
                  style={{
                    fontSize: 12,
                    color:
                      sourceStatus(p.category, path())?.status === "失败"
                        ? palette().error
                        : palette().muted,
                  }}
                >
                  {sourceStatus(p.category, path())?.detail ||
                    sourceStatus(p.category, path())?.status ||
                    "等待处理"}
                </Text>
                <If when={isImage}>
                  <View style={{ flexDirection: "row", gap: 6 }}>
                    <Button quiet compact onPress={() => showPreview(p.category, index())}>
                      预览此图
                    </Button>
                    <Button
                      quiet
                      compact
                      disabled={busy()}
                      onPress={() => remove(p.category, index())}
                    >
                      移除
                    </Button>
                  </View>
                </If>
              </View>
            )}
          </Each>
          <If when={isImage}>
            <Button quiet compact disabled={busy()} onPress={() => remove(p.category)}>
              清除全部
            </Button>
          </If>
        </If>
      </View>
    );
  }
  function calculate() {
    const batch = current();
    if (batch.busy() || downloading()) return;
    invalidate(batch);
    const kinds = ["daily", "simple"].filter((k) => batch.files()[`${titles[k]}模板`]?.length);
    if (!kinds.length) {
      fail("请先选择简表模板或日报模板。", batch);
      return;
    }
    const jobs = kinds.map((kind): Job => {
      const allowed =
        kind === "simple" ? tableCategories.slice(0, 4) : [...tableCategories, ...imageCategories];
      return {
        batchId: batch.id,
        kind,
        template: batch.files()[`${titles[kind]}模板`][0],
        files: Object.entries(batch.files())
          .filter(([k]) => allowed.includes(k))
          .flatMap(([category, paths]) => paths.map((path) => ({ category, path }))),
        date: batch.date(),
        workStart: batch.workStart(),
        shiftTime: batch.shiftTime(),
        gasPrice: batch.gasPrice(),
        divisor: batch.divisor(),
        countDivisor: batch.countDivisor(),
        balance: batch.balance(),
        apiKey: apiKey(),
        apiBase: apiBase(),
        model: model(),
      };
    });
    batch.busy.set(true);
    batch.phase.set("queued");
    batch.message.set("已加入队列，可以添加或切换加油站继续上传。");
    queue.push({ batch, jobs });
    void drainQueue();
  }
  function cancelQueued() {
    const batch = current();
    const index = queue.findIndex((item) => item.batch === batch);
    if (index < 0) return;
    queue.splice(index, 1);
    batch.busy.set(false);
    batch.phase.set("draft");
    batch.message.set("已取消排队，文件保留，可以继续修改。");
  }
  async function drainQueue() {
    if (running()) return;
    running.set(true);
    try {
      while (alive && queue.length) {
        const item = queue.shift();
        if (!item) break;
        const { batch, jobs } = item;
        batch.phase.set("running");
        const completed: Record<string, Prepared> = {},
          errors: string[] = [];
        try {
          for (const job of jobs) {
            if (!alive) break;
            batch.message.set(`正在生成${titles[job.kind]}… 可添加其他加油站继续上传。`);
            try {
              const result = await (p.prepare || Reports.prepare)(job);
              if (!alive) {
                Reports.discard(result.id);
                break;
              }
              completed[job.kind] = result;
            } catch (e) {
              errors.push(`${titles[job.kind]}：${String(e)}`);
            }
            batch.results.set({ ...completed });
            if (alive) refresh();
          }
          batch.message.set(
            Object.keys(completed).length
              ? "处理完成，可预览或导出表格。"
              : "处理失败，请查看日志。",
          );
          batch.error.set(errors.join("\n"));
          batch.phase.set(
            errors.length ? (Object.keys(completed).length ? "partial" : "failed") : "done",
          );
        } finally {
          batch.busy.set(false);
          if (!alive) Reports.reset(batch.id);
        }
      }
    } finally {
      running.set(false);
      if (alive) refresh();
      else Reports.setBusy(false);
    }
  }
  async function save(kind: string) {
    const batch = current();
    const result = batch.results()[kind];
    if (!result || batch.busy() || downloading()) return;
    batch.busy.set(true);
    batch.error.set("");
    try {
      const dest = await Reports.export(result.id, kind);
      if (dest && alive) batch.message.set(`已导出：${dest}`);
    } catch (e) {
      if (alive) fail(e, batch);
    } finally {
      batch.busy.set(false);
      if (!alive) Reports.reset(batch.id);
    }
  }
  function previewResult(kind: string) {
    try {
      preview.set({
        paths: [Reports.outputPath(results()[kind].id)],
        index: 0,
        image: false,
        title: `${titles[kind]}结果`,
      });
    } catch (e) {
      fail(e);
    }
  }
  async function reset() {
    const batch = current();
    if (batch.busy()) return;
    const choice = await AlertDialog.show({
      title: "重置当前加油站",
      description: `清除「${batch.name()}」的文件和处理结果？其他加油站和原始文件会保留。`,
      actions: [
        { label: "取消", role: "cancel", id: "cancel" },
        { label: "确认重置", role: "destructive", id: "reset" },
      ],
    });
    if (choice !== "reset" || batch.busy() || !alive) return;
    invalidate(batch);
    Reports.reset(batch.id);
    batch.files.set({});
    batch.optionalOpen.set(false);
    batch.parametersOpen.set(false);
    batch.balance.set("");
    if (current() === batch) preview.set(null);
    batch.message.set("已重置当前加油站的文件和处理结果。");
  }
  async function downloadUpdate() {
    if (downloading() || anyBusy()) return;
    downloading.set(true);
    updateMessage.set("正在下载更新…");
    try {
      await Reports.downloadUpdate();
      download.set(Reports.updateProgress());
      updateMessage.set("下载完成，可以安装更新。");
    } catch (e) {
      updateMessage.set(String(e));
    } finally {
      downloading.set(false);
    }
  }
  function installUpdate() {
    if (anyBusy() || downloading()) return;
    try {
      if (Reports.installUpdate()) {
        for (const batch of batches()) Reports.reset(batch.id);
        Window.close();
      }
    } catch (e) {
      updateMessage.set(String(e));
    }
  }
  function CurrentPreview() {
    const request = preview();
    if (!request) return null;
    return <Preview request={request} onClose={() => preview.set(null)} onError={fail} />;
  }
  return (
    <View style={{ flex: 1, backgroundColor: palette().bg }}>
      <View
        style={{
          paddingHorizontal: 24,
          paddingVertical: 14,
          flexDirection: "row",
          gap: 12,
          alignItems: "center",
          borderBottomWidth: 1,
          borderColor: palette().line,
          backgroundColor: palette().card,
        }}
      >
        <Text style={{ ...typography.title, color: palette().ink }}>站务报表</Text>
        <View style={{ flex: 1 }} />
        {[
          ["home", "首页"],
          ["logs", "日志"],
          ["settings", "设置"],
        ].map(([value, label]) => (
          <Button
            primary={page() === value}
            onPress={() => {
              page.set(value);
              if (value === "logs")
                setTimeout(() => logScroll?.scrollTo({ y: 10000000, animated: false }), 30);
            }}
          >
            {label}
          </Button>
        ))}
      </View>
      <If when={page() === "home"}>
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 8,
            paddingHorizontal: 20,
            paddingVertical: 8,
            backgroundColor: palette().card,
            borderBottomWidth: 1,
            borderColor: palette().line,
          }}
        >
          <Scroll
            horizontal
            style={{ flex: 1, height: 34 }}
            contentStyle={{ flexDirection: "row", alignItems: "center", gap: 6 }}
          >
            <Each of={batches()}>
              {(batch) => (
                <View
                  style={{
                    flexDirection: "row",
                    alignItems: "center",
                    borderRadius: 6,
                    backgroundColor: current() === batch() ? palette().button : palette().card,
                  }}
                >
                  <NativeButton
                    testID={`batch-${batch().number}`}
                    accessibilityLabel={`切换${batch().name()}`}
                    onPress={() => switchBatch(batch())}
                    style={{
                      paddingHorizontal: 10,
                      paddingVertical: 7,
                      borderRadius: 6,
                      backgroundColor: current() === batch() ? palette().button : palette().card,
                    }}
                    hoverStyle={{ opacity: 0.8 }}
                  >
                    <Text
                      numberOfLines={1}
                      style={{
                        maxWidth: 220,
                        fontSize: 13,
                        fontWeight: current() === batch() ? "500" : "400",
                        color:
                          batch().phase() === "failed" || batch().phase() === "partial"
                            ? palette().error
                            : palette().ink,
                      }}
                    >
                      {`${batch().name() || `加油站 ${batch().number}`} · ${batchPhaseLabel[batch().phase()]}`}
                    </Text>
                  </NativeButton>
                  <NativeButton
                    testID={`close-batch-${batch().number}`}
                    accessibilityLabel={`关闭${batch().name() || `加油站 ${batch().number}`}`}
                    disabled={batch().busy() || downloading()}
                    onPress={() => closeBatch(batch())}
                    style={{
                      width: 30,
                      height: 30,
                      alignItems: "center",
                      justifyContent: "center",
                      borderRadius: 6,
                    }}
                    hoverStyle={{ backgroundColor: palette().button }}
                    disabledStyle={{ opacity: 0.35 }}
                  >
                    <Text style={{ fontSize: 18, fontWeight: "400", color: palette().muted }}>
                      ×
                    </Text>
                  </NativeButton>
                </View>
              )}
            </Each>
          </Scroll>
          <Button testID="new-batch" compact disabled={downloading()} onPress={newBatch}>
            ＋ 添加加油站
          </Button>
        </View>
        <Scroll testID="home-scroll" style={{ flex: 1 }} contentStyle={{ padding: 20, gap: 16 }}>
          <View style={{ gap: 8 }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <Label>当前加油站</Label>
              <Input
                testID="batch-name"
                accessibilityLabel="加油站名称"
                value={current().name()}
                readonly={busy()}
                onChange={(value) => current().name.set(value)}
                placeholder="填写加油站名称"
                style={{
                  width: 240,
                  fontSize: 14,
                  paddingHorizontal: 8,
                  paddingVertical: 5,
                  borderBottomWidth: 1,
                  borderColor: palette().line,
                  color: palette().ink,
                }}
              />
              <Text testID="batch-status" style={{ fontSize: 12, color: palette().muted }}>
                {batchPhaseLabel[current().phase()]}
              </Text>
              <View style={{ flex: 1 }} />
            </View>

            <View style={{ flexDirection: "row", gap: 14, flexWrap: "wrap" }}>
              <DateField
                label="表格日期"
                testID="date"
                value={date()}
                onChange={(v) => change((next) => date.set(next), v)}
                disabled={busy()}
              />
              <DateField
                label="上班时间"
                testID="work-start"
                value={workStart()}
                onChange={(v) => change((next) => workStart.set(next), v)}
                disabled={busy()}
                withTime
              />
              <DateField
                label="交班时间"
                testID="shift-time"
                value={shiftTime()}
                onChange={(v) => change((next) => shiftTime.set(next), v)}
                disabled={busy()}
                withTime
              />
              <PriceField
                value={gasPrice()}
                onChange={(v) => {
                  if (v !== gasPrice()) change((next) => gasPrice.set(next), v);
                }}
                disabled={busy()}
              />
            </View>
          </View>
          <Section title="输出模板">
            <UploadGrid categories={["日报模板", "简表模板"]} templates />
          </Section>
          <Section title="源表">
            <UploadGrid categories={tableCategories.slice(0, 4)} />
          </Section>
          <Section title="平台截图（可选）">
            <UploadGrid categories={imageCategories} />
          </Section>
          <Label>文件可拖入对应位置；截图可添加多张，鼠标移到上传块后按 Ctrl / ⌘ + V 粘贴。</Label>
          <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
            <Button
              testID="optional-toggle"
              compact
              onPress={() => optionalOpen.set(!optionalOpen())}
            >
              {`${optionalOpen() ? "收起" : "展开"}其他表格 · 调价后统计、通联${tableCategories.slice(4).some((c) => files()[c]?.length) ? `（已上传 ${tableCategories.slice(4).reduce((n, c) => n + (files()[c]?.length || 0), 0)}）` : ""}`}
            </Button>
            <If when={!!files().简表模板?.length}>
              <Button
                testID="parameters-toggle"
                compact
                onPress={() => parametersOpen.set(!parametersOpen())}
              >
                {`${parametersOpen() ? "收起" : "展开"}简表参数${balance() ? "（已填期末余额）" : ""}`}
              </Button>
            </If>
          </View>
          <If when={optionalOpen()}>
            <UploadGrid categories={tableCategories.slice(4)} templates />
          </If>
          <If when={!!files().简表模板?.length && parametersOpen()}>
            <Section title="简表参数">
              <View style={{ flexDirection: "row", gap: 14, flexWrap: "wrap" }}>
                <Field
                  label="金额 / 升数除数"
                  value={divisor()}
                  onChange={(v) => change((next) => divisor.set(next), v)}
                  disabled={busy()}
                />
                <Field
                  label="次数除数"
                  value={countDivisor()}
                  onChange={(v) => change((next) => countDivisor.set(next), v)}
                  disabled={busy()}
                />
                <Field
                  testID="balance"
                  label="期末余额合计（可选）"
                  value={balance()}
                  onChange={(v) => change((next) => balance.set(next), v)}
                  disabled={busy()}
                />
              </View>
            </Section>
          </If>
        </Scroll>
        <View
          style={{
            paddingHorizontal: 24,
            paddingVertical: 14,
            gap: 10,
            borderTopWidth: 1,
            borderColor: palette().line,
            backgroundColor: palette().card,
          }}
        >
          <Text testID="upload-summary" style={{ fontSize: 12, color: palette().muted }}>
            {uploadSummary()}
          </Text>
          <If when={!!error()}>
            <Text testID="error" selectable style={{ fontSize: 13, color: palette().error }}>
              {error()}
            </Text>
          </If>
          <If when={!!message()}>
            <Text testID="message" selectable style={{ fontSize: 13, color: palette().green }}>
              {message()}
            </Text>
          </If>
          <View style={{ flexDirection: "row", gap: 10, flexWrap: "wrap" }}>
            <Button
              testID="calculate"
              primary
              disabled={busy() || downloading()}
              onPress={calculate}
            >
              {current().phase() === "queued"
                ? "排队中…"
                : busy()
                  ? "正在处理…"
                  : running()
                    ? "加入处理队列"
                    : "生成报表"}
            </Button>
            <If when={current().phase() === "queued"}>
              <Button onPress={cancelQueued}>取消排队</Button>
            </If>
            <Button disabled={busy() || !results().daily} onPress={() => save("daily")}>
              导出日报
            </Button>
            <Button disabled={busy() || !results().simple} onPress={() => save("simple")}>
              导出简表
            </Button>
            <If when={!!results().daily}>
              <Button onPress={() => previewResult("daily")}>预览日报</Button>
            </If>
            <If when={!!results().simple}>
              <Button onPress={() => previewResult("simple")}>预览简表</Button>
            </If>
            <View style={{ flex: 1 }} />
            <Button disabled={busy()} onPress={reset}>
              重置当前加油站
            </Button>
          </View>
        </View>
      </If>
      <If when={page() === "logs"}>
        <View style={{ flex: 1, padding: 24, gap: 14 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
            <Text style={{ fontSize: 20, fontWeight: "600", color: palette().ink }}>运行日志</Text>
            <View style={{ flex: 1 }} />
            <Button
              onPress={() => {
                try {
                  cursor = Reports.activity(cursor).cursor;
                  logs.set("");
                } catch (e) {
                  fail(e);
                }
              }}
            >
              清除日志
            </Button>
            <Button onPress={() => Clipboard.writeText(logs())}>复制日志</Button>
          </View>
          <Scroll
            testID="log-scroll"
            ref={logScroll}
            style={{ flex: 1, backgroundColor: "#16221C", borderRadius: 8 }}
            contentStyle={{ padding: 16 }}
          >
            <Text
              testID="logs"
              selectable
              style={{ fontFamily: "monospace", fontSize: 12, lineHeight: 20, color: "#DCEBDD" }}
            >
              {logs() || "暂无日志"}
            </Text>
          </Scroll>
        </View>
      </If>
      <If when={page() === "settings"}>
        <Scroll style={{ flex: 1 }} contentStyle={{ padding: 24, gap: 18 }}>
          <Card title="外观">
            <View style={{ flexDirection: "row", gap: 10 }}>
              <Button primary={theme() === "light"} onPress={() => changeTheme("light")}>
                浅色主题
              </Button>
              <Button primary={theme() === "dark"} onPress={() => changeTheme("dark")}>
                深色主题
              </Button>
            </View>
          </Card>
          <Card title="图片识别设置">
            <If when={!!settingsMessage()}>
              <Label>{settingsMessage()}</Label>
            </If>
            <Label>上传的平台截图通过此服务识别。Excel 文件在本机处理。</Label>
            <Field
              label="Gemini API 地址"
              value={apiBase()}
              onChange={(v) => apiBase.set(v)}
              disabled={busy()}
            />
            <Field
              label="Gemini API Key"
              testID="api-key"
              value={apiKey()}
              onChange={(v) => apiKey.set(v)}
              disabled={busy()}
              masked
            />
            <Field
              label="模型名称"
              value={model()}
              onChange={(v) => model.set(v)}
              disabled={busy()}
            />
            <Label>兼容原有环境变量及 .env 配置；环境变量和 .env 优先于此处保存的设置。</Label>
            <Button disabled={busy()} primary onPress={saveSettings}>
              保存设置
            </Button>
            <If when={!!message()}>
              <Text style={{ color: palette().green }}>{message()}</Text>
            </If>
            <If when={!!error()}>
              <Text style={{ color: palette().error }}>{error()}</Text>
            </If>
          </Card>
          <Card title="版本与更新">
            <Label>{`当前版本 ${Reports.version()}`}</Label>
            <Button disabled={checking() || downloading()} onPress={() => checkUpdate(true)}>
              {checking() ? "检查中…" : "检查更新"}
            </Button>
            <Text style={{ fontSize: 13, color: palette().ink }}>{updateMessage()}</Text>
            <If when={!!release()?.available}>
              <Text selectable style={{ fontSize: 13, color: palette().ink }}>
                {release()?.notes || ""}
              </Text>
              <If when={!release()?.downloadable}>
                <Label>该版本尚无适用于当前系统的安装包。</Label>
              </If>
              <If when={!!release()?.downloadable}>
                <Button disabled={anyBusy() || downloading()} onPress={downloadUpdate}>
                  下载更新
                </Button>
              </If>
            </If>
            <If when={downloading()}>
              <Label>{`已下载 ${Math.round(Number(download()?.received || 0) / 1024 / 1024)} MB / ${Math.round(Number(download()?.total || 0) / 1024 / 1024)} MB`}</Label>
              <Button onPress={() => Reports.cancelUpdate()}>取消下载</Button>
            </If>
            <If when={!!download()?.ready && !downloading()}>
              <Button disabled={anyBusy() || downloading()} primary onPress={installUpdate}>
                安装更新
              </Button>
            </If>
          </Card>
        </Scroll>
      </If>
      <If when={!!release()?.available && page() !== "settings"}>
        <View
          style={{
            padding: 12,
            flexDirection: "row",
            gap: 12,
            alignItems: "center",
            backgroundColor: palette().button,
          }}
        >
          <Text
            style={{ flex: 1, color: palette().ink, fontSize: 13 }}
          >{`发现新版本 ${release()?.version}`}</Text>
          <Button onPress={() => page.set("settings")}>查看更新</Button>
        </View>
      </If>
      <If when={!!preview()}>
        <CurrentPreview />
      </If>
    </View>
  );
}
