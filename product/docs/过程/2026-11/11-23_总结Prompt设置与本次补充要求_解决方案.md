# 11-23 总结 Prompt 设置与本次补充要求

## 文档状态

- 类型：功能完善方案（用户当轮「实施」授权后直接实施，普通任务未启用 Goal）。
- 业务日期：2026-11-23。
- Scale：M。
- 当前状态：R1～R7 已实施并在本轮完成本地提交；自动验证见进度总结记录，人工验证列留空由用户填 1/0。
- 授权：用户先「先给出方案」冻结本文，后明确「实施」授权代码改动。
- 基线：`product/src/services/core/app/ui/index.html`、`app.js`、`product/src/services/core/app/api/schemas.py`、`main.py`、`app/workflows/analyze.py` 当前工作树。
- 命名决定：输入框界面标签「补充要求」，DOM id `intake-extra-instruction` / `restyle-extra-instruction`，请求字段 `extra_instruction`。用户授权 AI 先定，可在实施前一句话改。

## 图片与需求映射

- 本轮用户未附图片，无附件图与映射。

## 产品问题 1

### 用户原话区（逐字，不许改写）

- U-R1-01 · 初始提出

  > 把设置中的那个总结 prompt 加上去吧，然后再加一个功能是当用户选择总结，力度总结这个的时候在下面，在那个选项下面加一个，加一个输入框，就是可以让用户选填的一个东西。那个输入框的命名你可以先定一下，然后在重新生成的时候，这个输入框也需要同步出现，先给出方案。

### AI 解释区

- 需求编号：R1、R2、R3、R7。
- 现状：设置页「模型」分区 `modelPane()`（`app.js:2946`）只有接口地址、密钥、模型三项，没有总结 Prompt 编辑框；后端已完整支持 `summary_prompt`（`schemas.py:909/947`、`main.py:_summary_prompt`、`main.py:6299` 保存、`analyze.py:1271` 消费）。旧版 `_legacy/app.js` 有 `#summary-prompt`，新版迁移时未带过来。
- 用户第二个需求是在选风格/强度的那个界面下面加一个选填输入框；「重新生成」时该输入框也要同步出现。

## 产品问题 2

### 用户原话区（逐字，不许改写）

- U-R2-01 · 用途澄清

  > 呃相当于是用户额外补充的单词 prompt，这里的总结力度就是我们在选择的时候会有一个选择嘛，选择通用详细还是各个风格，就是在那个界面的下面，它的作用只是为了定位。

### AI 解释区

- 需求编号：R4、R5、R6。
- 输入框用途按原话理解为：**本次总结单独追加的一段 prompt**，选填，只对这一次生成生效，不写回全局 `summary_prompt` 设置。
- 「总结力度」按原话理解为：用户对「总结强度 / 表达风格」那组选项的说法，它只用于**指认界面位置**（即输入框加在这组选项下面），不是要新增一个叫「力度」的功能。
- 不确定处：「额外补充的单词 prompt」按语音输入理解为「额外补充的一小段 prompt」。若用户原意是「每个单词一条」或别的口径，实施前纠正。
- 依据：`analyze.py:1271-1279` 生成时从任务快照读 `summary_prompt`，hash 校验后有 M1 追加先例，可在此同位置追加本次补充内容而不破坏快照校验。

## 需求与轮次映射

| 产品问题 | 需求 | 轮次 | 交付物 |
|---|---|---|---|
| 1 | 设置页模型分区新增「总结 Prompt」编辑框并接入保存 | R1 | `app.js::modelPane` 加 textarea；`settings-save` 带上 `summary_prompt` |
| 1 | 导入页风格/强度选项下加「补充要求」选填输入框 | R2 | `index.html` 选项区、`app.js::summaryConfig` |
| 1 | 重新总结弹窗同步出现「补充要求」输入框 | R3 | `index.html` restyle 区、`app.js::submitRestyle` |
| 2 | 四类导入请求模型新增 `extra_instruction` | R4 | `schemas.py` 的 Local / Link / LinkQueryConfirm / Resummarize 请求 |
| 2 | 后端把本次补充要求写入任务 settings 快照 | R5 | `main.py::_analysis_settings_from_store` 增参数并写入 |
| 2 | 生成总结时把补充要求追加到 prompt | R6 | `app/workflows/analyze.py` 生成前追加 |
| 1、2 | 契约测试、定向 pytest、语法与运行服务复核 | R7 | 新增前后端用例 |

## 统一范围与实施顺序

**本轮实现**

1. 设置页模型分区加「总结 Prompt」多行编辑框；保存时把内容随 `PUT /settings` 提交。纯 prompt 修改不得触发连通性测试换 token（后端 `main.py:6226-6228` 已为 prompt-only patch 留独立通道，前端不能把它算进 `summaryChanged`）。
2. 导入页「总结强度」选项下面加「补充要求」选填输入框，`summaryConfig()` 把值带入提交。
3. 重新总结弹窗在「总结强度」下面加同名字段，`submitRestyle()` 把值带入提交。
4. 四类请求加 `extra_instruction`；后端写入任务快照；生成时在 M1 追加同位置拼到 prompt 末尾，不改动全局 prompt 的 hash 与版本身份。
5. 新增用例覆盖：填入生效、留空无影响、重新总结同步出现、纯 prompt 保存不触发 token。

**明确不实施**

- 不把本次「补充要求」写回全局 `summary_prompt` 设置。
- 不改 `prompt_version` / `summary_prompt_hash` 的计算口径：它们仍只标识全局 prompt 版本，补充要求独立存快照。
- 不改强度/风格枚举、不改 ASR、不改归档、不改问答。
- 不给账号快捷导入、手机端入口加这个字段（它们不带风格/强度选项区）。

**实现顺序**

1. RED：先写 R7 用例，确认当前不满足。
2. 前端 R1～R3，后端 R4～R6。
3. 定向 pytest、`node --check`、`git diff --check`，运行服务只读复核。
4. 按 R1～R7 回填进度总结记录，按项目规则创建本地 commit（实施获授权后）。

## R1

- 状态：已实施。
- 现状：`app.js:2946 modelPane()` 只渲染接口地址、密钥、模型三项；`settings-save`（`app.js:3904`）的 `body` 不含 `summary_prompt`；后端 `SettingsResponse.summary_prompt` 已返回值。
- 原因：新版 UI 迁移时漏带旧版已有的总结 Prompt 编辑框。
- 方案：在 `modelPane()` 用 `setField` 加一个 `data-setting-key="summary_prompt"` 的多行输入框，初值 `S.settings.summary_prompt`；`settings-save` 读取该字段，与 `saved.summary_prompt` 不同则写入 `body.summary_prompt`（仅改 prompt 时也要让 `body` 非空）；不得把 prompt 改动计入 `summaryChanged`。
- 验收：设置→模型可见并可编辑总结 Prompt；保存后刷新仍显示新值；只改 Prompt 时保存成功且不调用 `/settings/summary/test`；留空/恢复默认行为与后端 `_summary_prompt` 回退 `DEFAULT_SUMMARY_PROMPT` 一致。

## R2

- 状态：已实施。
- 现状：`index.html:95-98` 的「总结强度」选项区下面紧接账号快捷导入，无补充输入框；`app.js:565 summaryConfig()` 只返回 `summary_style`、`strength`。
- 原因：需求新增。
- 方案：选项区强度字段后面加一个 `textarea#intake-extra-instruction`，标签「补充要求」，选填；`summaryConfig()` 增 `extra_instruction: $("#intake-extra-instruction").value`；提交路径 `/imports/query/confirm` 经 `...summaryConfig()` 自动带上。
- 验收：导入页强度下面出现「补充要求」输入框；填入后提交的 `/imports/query/confirm` 请求体含 `extra_instruction`；留空时提交空字符串、后端按无补充处理。

## R3

- 状态：已实施。
- 现状：`index.html:422-425` 重新总结弹窗只有风格、强度两项；`app.js:3209 submitRestyle()` 提交体只有 `summary_style`、`strength`、`reuse_content`。
- 原因：用户要求重新生成时该输入框同步出现。
- 方案：弹窗强度下面加 `textarea#restyle-extra-instruction`；`openRestyle()` 打开时清空或带出初始值（默认清空，避免跨内容串值）；`submitRestyle()` 请求体增 `extra_instruction`。
- 验收：内容详情点「重新生成 / 重新总结」后弹窗出现「补充要求」；填入后提交体含该字段；取消/失败路径行为不变。

## R4

- 状态：已实施。
- 现状：`schemas.py` 的 `LocalImportRequest`（:270）、`LinkImportRequest`（:332）、`LinkQueryConfirmRequest`（:375）、`ResummarizeRequest`（:300）都只有 style/strength，无补充字段。
- 原因：需要给前端提交的内容一个后端入口。
- 方案：四个模型各加 `extra_instruction: str | None = Field(default=None, max_length=2000)`；不设 `extra="forbid"` 的新约束，保留既有行为。
- 验收：带字段的请求解析成功；超过限长返回 422；不带字段时全部请求与现状一致。

## R5

- 状态：已实施。
- 现状：`main.py::_analysis_settings_from_store`（约 :7884）把设置快照组装进 `AnalysisSettings`，不含本次补充要求。
- 原因：生成链路需要从任务快照读到本次补充内容。
- 方案：函数增 `extra_instruction: str | None = None` 参数，写入返回对象的 settings 快照（独立键，不并入 `summary_prompt`）；在四类导入/重总结 handler 调用处把 `request.extra_instruction` 传入。
- 验收：带补充要求提交后，任务的 `settings_snapshot` 含该值；既有多处调用点不传时保持原行为。

## R6

- 状态：已实施。
- 现状：`analyze.py:1271-1279` 读快照 `summary_prompt`，hash 校验后有 M1 追加先例；`summarize_chunks` 在 :1294-1311 组装 `prompt`。
- 原因：补充要求必须真正进入发给模型的 prompt 才生效。
- 方案：在 M1 追加同位置，读快照里的 `extra_instruction`，非空则 strip 后拼到 `prompt` 末尾（如「\n\n本次补充要求：\n...」）；放在 hash 校验之后，不改 hash 与 version 身份；留空时不追加。
- 验收：填入时发给总结模型的 prompt 含补充内容；留空时 prompt 与现状一致；快照 hash 校验仍通过；重试复用同一任务快照时补充要求一致。

## R7

- 状态：已实施。
- 现状：无覆盖本需求的用例。
- 原因：需要前后端双向证据，避免只改界面不生效或只改后端不显示。
- 方案：新增前端契约用例（Python 读源码文本）覆盖两个输入框存在、`summaryConfig`/`submitRestyle` 带字段、设置保存带 `summary_prompt` 且不触发 token；新增后端用例覆盖四个请求模型字段、快照写入、生成追加与留空等效；跑定向 pytest、`node --check`、`git diff --check`，运行服务只读复核 OpenAPI。
- 验收：新增用例 RED→GREEN；既有定向用例全绿；前端语法与 diff 检查通过。

## 进度总结记录

| 编号 | 现状问题（位置/现象/状态） | 自动验证是否通过 | 人工验证是否通过 |
|---|---|---|---|
| R1 | 设置页模型分区缺总结 Prompt 编辑框 | 通过：`modelPane()` 增 `data-setting-key="summary_prompt"` 的 textarea；`settings-save` 的 `body.summary_prompt` 独立，`summaryChanged` 不含它；`test_r1` 覆盖 | |
| R2 | 导入页风格/强度选项下缺「补充要求」选填框 | 通过：`index.html` 增 `intake-extra-instruction`；`summaryConfig()` 带 `extra_instruction`；`test_r2` 覆盖 | |
| R3 | 重新总结弹窗缺「补充要求」输入框 | 通过：弹窗增 `restyle-extra-instruction`；`openRestyle()` 打开清空、`submitRestyle()` 带字段；`test_r3` 覆盖 | |
| R4 | 四类导入请求模型无 `extra_instruction` | 通过：`schemas.py` 四个请求模型增字段（默认 None、限长 2000）；`test_r4` 两项覆盖含超长 422 | |
| R5 | 任务设置快照不携带本次补充要求 | 通过：`AnalysisSettings` 增字段并进 `as_dict()`；`_analysis_settings_from_store` 接收并 strip 写入；四处 handler 传参；`test_r5` 验证快照携带且不并入全局 prompt | |
| R6 | 生成总结时 prompt 不含本次补充要求 | 通过：`analyze.py` 在 M1 追加同位置（hash 校验之后）拼 `本次补充要求`；`test_r6` 两项验证填入生效、留空无影响 | |
| R7 | 缺本需求的前后端自动验证 | 通过：新增 `test_1123_summary_prompt_extra_instruction_contract.py` 9 passed；相关既有 34 passed / 3 failed（3 项均为 `test_1110_rebuild_contract.py` 对旧版 UI 文本的断言，本轮未触碰且当前源码无对应串）；`node --check` 通过；`git diff --check` 本轮文件无错 | |

> 注：3 项既有失败来自 `test_1110_rebuild_contract.py`（`job.state || ...`、`detail?.messages`、`.screen[data-screen="intake"] { max-width: none }`），这些文本在 `HEAD` 的 `app.js`/`style.css` 中同样不存在，属开工前在途状态，与本轮改动无关。
> 人工验收待用户执行：设置页能看到并保存总结 Prompt；导入页和重新总结弹窗的「补充要求」填入后总结确实按补充要求生成；重新生成时输入框每次为空。
