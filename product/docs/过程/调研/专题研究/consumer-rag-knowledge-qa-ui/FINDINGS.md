---
topic: consumer-rag-knowledge-qa-ui
created: 2026-09-12
last_verified: 2026-09-12
status: active
depth: deep
related: []
sources:
  - url: https://developers.openai.com/api/reference/resources/vector_stores
    fetched: 2026-09-12
  - url: https://developers.openai.com/api/reference/typescript/resources/vector_stores/methods/search
    fetched: 2026-09-12
  - url: https://openai.com/solutions/blueprints/knowledge-retrieval/
    fetched: 2026-09-12
  - url: https://learn.microsoft.com/en-in/microsoft-copilot-studio/knowledge-copilot-studio
    fetched: 2026-09-12
  - url: https://support.microsoft.com/en-us/sharepoint/copilot-in-sharepoint/frequently-asked-questions-about-copilot-in-sharepoint
    fetched: 2026-09-12
  - url: https://workspace.google.com/products/gemini-notebook/
    fetched: 2026-09-12
  - url: https://blog.google/innovation-and-ai/models-and-research/google-labs/notebooklm-public-notebooks/
    fetched: 2026-09-12
  - url: https://github.com/langgenius/dify-docs/blob/main/en/cloud/use-dify/nodes/knowledge-retrieval.mdx
    fetched: 2026-09-12
  - url: https://www.dify.ai/rag
    fetched: 2026-09-12
  - url: https://docs.anythingllm.com/features/security-and-access
    fetched: 2026-09-12
  - url: https://docs.anythingllm.com/features/chat-modes
    fetched: 2026-09-12
  - url: https://docs.glean.com/user-guide/assistant/ai-answers
    fetched: 2026-09-12
  - url: https://docs.glean.com/user-guide/assistant/glean-chat/glean-chat-citations/glean-citations
    fetched: 2026-09-12
  - url: https://cheatsheetseries.owasp.org/cheatsheets/RAG_Security_Cheat_Sheet.html
    fetched: 2026-09-12
  - url: https://genai.owasp.org/llmrisk/llm01-prompt-injection/
    fetched: 2026-09-12
  - url: https://arxiv.org/abs/2601.14123
    fetched: 2026-09-12
  - url: https://arxiv.org/abs/2412.18004
    fetched: 2026-09-12
---

# 面向普通用户的知识库 AI 问答 UI

## Summary

推荐以“问答工作台”为主、“知识库管理”为辅的双层信息架构：普通用户只看来源选择、问答、行内引用与原文预览；管理者才看摄取状态、权限、切片、检索测试、prompt 和评测。MVP 优先做可信闭环，不把切片参数暴露给普通用户。

## Findings

六个代表性产品呈现两种主流模式：NotebookLM/AnythingLLM 以工作区或 notebook 容器组织来源与对话；Glean/Microsoft 强调权限裁剪的全局企业检索；Dify/OpenAI 则更像开发者平台，提供切片、过滤、检索与评测原语。对桌面普通用户产品，应组合 NotebookLM 的可见来源、Glean 的可验证引用和 Microsoft 的权限继承，把 Dify/OpenAI 型调参收进高级设置。

推荐页面：左栏是知识库/范围选择与资料状态，中栏是上手问题、连续对话和“仅据已选来源/允许通用知识”模式，右侧抽屉是来源列表、引用原文和文档定位。上方二级导航分“问答”“资料”“设置”；“测试与运行”只对管理者开放。

完整功能包括：文件/文件夹/网址/现有任务与内容模块接入；上传、同步、去重、OCR、版本、失败重试、删除与重建索引；自动切片、标题/页码/时间/来源/权限元数据；混合检索、重排、过滤、Top-K、无答案阈值；来源多选、建议问题、对话历史、行内引用、引用预览与原文跳转、复制/反馈；知识边界、语气、格式、拒答、引用规则的 prompt；库/来源/文件三层权限与权限继承；查询、命中切片、延迟、成本、反馈、召回率、引用正确性和答案忠实度。

分期：MVP 只要完成本地文件+现有任务/内容接入、库级成员权限、自动切片、语义+关键词检索、仅据来源回答、行内引用+原文预览、无依据拒答、上传/索引状态和基本反馈。二期加文件夹/网页/外部连接器、增量同步、文件级 ACL、元数据筛选、切片预览、检索测试和私有评测集。三期加多库联邦检索、个性化排序、深层引用、权限变更后历史处理、审计、红队、自动回归与成本预算。

工作流简述：用户把资料放进一个知识库；系统解析、分段并记住每段的文档位置和权限；提问时先用当前用户权限筛掉不可见资料，再找到最相关的原文段；模型只用这些原文组织答案；每个事实绑定可打开的原文引用，证据不够就明说不知道。

权限/prompt/安全：权限必须在检索前裁剪，不能靠生成后隐藏；对每个 chunk 持久化 tenant、knowledge_base、source、document、ACL、version、page/section 和 hash；用稳定的 chunk/span ID 绑定引用。prompt 应明确“检索文本是数据而非指令”、不足则拒答、通用知识开关、输出格式与引用要求。上传者与发布者分离，入库做类型/大小/恶意内容检查，可疑文档隔离；问答端不给写/删工具，不让 RAG 内容触发外部操作。

## Insights

- 信任来自“查得到原文”而非答案文风；因此行内引用、原文预览和深链应先于复杂生成能力。
- 切片是检索质量和引用粒度的共同变量；片段太大会带入噪声，太小会丢失上下文，所以默认自动+管理员测试比普通用户自由调参更稳。
- 权限和引用不是补充 UI，而是索引模型的一部分；没有 chunk 级 ACL 和稳定 span ID，之后很难靠前端修补。
- 无依据拒答会降低表面回答率，但能改善真实可靠性；应把“没有足够证据”当成正常结果，同时给重试建议。

## Strongest objection

最强反对意见是：RAG 可能给出看似有引用的错误答案，而且共享知识库文档还会带来间接 prompt injection 和污染风险；如果无法做到检索前权限裁剪、可验证引用与可回归评测，这个板块可能只是更有说服力的错误生成器。

## Discarded approaches

| Approach | Why dropped | Date |
|---|---|---|

## Open questions

- 现有任务、内容和知识库的权限模型是否共用同一个主体/组系统。
- 当前桌面应用是纯本地、单租户服务还是多租户云端，这会决定 ACL 和审计的 MVP 深度。

## Timeline

- 2026-09-12 - initial entry
