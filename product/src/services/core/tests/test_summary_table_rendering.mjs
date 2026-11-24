import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const source = await readFile(new URL("../app/ui/app.js", import.meta.url), "utf8");
const escapeCode = source.slice(source.indexOf("  const esc ="), source.indexOf("\n\n  const S ="));
const renderer = source.slice(source.indexOf("  function inline("), source.indexOf("  function plainText("));
const mdToHtml = vm.runInNewContext(escapeCode + "\n" + renderer + "\nmdToHtml");

test("renders a summary table with blank lines and keeps the following heading outside it", () => {
  const meaning = "保留一次自我改进，例如根据环境反馈修改自己的 probe 和 memory，并把结果保留下来";
  const markdown = [
    "| 层级 | 含义 | 材料中的例子或状态 |",
    "",
    "|---|---|---|",
    "",
    `| 弱 | ${meaning} | 2023 年涌现的自动 prompt 优化算法属于这一类 |`,
    "",
    "| 中 | 改进下一次改进的机制 | **Meta RSI** |",
    "",
    "| 强 | 自己定义问题 | 材料称暂无公开系统达到 |",
    "",
    "## Meta RSI 的整体结构",
  ].join("\r\n");
  const html = mdToHtml(markdown, { tables: true });
  assert.match(html, /<table><thead><tr><th>层级<\/th><th>含义<\/th><th>材料中的例子或状态<\/th>/);
  assert.ok(html.includes(`<td>${meaning}</td><td>2023 年涌现的自动 prompt 优化算法属于这一类</td>`));
  assert.match(html, /<td><strong>Meta RSI<\/strong><\/td>/);
  assert.match(html, /<td>材料称暂无公开系统达到<\/td><\/tr><\/tbody><\/table><\/div><h3>/);
});

test("preserves ordinary pipe text and safely renders literal pipes and HTML in cells", () => {
  const html = mdToHtml([
    "含有 | 的普通段落",
    "",
    "名称 | 内容",
    "--- | ---",
    "A | x\\|y <b>",
    "",
    "结尾 | 普通段落",
  ].join("\n"), { tables: true });
  assert.match(html, /^<p>含有 \| 的普通段落<\/p>/);
  assert.match(html, /<td>x\|y &lt;b&gt;<\/td>/);
  assert.match(html, /<\/table><\/div><p>结尾 \| 普通段落<\/p>$/);
});
