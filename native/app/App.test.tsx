import { Reports } from "financial/native";
import { expect, open, test } from "nsh/test";
import { readUploadClipboard } from "./clipboard";

const options = { width: 1200, height: 900, platform: "macos" as const };

test("date-time pickers edit all time parts and cancel without changing the value", async () => {
  const app = await open("./fixtures/Empty.tsx", options);
  for (const field of ["work-start", "shift-time"]) {
    const initial = String(app.value(`id:${field}`));
    const date = `${initial.slice(0, 8)}01`;
    const [hour, minute, second] = initial.slice(11).split(":").map(Number);
    const expected = `${date} ${[(hour + 1) % 24, (minute + 1) % 60, (second + 1) % 60].map((v) => String(v).padStart(2, "0")).join(":")}`;
    await app.press(`id:${field}-calendar`);
    await app.waitFor(`id:${field}-hours`);
    expect(app.value(`id:${field}-hours`)).toBe(initial.slice(11, 13));
    await app.press(`label:${Number(date.slice(0, 4))}-${Number(date.slice(5, 7))}-1`);
    await app.press("label:增加时");
    await app.press("label:增加分");
    await app.press("label:增加秒");
    await app.press("确定");
    await app.waitFor(`id:${field}-hours`, { state: "gone" });
    expect(app.value(`id:${field}`)).toBe(expected);
    await app.press(`id:${field}-calendar`);
    await app.waitFor(`id:${field}-hours`);
    await app.clear(`id:${field}-hours`);
    await app.type(`id:${field}-hours`, "24");
    expect(app.enabled("确定")).toBe(false);
    await app.press("取消");
    await app.waitFor(`id:${field}-hours`, { state: "gone" });
    expect(app.value(`id:${field}`)).toBe(expected);
    await app.press(`id:${field}-calendar`);
    await app.waitFor(`id:${field}-hours`);
    expect(app.value(`id:${field}-hours`)).toBe(expected.slice(11, 13));
    await app.keyboard.press("escape");
    await app.waitFor(`id:${field}-hours`, { state: "gone" });
    expect(app.value(`id:${field}`)).toBe(expected);
  }
}, 60000);

test("API key visibility toggles without changing the key", async () => {
  const app = await open("./fixtures/Empty.tsx", options);
  await app.press("设置");
  await app.waitFor("id:api-key");
  await app.clear("id:api-key");
  await app.type("id:api-key", "ui-test-key");
  await app.press("label:显示 Gemini API Key");
  expect(app.shows("label:隐藏 Gemini API Key")).toBe(true);
  expect(app.value("id:api-key")).toBe("ui-test-key");
  await app.press("label:隐藏 Gemini API Key");
  expect(app.shows("label:显示 Gemini API Key")).toBe(true);
  expect(app.value("id:api-key")).toBe("ui-test-key");
});

test("original date, time and price controls are present before uploading", async () => {
  const app = await open("./fixtures/Empty.tsx", options);
  expect(app.value("id:date")).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  expect(app.value("id:work-start")).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
  expect(app.value("id:shift-time")).toMatch(/^\d{4}-\d{2}-\d{2} /);
  expect(app.value("id:gas-price")).toBe("8.23");
  expect(app.shows("填写规则")).toBe(false);
  await app.press("id:date-calendar");
  await app.press("今天");
  await app.press("id:calculate");
  await app.waitFor("请先选择简表模板或日报模板。");
  await app.press("日志");
  await app.waitFor("text:/请选择|请先选择/");
  await app.press("清除日志");
  expect(app.shows("暂无日志")).toBe(true);
  await app.press("设置");
  expect(app.shows("Gemini API Key")).toBe(true);
  await app.press("深色主题");
  await app.waitFor("设置已保存");
  await app.press("浅色主题");
});

test("invalid uploads are rejected immediately and logged", async () => {
  const app = await open("./fixtures/Clipboard.tsx", {
    ...options,
    clipboard: "/missing/template.xlsx",
  });
  await app.press("id:slot-简表模板 >> text:粘贴");
  await app.waitFor("text:/文件不存在/");
  expect(app.shows("text:template.xlsx")).toBe(false);
  expect(app.enabled("id:calculate")).toBe(true);
  await app.press("日志");
  await app.waitFor("text:/文件不存在/");
});

test("multiple receipts append, preview together, remove individually, reset safely", async () => {
  const path = "./native/app/fixtures/receipt.png";
  const app = await open("./fixtures/Clipboard.tsx", { ...options, clipboard: path });
  await app.press("id:slot-国通1 >> text:粘贴");
  await app.waitFor("text:1 张图片 · 点击继续添加");
  await app.press("id:slot-国通1 >> text:粘贴");
  await app.waitFor("text:2 张图片 · 点击继续添加");
  await app.press("id:manage-国通1");
  expect(app.count("id:slot-国通1 >> text:receipt.png")).toBe(2);
  await app.press("id:slot-国通1 >> text:预览 >> nth=0");
  await app.waitFor("text:1 / 2");
  await app.press("下一张");
  await app.waitFor("text:2 / 2");
  await app.press("关闭预览");
  await app.press("id:slot-国通1 >> text:移除 >> nth=0");
  expect(app.count("id:slot-国通1 >> text:receipt.png")).toBe(1);
  app.onDialog(() => "取消");
  await app.press("重置当前加油站");
  expect(app.count("id:slot-国通1 >> text:receipt.png")).toBe(1);
  app.onDialog(() => "确认重置");
  await app.press("重置当前加油站");
  expect(app.shows("text:receipt.png")).toBe(false);
  await app.press("id:slot-国通1 >> text:粘贴");
  await app.waitFor("text:1 张图片 · 点击继续添加");
}, 60000);

test("table preview and hover keyboard paste retain the original workflow", async () => {
  const path = "./native/app/fixtures/stats.csv";
  const app = await open("./fixtures/Clipboard.tsx", { ...options, clipboard: path });
  await app.hover("id:slot-油品时间统计");
  await app.keyboard.press("mod+v");
  await app.waitFor("text:stats.csv");
  await app.press("id:slot-油品时间统计 >> text:预览");
  await app.waitFor("text:0#柴油");
  await app.press("关闭预览");
  expect(app.enabled("id:calculate")).toBe(true);
});

test("independent report failures, previewed calculation and stale-result invalidation", async () => {
  const app = await open("./fixtures/Workflow.tsx", options);
  expect(app.shows("text:已上传 5 个文件 · 还缺：油品优惠（日报）")).toBe(true);
  expect(app.shows("id:balance")).toBe(false);
  await app.press("id:parameters-toggle");
  await app.type("id:balance", "900");
  await app.press("id:parameters-toggle");
  await app.press("id:parameters-toggle");
  expect(app.value("id:balance")).toBe("900");
  await app.clear("id:balance");
  await app.press("id:parameters-toggle");
  await app.press("id:slot-日报模板 >> text:移除");
  expect(app.shows("text:已上传 4 个文件 · 必填表格已齐，可以开始处理")).toBe(true);
  // Restore the invalid daily template to retain independent-failure coverage.
  app.dispose();
  const workflow = await open("./fixtures/Workflow.tsx", options);
  await workflow.press("id:calculate");
  await workflow.waitFor("处理完成，可预览或导出表格。", { timeout: 15000 });
  expect(workflow.enabled("导出简表")).toBe(true);
  expect(workflow.enabled("导出日报")).toBe(false);
  await workflow.press("预览简表");
  await workflow.waitFor("text:510");
  expect(workflow.shows("text:保留")).toBe(true);
  await workflow.press("关闭预览");
  await workflow.press("日志");
  await workflow.waitFor("text:/失败/");
  await workflow.press("首页");
  await workflow.waitFor("id:gas-price");
  await workflow.clear("id:gas-price");
  await workflow.type("id:gas-price", "9.01");
  expect(workflow.enabled("导出简表")).toBe(false);
}, 60000);

test("clipboard file entries take priority over text and image representations", async () => {
  const paths = ["file:///tmp/1%20%E4%B8%AD.xlsx", "file:///tmp/2.xlsx"];
  const content = await readUploadClipboard(
    {
      readFiles: async () => paths,
      readText: async () => {
        throw new Error("File names are not file paths");
      },
      readImage: async () => {
        throw new Error("File thumbnails are not screenshots");
      },
    },
    true,
  );
  expect(content).toEqual({ paths });
});

test("clipboard text paths are separated and quoted paths are supported", async () => {
  const read = (text: string) =>
    readUploadClipboard(
      {
        readFiles: async () => [],
        readText: async () => text,
        readImage: async () => null,
      },
      false,
    );
  expect(await read('"/tmp/表 格.xlsx"\r\n"/tmp/2.xlsx"')).toEqual({
    paths: ["/tmp/表 格.xlsx", "/tmp/2.xlsx"],
  });
  expect(await read("file:///tmp/1.xlsx\nfile:///tmp/2.xlsx")).toEqual({
    paths: ["file:///tmp/1.xlsx", "file:///tmp/2.xlsx"],
  });
  expect(await read("普通文字")).toBe(null);
  expect(
    await readUploadClipboard(
      {
        readFiles: async () => [],
        readText: async () => "",
        readImage: async () => ({ url: "data:image/png;base64,test" }),
      },
      true,
    ),
  ).toEqual({ image: "data:image/png;base64,test" });
});

test("pasting multiple table paths reports the single-file constraint without reading a joined path", async () => {
  const app = await open("./fixtures/Clipboard.tsx", {
    ...options,
    clipboard: "./native/app/fixtures/stats.csv\n./native/app/fixtures/details.csv",
  });
  await app.hover("id:slot-油品时间统计");
  await app.keyboard.press("mod+v");
  await app.waitFor("每个表格位置请选择一个文件。");
  expect(app.shows("text:/Not a directory/")).toBe(false);
});

test("copied file entries upload through the keyboard even when their text is not a path", async () => {
  const app = await open("./fixtures/Clipboard.tsx", {
    ...options,
    clipboard: "files:./native/app/fixtures/stats.csv",
  });
  await app.hover("id:slot-油品时间统计");
  await app.keyboard.press("mod+v");
  await app.waitFor("text:stats.csv");
  expect(app.shows("text:/文件不存在/")).toBe(false);
});

test("a running batch allows another upload, queued edits and independent results", async () => {
  const app = await open("./fixtures/Batches.tsx", options);
  const firstDate = app.value("id:date");
  await app.press("id:calculate");
  await app.waitFor("text:加油站 1 · 处理中");
  await app.press("id:new-batch");
  expect(app.value("id:gas-price")).toBe("8.23");
  await app.clear("id:gas-price");
  await app.type("id:gas-price", "9.01");
  await app.clear("id:date");
  await app.type("id:date", "2026-10-21");
  for (const category of ["简表模板", "油品时间统计", "加油明细", "充值明细"]) {
    await app.press(`复制${category}`);
    await app.press(`id:slot-${category} >> text:粘贴`);
  }
  await app.press("id:parameters-toggle");
  await app.type("id:balance", "600");
  await app.press("id:parameters-toggle");
  await app.press("id:calculate");
  await app.waitFor("text:加油站 2 · 排队中");
  expect(app.enabled("id:upload-简表模板")).toBe(false);
  await app.press("取消排队");
  expect(app.enabled("id:upload-简表模板")).toBe(true);
  await app.press("id:calculate");
  await app.press("id:batch-1");
  expect(app.value("id:gas-price")).toBe("8.23");
  expect(app.value("id:date")).toBe(firstDate);
  await app.press("id:new-batch");
  await app.press("id:release-job");
  await app.waitFor("text:加油站 1 · 可导出", { timeout: 15000 });
  await app.waitFor("text:加油站 2 · 处理中");
  expect(app.enabled("导出简表")).toBe(false);
  app.onDialog(() => "确认重置");
  await app.press("重置当前加油站");
  await app.press("id:batch-1");
  expect(app.enabled("导出简表")).toBe(true);
  await app.press("预览简表");
  await app.waitFor("text:510");
  await app.press("关闭预览");
  await app.press("id:release-job");
  await app.waitFor("text:加油站 2 · 可导出", { timeout: 15000 });
  await app.press("id:batch-2");
  expect(app.value("id:gas-price")).toBe("9.01");
  expect(app.value("id:date")).toBe("2026-10-21");
  await app.press("预览简表");
  await app.waitFor("text:200");
  await app.press("关闭预览");
  await app.press("重置当前加油站");
  expect(app.enabled("导出简表")).toBe(false);
  await app.press("id:batch-1");
  expect(app.enabled("导出简表")).toBe(true);
  await app.press("预览简表");
  await app.waitFor("text:510");
  await app.press("关闭预览");
}, 60000);

test("late pasted files and failed jobs stay with their original batch", async () => {
  const app = await open("./fixtures/Batches.tsx", options);
  await app.press("id:calculate");
  await app.press("id:new-batch");
  await app.press("延迟粘贴");
  await app.press("id:slot-简表模板 >> text:粘贴");
  await app.press("id:new-batch");
  await app.press("完成粘贴");
  expect(app.shows("text:simple.xlsx")).toBe(false);
  await app.press("id:batch-2");
  await app.waitFor("text:simple.xlsx");
  await app.press("id:calculate");
  await app.waitFor("text:加油站 2 · 排队中");
  await app.press("id:batch-3");
  await app.press("id:release-job");
  await app.waitFor("text:加油站 1 · 可导出", { timeout: 15000 });
  await app.waitFor("text:加油站 2 · 处理中");
  await app.press("id:release-job");
  await app.waitFor("text:加油站 2 · 失败", { timeout: 15000 });
  expect(app.shows("text:/缺少源表/")).toBe(false);
  await app.press("id:batch-2");
  await app.waitFor("text:/缺少源表/");
  expect(app.enabled("id:calculate")).toBe(true);
  app.onDialog(() => "移除加油站");
  await app.press("id:close-batch-2");
  await app.waitFor("id:batch-2", { state: "gone" });
  await app.press("id:batch-1");
  expect(app.enabled("导出简表")).toBe(true);
}, 60000);

test("removing stations requires confirmation, preserves selection and keeps a fresh last station", async () => {
  const app = await open("./fixtures/Empty.tsx", options);
  await app.press("id:new-batch");
  await app.press("id:new-batch");
  await app.clear("id:gas-price");
  await app.type("id:gas-price", "9.21");
  app.onDialog(() => "移除加油站");
  await app.press("id:close-batch-2");
  await app.waitFor("id:batch-2", { state: "gone" });
  expect(app.shows("id:batch-2")).toBe(false);
  expect(app.value("id:gas-price")).toBe("9.21");
  await app.press("id:close-batch-3");
  await app.waitFor("id:batch-3", { state: "gone" });
  expect(app.shows("id:batch-3")).toBe(false);
  expect(app.value("id:gas-price")).toBe("8.23");
  await app.press("id:close-batch-1");
  await app.waitFor("id:batch-1", { state: "gone" });
  expect(app.shows("id:batch-1")).toBe(false);
  expect(app.shows("id:batch-4")).toBe(true);
  expect(app.enabled("id:calculate")).toBe(true);
  expect(app.dialogs().length).toBe(3);
});

test("closing a new tab does not stop a running batch, and closing its results requires confirmation", async () => {
  const app = await open("./fixtures/Batches.tsx", options);
  await app.press("id:calculate");
  expect(app.enabled("id:close-batch-1")).toBe(false);
  await app.press("id:new-batch");
  app.onDialog(() => "移除加油站");
  await app.press("id:close-batch-2");
  await app.waitFor("id:batch-2", { state: "gone" });
  expect(app.shows("id:batch-2")).toBe(false);
  await app.press("id:release-job");
  await app.waitFor("text:加油站 1 · 可导出", { timeout: 15000 });
  await app.press("id:new-batch");
  app.onDialog(() => "取消");
  await app.press("id:close-batch-1");
  expect(app.shows("id:batch-1")).toBe(true);
  expect(app.value("id:batch-name")).toBe("加油站 3");
  app.onDialog(() => "移除加油站");
  await app.press("id:close-batch-1");
  await app.waitFor("id:batch-1", { state: "gone" });
  expect(app.shows("id:batch-1")).toBe(false);
  expect(app.value("id:batch-name")).toBe("加油站 3");
}, 60000);

test("fixed stations persist names, prices, selection and removal without yesterday's files or results", async () => {
  const first = await open("./fixtures/Stations.tsx", options);
  await first.clear("id:batch-name");
  await first.type("id:batch-name", "城东站");
  await first.clear("id:gas-price");
  await first.type("id:gas-price", "8.51");
  await first.clear("id:date");
  await first.type("id:date", "2001-01-01");
  await first.press("id:calculate");
  await first.waitFor("text:城东站 · 可导出", { timeout: 15000 });
  await first.press("id:new-batch");
  await first.clear("id:batch-name");
  await first.type("id:batch-name", "城西站");
  await first.clear("id:gas-price");
  await first.type("id:gas-price", "9.12");
  // Input events and the persistence effect can finish after the driver step.
  // Verify the on-disk snapshot before opening a second application instance.
  await first.waitUntil(() => {
    const saved = Reports.stations();
    const selected = saved.stations.find((station) => station.id === saved.selectedId);
    return selected?.name === "城西站" && selected.gasPrice === "9.12";
  });

  const reopened = await open("./App.tsx", options);
  await reopened.waitUntil(() => reopened.value("id:batch-name") === "城西站");
  expect(reopened.value("id:batch-name")).toBe("城西站");
  expect(reopened.value("id:gas-price")).toBe("9.12");
  await reopened.press("id:batch-1");
  expect(reopened.value("id:batch-name")).toBe("城东站");
  expect(reopened.value("id:gas-price")).toBe("8.51");
  expect(reopened.value("id:date")).not.toBe("2001-01-01");
  expect(reopened.shows("text:stats.csv")).toBe(false);
  expect(reopened.shows("text:城东站 · 可导出")).toBe(false);
  reopened.onDialog(() => "取消");
  await reopened.press("id:close-batch-2");
  expect(reopened.shows("id:batch-2")).toBe(true);
  reopened.onDialog(() => "移除加油站");
  await reopened.press("id:close-batch-2");
  await reopened.waitFor("id:batch-2", { state: "gone" });
  await reopened.waitUntil(
    () => !Reports.stations().stations.some((station) => station.number === 2),
  );
  const last = await open("./App.tsx", options);
  expect(last.shows("id:batch-2")).toBe(false);
  expect(last.value("id:batch-name")).toBe("城东站");
  expect(last.value("id:gas-price")).toBe("8.51");
}, 60000);
