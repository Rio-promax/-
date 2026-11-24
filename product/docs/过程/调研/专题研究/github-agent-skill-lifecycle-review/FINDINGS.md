---
topic: github-agent-skill-lifecycle-review
created: 2026-09-13
last_verified: 2026-09-13
status: active
depth: deep
related: []
sources:
  - url: https://raw.githubusercontent.com/github/spec-kit/main/templates/commands/specify.md
    fetched: 2026-09-13
  - url: https://raw.githubusercontent.com/github/spec-kit/main/templates/commands/plan.md
    fetched: 2026-09-13
  - url: https://raw.githubusercontent.com/github/spec-kit/main/templates/commands/tasks.md
    fetched: 2026-09-13
  - url: https://raw.githubusercontent.com/github/spec-kit/main/templates/commands/implement.md
    fetched: 2026-09-13
  - url: https://github.com/github/spec-kit/blob/main/docs/reference/workflows.md
    fetched: 2026-09-13
  - url: https://raw.githubusercontent.com/obra/superpowers/main/skills/writing-plans/SKILL.md
    fetched: 2026-09-13
  - url: https://raw.githubusercontent.com/obra/superpowers/main/skills/executing-plans/SKILL.md
    fetched: 2026-09-13
  - url: https://raw.githubusercontent.com/obra/superpowers/main/skills/test-driven-development/SKILL.md
    fetched: 2026-09-13
  - url: https://raw.githubusercontent.com/obra/superpowers/main/skills/verification-before-completion/SKILL.md
    fetched: 2026-09-13
  - url: https://raw.githubusercontent.com/obra/superpowers/main/skills/requesting-code-review/SKILL.md
    fetched: 2026-09-13
  - url: https://raw.githubusercontent.com/openai/openai-cookbook/main/examples/codex/iterating-development-workflows-with-codex.md
    fetched: 2026-09-13
  - url: https://raw.githubusercontent.com/github/awesome-copilot/main/agents/plan.agent.md
    fetched: 2026-09-13
  - url: https://github.com/microsoft/vscode-docs/blob/main/docs/copilot/customization/custom-agents.md
    fetched: 2026-09-13
  - url: https://raw.githubusercontent.com/mblode/agent-skills/main/skills/planning/SKILL.md
    fetched: 2026-09-13
  - url: https://raw.githubusercontent.com/addyosmani/adverse/main/skills/adverse-review/SKILL.md
    fetched: 2026-09-13
  - url: https://raw.githubusercontent.com/poteto/noodle/main/.agents/skills/adversarial-review/SKILL.md
    fetched: 2026-09-13
  - url: https://raw.githubusercontent.com/trailofbits/skills/main/plugins/differential-review/skills/differential-review/SKILL.md
    fetched: 2026-09-13
  - url: https://raw.githubusercontent.com/agakadela/aga-verify-agent/main/SKILL.md
    fetched: 2026-09-13
  - url: https://github.com/h1r9do/get-shit-done-ClaudeCode/blob/main/README.md
    fetched: 2026-09-13
  - url: https://raw.githubusercontent.com/superagent-ai/skills/main/skills/skill-security/SKILL.md
    fetched: 2026-09-13
---

# GitHub Agent Skill 需求—实施—验收生命周期调研

## Summary

成熟体系不依赖一份超长提示词，而是把需求、计划、实施、审查和验真拆成持久化产物与明确门禁。GitHub Spec Kit 和 Superpowers 的生命周期覆盖最完整；AGA Verify 对“授权任务是否真正完成”的证据约束最严谨；Trail of Bits 和 Adverse 的风险审查更专业。本地体系已有需求来源隔离、方案独立审核、跨模块追踪表、完成证据门禁和人工验收状态；值得补强的是现有追踪表的代码/证据字段、高风险任务的快照身份、可执行的风险升级条件和实施后复核闭环。

## Findings

调研通过 20 组定向检索覆盖需求/方案撰写、对抗审查、实施约束、验收验真和 skill 安全，并直接阅读了 11 个仓库或官方文档仓库的源文件。单仓库机制说明天然是该仓库的一手单源主张；跨仓库结论经多个独立来源交叉。

| 体系 | 代表文件 | 关键优点 | 局限 |
|---|---|---|---|
| `github/spec-kit` | `templates/commands/{specify,plan,tasks,implement}.md` | 规格→计划→任务→实施独立持久化；用 constitution 和 checklist 做前后门禁；任务按可独立测试的用户故事分组 | 小任务仪式偏重；测试并非始终强制 |
| `obra/superpowers` | `writing-plans`, `executing-plans`, `test-driven-development`, `verification-before-completion` | 精确路径、接口、命令及预期红/绿结果；小步 TDD；完成声明前必须获取当前证据 | 高度规范化且耗上下文；对原型、配置和遗留代码可过度 |
| `openai/openai-cookbook` | `examples/codex/iterating-development-workflows-with-codex.md` | 用 `AGENTS.md`、分阶段计划、接受标准、红绿重构、证据与高风险独立验证组成 Codex 原生范式 | 是参考教程，不是开箱即用的 skill 链 |
| `github/awesome-copilot` | `agents/plan.agent.md` | 规划角色只读探索代码、调用者、问题、依赖、风险和测试 | 输出契约宽松，无强制覆盖矩阵或证据 schema |
| `microsoft/vscode-docs` | `docs/copilot/customization/custom-agents.md` | 用最小工具集隔离 Planner→Implementer→Reviewer，并提供可见 handoff | 交接传递文本，不证明覆盖或正确性 |
| `mblode/agent-skills` | `skills/planning/SKILL.md` | 计划紧凑，但强制 outcome、acceptance criteria、boundary 与逐标准验证 | 仅规划，无执行器或验收裁决 |
| `addyosmani/adverse` | `skills/adverse-review/SKILL.md` | Auditor/Adversary/Pragmatist 独立审查、交叉诉讼、schema 校验和确定性聚合 | 调用成本高；同模型仍可共享盲区；共识不是事实证明 |
| `poteto/noodle` | `.agents/skills/adversarial-review/SKILL.md` | 使用对立模型 CLI；按变更规模扩审查者；默认只读 | 依赖多 CLI/账号；成本、复现性和冲突裁决都更难 |
| `trailofbits/skills` | `plugins/differential-review/skills/differential-review/SKILL.md` | 用 Git 历史、调用者爆炸半径、测试覆盖与攻击场景做高风险差分审查 | 专用于安全敏感 diff，深度模式可耗时数小时 |
| `agakadela/aga-verify-agent` | `SKILL.md`, `references/output-templates.md` | 重建权威任务契约，将证据绑定到确切快照，区分“任务履约验真”与“代码质量审查” | 项目缺乏实施前契约时，只能得到有限置信的验证 |
| `h1r9do/get-shit-done-ClaudeCode` | `README.md` 及 discuss/plan/execute/verify/plan-fix/ship 工作流 | 完整的讨论→计划→执行→验证→修复→交付循环，新鲜上下文和原子提交 | 编排面大且成本高；跳过权限提示会扩大风险 |
| `superagent-ai/skills` | `skills/skill-security/SKILL.md` | 将 skill 本身视为供应链输入，检查注入、外传、持久化和行为—描述不符 | 静态启发式无法证明无害，会有误报和语义攻击漏报 |

与本地 skill 相比，本地的 `requirement-save-source-audit` 对用户原话、覆盖关系和问题区做冻结隔离，这在外部样本中少见；`independent-solution-audit` 已有双向对应、事实核验、过度防御、证据缺口和人工验收状态；`AI代码执行标准化方案` 已包含 Git 基线、用户改动保护、范围门禁、有针对性验证、失败继续定位和人工验收不冒充通过。这些都不应被外部通用模板取代。

本地的主要增强点是：已有追踪表可选补入最终代码位置、审查状态和证据身份，不应另建第二份状态源；高风险或跨轮任务需将验证绑定到可识别的代码状态，普通任务只保留最小身份；实施后需求履约复核可先作为高风险/大范围任务的模板试运行，而非立即新建 skill；风险类别和对应审查深度需更明确。UI、可访问性、迁移、真实运行环境和发布后观测的验收仍分散。

## Insights

- 保留现有“原话来源审核”和跨模块追踪表；只在同一张表中按需补入最终代码位置、审查状态和证据身份，不新建平行矩阵。
- 普通任务以 `HEAD + clean/dirty + 命令/场景 + 结果` 识别证据；高风险或跨轮任务再补入 candidate/diff、退出码、时间、必要输出和环境，不强制三套 Git 身份。
- 把“任务履约验真”和“代码质量/安全审查”分开：前者回答做的是不是已批准的事，后者回答实现是否正确安全。
- 计划对每个实质任务补齐精确文件/接口、依赖、负向行为、验证命令、预期结果和窄化完成条件，但不强制所有任务使用两分钟级拆分。
- 以风险驱动流程：认证、授权、用户数据、付费、迁移、外部回调、AI 成本/工具调用和高爆炸半径 API 才升级到历史追踪、调用者映射、攻击场景与独立复核。
- 审查者默认只读，评审结果通过分级、证据、影响、置信度和最小修正归一化；修复必须先经主 Agent 核实并使用已有授权，发生修改后以新快照复验受影响项。
- 不新建重复的“鲜活证据” skill；在现有完成判断中强化交付前最后自检，确保证据晚于最后一次相关代码或运行条件变化。
- 先在 3～5 个 M/L 或高风险任务中试运行“实施后需求履约复核”；只有稳定发现现有流程的漏项后，再决定是否拆成独立 skill。暂不新建覆盖所有代码任务的通用质量审核 skill。
- 将 skill、hook 和其引用脚本当作可执行供应链依赖：记录版本/提交，审查 diff，限制权限，不自动执行不可信仓库指令。
- 对流程本身设指标：需求覆盖率、无证据完成声明、逃逸缺陷、审查误报、证据时效、人工验收驳回率、时间与 token 成本，防止流程只增仪式。

## Strongest objection

多 Agent、多检查表可能制造“已审查”的安全感，却仍共享相同的需求误读；测试也可能与代码一起编码了错误理解。此外，能调用 shell 的外部 `SKILL.md` 本身是可执行供应链输入，若不做来源、最小权限和人工门禁，“增强可靠性”反而可能扩大安全影响面。

## Discarded approaches

| Approach | Why dropped | Date |
|---|---|---|

## Open questions

- 单仓库对自身机制的有效性主张缺少独立实证；引入前应在本项目用历史任务做对照试运行。
- 实施后需求履约复核在 3～5 个 M/L 或高风险任务中的漏项发现率、误报与额外耗时，尚待试运行记录。

## Timeline

- 2026-09-13 - 初始深度调研；覆盖 11 个仓库/官方文档仓库和需求到验收四阶段。
- 2026-09-13 - 经独立 SOL High 审阅和主 Agent 核实，将“完全缺失”修正为“已有能力的字段与触发强化”，改为先试运行履约复核而不立即新建 skill。
