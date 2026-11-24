# 项目开发约束

1. 新增实现前先查询相关代码、调用方与测试。已有实现满足行为要求时直接复用。需要另写时，说明现有实现无法满足的行为或边界。
2. 新增校验、兜底或抽象前先确认依据。检查输入在哪一层校验、异常由谁处理，避免为基本不可能发生的场景添加防御性代码。新增接口、工厂或策略时，说明当前的调用方、职责边界或已确定的变化，不为单一场景引入抽象。
3. 当任务涉及产品代码、页面、功能、交互或设计实现的开发与修改时，先读取 Git 状态作为代码上下文，至少检查当前分支和未提交改动。完成后根据本轮 diff 创建本地 commit。
4. 每轮代码修改完成后，如实汇报自动检查结果与待人工验收项。在《进度现状》和任务记录中，自动项按证据记录通过或失败；需要用户确认的项标为“待人工验收”，仅在用户确认通过后标为“已解决”。
5. 新文件按 `product/docs/README.md` 和 `product/src/services/core/README.md` 的落点规则保存：需求正本放文档基线，调研、笔记、产出与附件放文档过程；产品代码按核心概念、接口、外部实现、业务流程与交付入口归位。
6. 调研或样例支撑 PRD 时，在对应需求正本链接具体依据；研究记录写入 `product/docs/过程/调研/`，不要重新生成根层 `.research/` 或与 `product/docs/` 平行的材料总目录，也不要仅为新文件创建单一场景目录。
7. `product/` 内按 `docs/`、`src/`、`local/`、`.venv/` 四类归位；桌面壳等正式源码进入 `src/`，`local/` 只放运行数据、编译产物与实验资料，`.venv/` 只放 Python 环境。其他目录须先说明必要性再创建。
8. 主流程应能沿真实入口读懂。命名体现业务含义，代码清楚呈现输入、关键处理、输出和失败路径。辅助方法按明确的职责边界拆分，避免在同一条业务路径上频繁跳转。


## 工作区导航

已知目标路径时直接读取。需要查找材料或决定新文件落点时，先打开根 [README.md](README.md) 的目录树，只沿相关分支读取入口和规则。

## 默认上下文排除地址

以下工作区地址属于备份、历史、日志或临时内容，默认不作为上下文参考：

- 备份文件：`archive/`、`product/local/legacy-root/`
- 历史文件：`product/docs/历史参考/`、`archive/skills/summary/历史版本/`
- 日志文件：`product/local/api.stderr.log`、`product/local/api.stdout.log`
- 临时文件：`product/docs/临时/`、`product/local/cache/`、`product/local/experiments-video-summary/`

默认情况下不读取以上地址，不将其中内容纳入任务上下文。仅当用户明确指定，或当前任务必须排查对应日志、备份、历史或临时产物时，才读取被点名的最小文件集合。

临时文件、当前进度规则
语言以简练为主

## 模型角色路由规则

- 用户输入中的“决策者”和“C 执行者”是当前启用的模型路由触发词，无须单独成句；在普通句子中的任意位置出现也必须触发。
- 普通“执行者”当前暂停使用：单独出现“执行者”时不得触发模型切换或执行任务；仅在用户明确要求恢复后重新启用。
- “C 执行者”包含“执行者”字样时，按最长触发词优先，只触发一次“C 执行者”，不得再重复触发内含的“执行者”。
- 按触发词在输入中从左到右的出现顺序拆分和执行任务。同一句中出现多个触发词时，必须依次完成对应阶段，不得合并、跳过或并行执行。
- “决策者”阶段使用 `gpt-6-sol`，推理强度为 `medium`。
- “执行者”阶段使用 `gpt-6-luna`，推理强度为 `max`。
- “C 执行者”阶段使用 `gpt-6-luna`，推理强度为 `max`，并按 `product/docs/基线/规则/AI代码执行标准化方案.md` 执行代码重构。
- 第一个触发词之前的内容作为各阶段共享的任务背景；每个触发词之后、下一个触发词之前的内容作为该阶段的具体指令。
- 后一阶段需要延续前一阶段成果时，必须将前一阶段的结果作为上下文传入后一阶段。例如“让决策者制定方案，再让 C 执行者实现”必须先由 SOL 完成方案，再由 Luna 基于该方案执行。
- 每次切换后，对应模型的第一次输出必须在开头附上当前执行模型：`当前执行模型：SOL · Medium` 或 `当前执行模型：Luna · Max`。同一阶段的后续输出不重复附加。
- 触发词只承担路由作用，不作为阶段任务正文提交给对应模型。

### C 执行者启动门禁

方案采用与授权规则统一遵循 `product/docs/基线/规则/AI代码执行标准化方案.md` 的“方案与授权”。已有明确批准且范围未变时直接执行；随后按该标准读取相关上下文、修改、验证、提交并汇报。

需求/代码指导文档面向 AI，以AI更容易理解的形式与格式撰写

-汇报要求：在c执行者执行完代码任务后在完善方案新增进度总结记录板块，对完善方案的进度记录：
最终总结按 R1～Rn 逐项列出，问题描述以需要解决的现状为主，包含位置、现象和状态，语言保持简练，以让用户能够清晰与任务对应；
仅保留“自动验证是否通过”和“人工验证是否通过”；
人工验证留空，用户填 1/0。
如果同时依据多分完善方案，则在最新的一份完善记录中记录汇总

---

## Karpathy 行为准则（原文引用）

> 来源：`multica-ai/andrej-karpathy-skills`（原 `forrestchang/andrej-karpathy-skills`），MIT 许可。
> 以下为原文照录，仅 Simplicity First 一节按本项目口径增补了一条（询问后再加未要求的功能）。

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked. If a feature is not requested, ask the user before adding it. By default, do not add unrequested features.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## 界面文案规则

产品界面禁止出现说明类文字：标题、标签、卡片、设置项只承载名称本身，不加副标题、描述句或解释小字，不用文字复述标题。

唯一例外：不写会导致误操作或填错的提示（删除确认、不可逆操作、计费与数据后果、格式要求、校验规则）。

## 总结评审与 Prompt 完善

收到总结审核或总结 Prompt 完善任务，先读取 `product/docs/基线/规则/总结评审与Prompt完善流程.md`，按状态执行并保存续跑记录。派评审仅传其指定的评分标准与材料，不传主流程或历史决策。仅维护规则时不启动真实评测。
