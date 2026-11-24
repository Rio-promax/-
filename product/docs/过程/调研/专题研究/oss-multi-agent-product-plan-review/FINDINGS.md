---
topic: oss-multi-agent-product-plan-review
created: 2026-09-16
last_verified: 2026-09-16
status: active
depth: deep
related: [github-agent-skill-lifecycle-review]
sources:
  - url: https://github.com/luigiluft/crossfire
    fetched: 2026-09-16
  - url: https://github.com/zmustafa/MultiChat
    fetched: 2026-09-16
  - url: https://github.com/zmustafa/MultiChat/blob/main/SECURITY.md
    fetched: 2026-09-16
  - url: https://github.com/addyosmani/adverse
    fetched: 2026-09-16
  - url: https://github.com/addyosmani/adverse/blob/main/LICENSE
    fetched: 2026-09-16
  - url: https://github.com/antonbabenko/deliberation
    fetched: 2026-09-16
  - url: https://github.com/antonbabenko/deliberation/blob/master/TECHNICAL.md
    fetched: 2026-09-16
  - url: https://github.com/skwid138/opencode-council
    fetched: 2026-09-16
  - url: https://github.com/mayankmankhand/llm-peer-review
    fetched: 2026-09-16
  - url: https://github.com/ng/adversarial-review
    fetched: 2026-09-16
  - url: https://github.com/poteto/noodle
    fetched: 2026-09-16
  - url: https://github.com/microsoft/autogen/blob/main/README.md
    fetched: 2026-09-16
  - url: https://github.com/langchain-ai/langgraph
    fetched: 2026-09-16
  - url: https://github.com/crewAIInc/crewAI
    fetched: 2026-09-16
  - url: https://github.com/ag2ai/ag2
    fetched: 2026-09-16
  - url: https://github.com/karpathy/llm-council
    fetched: 2026-09-16
---

# 可直接改造的开源多 Agent 产品方案审核工具

## Summary

没有一个已验证项目开箱即同时满足冻结 Scale 材料、跨厂商独立审核、结构化问题卡、确定性聚合、保留分歧和人工批准。最小改造路线是以 `luigiluft/crossfire` 为 Scale 的多模型审阅入口；需要完整本地审阅界面时选 `zmustafa/MultiChat`；若确定性聚合是第一要求，复用 `addyosmani/adverse` 的校验和聚合内核。`antonbabenko/deliberation` 是适合接入 Agent 的 MCP 备选。AutoGen、LangGraph、CrewAI 和 AG2 是框架，不是可直接使用的产品方案审核系统。

## Findings

| 候选 | 可直接利用的能力 | 主要缺口 | 改造量 | 结论 |
|---|---|---|---|---|
| `luigiluft/crossfire` | 直接审查 `plan.md`；通过 OpenRouter 跨厂商盲审；展示原始意见和分歧；可输出 JSON | 最后综合仍是 LLM judge；缺严格问题卡 schema、材料哈希和人工批准记录 | 低～中 | **Scale 首选试点** |
| `zmustafa/MultiChat` | 完整本地 Web 应用；多厂商盲审、匿名评议、少数报告、合成复审、JSON 审计导出 | 应用面较大；模型赞同不是人工批准；聚合不是确定性代码 | 中 | **需界面时首选** |
| `addyosmani/adverse` | 独立首轮、交叉质疑、JSON 校验、确定性聚合、争议/单方问题保留、多格式输出 | 默认一次只配一个 Agent 命令，三角色不等于三个厂商；默认面向代码 | 中 | **最值得复用的聚合内核** |
| `antonbabenko/deliberation` | MCP 服务；计划审阅专家；OpenRouter/兼容 API/CLI 适配；有界限轮次和共识状态机 | 当前引擎已移除匿名同伴复审；输出不是统一问题卡 JSON；需补少数报告和人工裁决 | 低～中 | **MCP 路线备选** |
| `skwid138/opencode-council` | 可向多个 provider 子会话并发同一问题；支持设计文档审核、quorum 和超时 | 绑定 OpenCode；聚合仍是温度 0 的 LLM，非确定性代码；默认审核权限偏宽 | 低（已用 OpenCode）/中高 | 条件备选 |
| `mayankmankhand/llm-peer-review` | 明确支持产品规格、研究和计划；Claude↔ChatGPT/Gemini 多轮辩论；有用户实施批准 | 主要是双边辩论，不是隔离的多厂商小组；Windows 辩论命令依赖 Bash/WSL；安装器会带入更大开发流程 | 低～中 | 可借用部分命令，不整套导入 |
| `ng/adversarial-review` | 跨厂商 lane、按审核者保留产物、结构化 finding、明确争议/延后项 | 强绑 diff/PR，默认可修代码与发布评论；证据逻辑偏代码而非产品假设 | 中高 | 借鉴协议，不直接采用 |
| `poteto/noodle` | 附带计划对抗审阅 skill；可调对立 provider CLI | 整体是实施/工作树/合并调度器；为 Scale 审核引入整套成本过高 | 整体高 | 只借鉴 skill |
| `LangGraph` / `CrewAI` / `AG2` | 状态机、任务、结构化输出、人工中断等组件 | 冻结材料、审核协议、分歧账本和聚合规则均需自建 | 高 | 不符合“尽量不重造” |

首选方案是以固定 commit 的 Crossfire 试点，使用其 `review plan.md --type plan --panel` 路径。Scale 在审核前导出一份不可变材料包；Crossfire 负责跨厂商分发和原始意见收集；本地适配层将输出校验为统一问题卡，并用确定性规则保留支持、反对、单方严重发现和不完整审核。不应使用 Crossfire 的单模型 `decide` 路径代替跨厂商 panel。

需要一个人可直接操作的本地审核站时，MultiChat 更接近成品。它已有盲审、同伴评议、少数报告和审计导出，但必须另加 Scale 材料导入、人工批准记录和最小 provider 到齐规则。其安全文档将当前能力界定为 localhost/可信团队边界，首版应关闭工具调用，只允许审查文本和 API 模型调用。

Scale 接入的建议契约：

1. Scale 输出含 `packet_id`、版本、SHA-256、S/M/L、用户问题、原始证据、已确认需求、假设、范围/排除项、方案、备选、约束、验收、待决定项和审核 rubric 的冻结包。
2. 每个审核者收到字节一致的材料和 rubric，在新上下文中完成第一轮，不可看到同伴意见；记录真实 provider/model。
3. 每条问题卡包含 `finding_id`、材料身份、需求引用、审核者/provider/model、视角、严重级、类别、主张、触发场景、用户影响、证据、假设、最小修正、验证方式和置信依据。
4. 只在所有首轮完成后启动可选的交叉质疑；使用稳定 finding ID 记录 `support`、`challenge`、`needs_evidence` 或 `abstain` 及理由。
5. 聚合器以代码计算独立厂商支持数，保留原卡、反对证据和单方严重问题；语义归组可由 LLM 建议，但不得静默删除原始卡。
6. 用户批准记录 `approve/revise/reject`、操作者、时间和材料哈希；材料变更后旧批准失效。模型共识只是建议，不授权实施。

## Insights

- 可复用的主体是多模型分发和结果展示；Scale 真正需新增的是冻结包契约、问题卡 schema、确定性分歧账本和人工决定记录。
- 多角色与多厂商是两种不同的多样性；本地方案应同时保留产品价值、用户流程、可实施性和反方视角，并至少在 M/L 级使用不同厂商。
- 确定性调度或温度 0 不等于确定性聚合；只有代码化规则才能稳定保留分歧。
- 少数报告必须保留不可变原始意见；仅在 LLM 摘要中写“有人不同意”不足以审计。
- MultiChat 自身的基准提醒，完整辩论未必比一次综合更好；交叉质疑应只在 L 级、高风险或重大分歧时启用。

## Strongest objection

首选 Crossfire 仍需本地增加 schema 校验和确定性聚合，因此是可复用底座而非开箱即完成的成品。若不接受这部分改造，MultiChat 更接近现成系统，但需承担更大运维面和安全边界。

## Discarded approaches

| Approach | Why dropped | Date |
|---|---|---|
| Microsoft AutoGen | 当前 README 明确处于 maintenance mode，并指向 Microsoft Agent Framework | 2026-09-16 |
| karpathy/llm-council | 维护者表明不支持，且未核实清晰的可复用许可证 | 2026-09-16 |
| 直接用 LangGraph/CrewAI/AG2 重建 | 只提供组件，仍要重做本次最关键的审核协议和应用 | 2026-09-16 |

## Open questions

- Crossfire、MultiChat 与 adverse 尚未在当前 Windows 工作区实际安装运行，原生 Windows 子进程、编码和长中文材料支持需用同一份小型 Scale 包验证。
- 候选项目多数规模较小，没有独立企业级可靠性证据；应固定 commit 试点而非直接长期依赖 `main`。

## Timeline

- 2026-09-16 - 完成可直接改造的开源多 Agent 产品方案审核工具比较，建议 Crossfire 试点、MultiChat 界面备选、adverse 聚合内核。
