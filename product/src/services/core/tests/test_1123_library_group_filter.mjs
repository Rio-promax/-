import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import test from "node:test";

const appPath = fileURLToPath(new URL("../app/ui/app.js", import.meta.url));
const appSource = await readFile(appPath, "utf8");

test("library group filters use OR within each kind and AND between kinds", () => {
  const start = appSource.indexOf("  function libraryEntries() {");
  const end = appSource.indexOf("\n  /* R4：合集归属", start);
  assert.ok(start >= 0 && end > start, "libraryEntries must be available for the UI entrypoint");

  const context = {
    S: {
      history: [
        { id: "a", content: { tag_ids: ["t1"], favorite_folder_ids: ["f1"] } },
        { id: "b", content: { tag_ids: ["t2"], favorite_folder_ids: ["f2"] } },
        { id: "c", content: { tag_ids: ["t3"], favorite_folder_ids: ["f1"] } },
        { id: "d", content: { tag_ids: ["t1"], favorite_folder_ids: ["f3"] } },
        { id: "e", content: { tag_ids: ["t2"], favorite_folder_ids: ["f1"] } },
      ],
      activeTagIds: ["t1", "t2"],
      activeFolderIds: ["f1", "f2"],
      libQuery: "",
      libFilters: { platform: null, kind: null, duration: null, introduction: null },
    },
    contentOf: (entry) => entry.content,
  };

  vm.createContext(context);
  vm.runInContext(`${appSource.slice(start, end)}\nglobalThis.visibleEntries = libraryEntries();`, context);

  assert.deepEqual(context.visibleEntries.map((entry) => entry.id), ["a", "b", "e"]);
});

test("detail quick list uses the frozen filter context from the library", () => {
  const pStart = appSource.indexOf("  function contentMatchesFilters(content, ctx) {");
  const pEnd = appSource.indexOf("\n  /* 11-23：进入详情时冻结", pStart);
  const qStart = appSource.indexOf("  function quickEntries() {");
  const qEnd = appSource.indexOf("\n  /* 11-18 R4：按最新成功任务", qStart);
  assert.ok(pStart >= 0 && pEnd > pStart, "contentMatchesFilters must exist");
  assert.ok(qStart >= 0 && qEnd > qStart, "quickEntries must exist");

  const context = {
    S: {
      history: [
        { id: "a", content: { title: "A", tag_ids: ["t1"], favorite_folder_ids: ["f1"] } },
        { id: "b", content: { title: "B", tag_ids: ["t2"], favorite_folder_ids: ["f2"] } },
        { id: "c", content: { title: "C", tag_ids: ["t1"], favorite_folder_ids: ["f1"] } },
      ],
      quickQuery: "",
      quickContext: { tagIds: ["t1"], folderIds: ["f1"], filters: {} },
    },
    contentOf: (entry) => entry.content,
  };

  vm.createContext(context);
  vm.runInContext(
    `${appSource.slice(pStart, pEnd)}\n${appSource.slice(qStart, qEnd)}\nglobalThis.visibleEntries = quickEntries();`,
    context
  );
  assert.deepEqual(context.visibleEntries.map((entry) => entry.id), ["a", "c"]);

  context.S.quickContext = null;
  vm.runInContext("globalThis.visibleEntries = quickEntries();", context);
  assert.deepEqual(context.visibleEntries.map((entry) => entry.id), ["a", "b", "c"]);
});
