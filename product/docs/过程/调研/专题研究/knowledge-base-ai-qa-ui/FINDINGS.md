---
topic: knowledge-base-ai-qa-ui
created: 2026-09-12
last_verified: 2026-09-12
status: active
depth: deep
related: []
sources:
  - url: https://developers.openai.com/api/reference/resources/vector_stores
    fetched: 2026-09-12
  - url: https://openai.com/solutions/blueprints/knowledge-retrieval/
    fetched: 2026-09-12
  - url: https://learn.microsoft.com/en-in/microsoft-copilot-studio/knowledge-copilot-studio
    fetched: 2026-09-12
  - url: https://learn.microsoft.com/en-us/microsoft-copilot-studio/nlu-generative-answers-sharepoint-onedrive
    fetched: 2026-09-12
  - url: https://workspace.google.com/products/gemini-notebook/
    fetched: 2026-09-12
  - url: https://support.google.com/notebooklm/answer/17003757
    fetched: 2026-09-12
  - url: https://github.com/langgenius/dify-docs/blob/main/en/cloud/use-dify/nodes/knowledge-retrieval.mdx
    fetched: 2026-09-12
  - url: https://docs.anythingllm.com/features/security-and-access
    fetched: 2026-09-12
  - url: https://docs.glean.com/user-guide/assistant/glean-chat/glean-chat-citations/glean-citations
    fetched: 2026-09-12
  - url: https://docs.glean.com/user-guide/assistant/how-glean-accesses-info
    fetched: 2026-09-12
  - url: https://cheatsheetseries.owasp.org/cheatsheets/RAG_Security_Cheat_Sheet.html
    fetched: 2026-09-12
  - url: https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html
    fetched: 2026-09-12
---

# 知识库 AI 问答 UI 与功能

## Summary

第五板块建议命名为“知识问答”，采用“问答工作台 + 资料管理 + 管理设置/测试”结构。普通用户只需选择资料范围、提问、查看引用和原文；切片、检索参数、Prompt、权限与评测收进管理员界面。MVP 的核心不是能聊天，而是权限正确、证据可打开、证据不足会拒答。

## Findings

| 产品 | UI 模式 | 最值得借鉴 |
|---|---|---|
| NotebookLM | 来源栏 + 对话工作区 | 来源范围始终可见，普通用户无需理解 RAG 参数 |
| Glean | 搜索/聊天 + 行内引用与原文预览 | 答案可快速核对，引用不授予额外权限 |
| Microsoft Copilot Studio / SharePoint | 知识源列表 + Agent + 配置 | 使用当前用户身份访问知识，继承来源权限 |
| Dify | 独立知识库 + 应用检索节点 | 管理员可测试切片、命中片段、过滤与重排 |
| OpenAI File Search | Vector Store/API 控制面 | 适合作为底层能力，不宜直接成为普通用户 UI |
| AnythingLLM | Workspace + 对话 + 设置 | 简单的工作区隔离和角色分层 |

推荐第五个一级入口为“知识问答”，内部包含：问答、资料、设置、测试与运行。问答页左侧选择知识库和资料范围，中间连续对话，右侧抽屉展示本轮来源、高亮原文及文档定位。资料页承接已有内容接入、任务和知识库的成果，不复制一套内容系统；显示解析、索引、同步、权限和版本状态。设置与测试默认仅管理员可见。

完整链路是：接入资料，解析结构，按段切割，给每段保存来源、位置、版本和权限，建立关键词与语义索引；提问时先排除无权资料，再检索和重排相关片段，最后让模型仅用这些片段回答并生成系统校验过的引用。证据不足时应正常拒答。

MVP 包含本地文件与现有模块接入、库级权限、自动切片、混合检索、只依据资料回答、行内引用、原文抽屉、证据不足拒答、索引状态、基础反馈和审计。二期增加外部连接器、增量同步、文件级权限、元数据筛选、切片预览、重排调参、测试台和 Prompt 版本。三期再考虑跨库检索、自动回归、红队、异常检测和审批流。

Prompt 应分成不可覆盖的系统安全规则和管理员可配的回答规则。管理员只需配置知识边界、语气、长度、格式、引用要求、冲突及证据不足的处理，不应把一整段自由文本当作唯一安全边界。

权限必须在检索前按当前用户裁剪，并写入索引记录；不能先把敏感片段取回，再让模型隐藏。引用应绑定稳定的 chunk/span 标识、文件版本和页码/章节，不能让模型自由编造。RAG 文档仍可能携带间接提示词注入，因此资料内容只能被视为数据，不能改变系统指令或直接触发外部操作。

## Insights

- 用户真正理解的是“在我选定且有权看的资料里找答案”，不是 RAG、Embedding 或 Top-K。
- 信任主要来自能立即核对原文，引用体验比继续美化答案文风更重要。
- 切片同时影响检索质量与引用粒度，应提供稳定默认值和管理员测试，而不是普通用户调 token。
- 权限、版本和引用首先是数据模型问题，前端无法补救缺失的 chunk 级边界。
- “不知道”是产品能力，不是失败；它用较低的表面回答率换取更少的自信误答。
- 检索召回与答案忠实度必须分开评测。

## Strongest objection

RAG 可能生成带真实引用的错误综合结论，共享知识库还可能成为间接 Prompt Injection 和文档污染入口；若没有检索前权限裁剪、可验证引用和持续评测，它只是更有说服力的错误生成器。

## Discarded approaches

| Approach | Why dropped | Date |
|---|---|---|

## Open questions

- 当前产品是单用户本地优先，首版是否真的需要多角色协作权限，需在正式 PRD 中定界。
- 支持的首批文件格式、最大文件大小、模型供应商和成本上限尚未确定。

## Timeline

- 2026-09-12 - initial entry
