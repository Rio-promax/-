---
topic: project-workspace-organization-skills
created: 2026-10-14
last_verified: 2026-10-14
status: active
depth: deep
related: []
sources:
  - url: https://github.com/ComposioHQ/awesome-claude-skills
    fetched: 2026-10-14
  - url: https://github.com/ComposioHQ/awesome-claude-skills/blob/master/file-organizer/SKILL.md
    fetched: 2026-10-14
  - url: https://www.skills.sh/composiohq/awesome-claude-skills/file-organizer
    fetched: 2026-10-14
  - url: https://github.com/affaan-m/ECC
    fetched: 2026-10-14
  - url: https://github.com/affaan-m/ECC/blob/main/skills/living-docs-governance/SKILL.md
    fetched: 2026-10-14
  - url: https://www.skills.sh/affaan-m/ecc/living-docs-governance
    fetched: 2026-10-14
  - url: https://github.com/tt-a1i/simplify-codebase
    fetched: 2026-10-14
  - url: https://raw.githubusercontent.com/tt-a1i/simplify-codebase/main/SKILL.md
    fetched: 2026-10-14
  - url: https://www.skills.sh/tt-a1i/simplify-codebase
    fetched: 2026-10-14
  - url: https://github.com/Pixel-Process-UG/superkit-agents
    fetched: 2026-10-14
  - url: https://github.com/Pixel-Process-UG/superkit-agents/blob/main/templates/skills/file-organizer/SKILL.md
    fetched: 2026-10-14
  - url: https://github.com/CRangelP/codebase-cleanup
    fetched: 2026-10-14
  - url: https://raw.githubusercontent.com/CRangelP/codebase-cleanup/main/SKILL.md
    fetched: 2026-10-14
  - url: https://docs.github.com/en/copilot/tutorials/customization-library/custom-agents/cleanup-specialist
    fetched: 2026-10-14
  - url: https://github.com/10xChengTu/harness-engineering
    fetched: 2026-10-14
  - url: https://github.com/10xChengTu/harness-engineering/blob/main/skills/harness-engineering-zh/SKILL.md
    fetched: 2026-10-14
---

# GitHub 项目空间整理技能

## Summary

截至 2026-10-14，未找到一项同时具备高关注度、明确宽松许可证，并能完整整理既有仓库文档、参考资料、测试/临时产物、源码和机制边界的单一技能。
Composio `file-organizer` 的所属仓库约 77k Stars，能按用途提出文件夹和移动方案，但没有展示代码调用关系、测试依赖或明确许可证。
MIT 许可且所属仓库约 278.7k Stars 的 ECC `living-docs-governance` 适合给既有文档划定权威职责；`tt-a1i/simplify-codebase`（506 Stars）适合对代码、机制和过时设计记录做证据化只读审计。
直接规划代码仓库目录迁移的 `superkit-agents/file-organizer` 只有约 2 Stars；Star 高低不能替代能力匹配，也不能证明单个 Skill 受到同等使用。

## Findings

| 仓库 / Skill | GitHub 仓库 Stars | 主要能力 | 与本项目的匹配边界 |
|---|---:|---|---|
| ComposioHQ/awesome-claude-skills — `file-organizer` | 约 77k | 按文件用途分组，明确包含项目文件、参考资料、临时/草稿文件；先盘点再提出目录和移动计划，经批准后执行；删除重复项前需确认。Skills.sh 显示约 6.5k 次安装。 | 适合对杂项材料做语义分类和出迁移草案；面向一般个人/项目文件，未提供证明源代码运行消费者、测试导入或文档权威关系的流程。GitHub 仓库页未展示许可证，不能据 Star 数推断可自由再分发。 |
| affaan-m/ECC — `living-docs-governance` | 约 278.7k | MIT 许可；为已有项目文档分配 Constitution、Map、Status、History 四种不重叠职责，保留一个事实的权威来源并建立维护规则。Skills.sh 显示约 2k 次安装。 | 最适合解决项目文档重复、现状/历史混杂、没有清晰入口的问题；不负责把代码、测试文件和临时产物搬到新目录。 |
| tt-a1i/simplify-codebase | 506 | MIT 许可；Survey 模式只读排序候选；追踪运行时消费者、动态注册、持久化格式、接口与设计历史，再决定保留、合并、删除或标记待查。GitHub README 记录了在 973 文件的 Python/TypeScript 仓库执行过全库审计；Skills.sh 显示约 93 次安装。 | 对代码、基础机制和已过时设计记录的冗余审查最贴合；不是参考资料、产品方案、测试样例的文件归类器。 |
| Pixel-Process-UG/superkit-agents — `file-organizer` | 2 | MIT 许可；先评估目录与命名，再设计策略、列出迁移路径、分批移动并在步骤后验证测试；范围包括代码结构、配置和文档。 | 目录迁移方案更接近用户描述，但社区关注度低、模板较通用，需用本项目自己的模块与文档权威规则校正。 |
| 10xChengTu/harness-engineering（中文技能） | 约 102 | 改进 AGENTS.md、docs、测试、Lint 和架构边界；支持中文及多种 Agent 工具。 | 适合建立后续导航和约束，能帮助防止再次混乱；定位是 Agent 工程环境，不是现有目录批量归档。 |

本地 `product/docs/README.md` 已定义五张当前产品基线图、重构执行材料、冲突优先级，以及旧资料应进入 `历史参考/` 的规则；本地还已有 `product/docs/临时/`、`历史参考/`、`assets/`、`思维导图/`、PRD 子目录，源码测试已位于 `product/src/services/core/tests/`。因此后续若做实际整理，应先让技能读取现有权威规则，再输出每项文件的去向和引用影响；仅按扩展名或时间排序会丢掉语义和权威关系。

本轮 `git status --short --branch` 显示大量已修改、删除和未跟踪文件。`CRangelP/codebase-cleanup` 的自动变更流程要求先有干净工作树并把回滚建立在 `git restore --staged --worktree .` 上；它不适合作为当前工作树的直接清理方案。GitHub 官方 `cleanup-specialist` 示例能移除重复/过时的代码与文档内容，但它是 Copilot custom agent 示例，且没有一套文档、测试、临时文件的目录分类迁移规则。

## Insights

- 这个任务实际包含三种不同工作：文档权威与导航、杂项文件归档、代码机制去重；仓库里现成的工具分别覆盖其中一部分。
- 结合适配度，先用 ECC `living-docs-governance` 建立文档职责/索引，再用 `simplify-codebase` 只读审查代码与机制；由 `file-organizer` 或 `superkit` 产出目录迁移表，逐步实施并检查 Markdown 链接、导入、测试和 Git diff，风险比让单个通用技能直接全仓搬迁更低。
- 高 Star 是所属仓库指标。Composio 的 `file-organizer` 在 Skills.sh 上有可观安装量，但所在仓库未展示许可证；ECC 的所属仓库 Star 很高，其具体文档治理技能也有约 2k 次安装；这些数字都不能单独证明它已在类似本项目的迁移任务上验证。

## Strongest objection

最热门的直接文件整理技能有通用目录迁移例子，但未展示源代码/测试依赖的追踪协议，且许可证未能从仓库页确认；最贴近文档治理与源码机制的技能分属不同工作流。没有证据支持一项高 Star 技能可安全包办整个仓库整理。

## Discarded approaches

| Approach | Why dropped | Date |
|---|---|---|

## Open questions

- Composio 仓库及其 `file-organizer` 的许可证没有在所核对的页面中明确展示。
- Stars 与安装量会变化；此处数值是 2026-10-14 查询快照。
- Skills 的 README/正文描述流程，不构成对该技能整理本项目成功率或行为的独立实测。

## User clarification: prioritize physical project-file organization

The user clarified that the main need is sorting project files into the right locations: source, tests, references, intermediate/generated files, and project mechanism material. This changes the ranking from the initial broad comparison.

### Best-fit direct workflow: `pakco77/mishu.skill` → `project-fold`

- GitHub reports 1 Star; repository license is MIT; the skill metadata marks version `0.2.0-candidate`.
- This Chinese-language skill explicitly classifies source, docs, assets, builds, data/intermediate results, run/release materials, references, history, and delete-review candidates. It says to consider ownership and relationships rather than extensions alone; uncertain items stay in Inbox.
- First-time cleanup defaults to read-only inventory plus a concise move plan. It logs each move for reversal, never deletes automatically, and says to inspect `git status --short` before moving Git repositories.
- It proposes a numbered schema such as `00_Context/`, `10_Source/`, `20_Docs/`, and on-demand folders. This is a classification framework, not a mandate to replace this repository's established layout. The project has existing `AGENTS.md` and `product/docs/README.md` rules that should govern any adaptation.
- Sources: https://github.com/pakco77/mishu.skill and https://github.com/pakco77/mishu.skill/blob/main/skills/project-fold/SKILL.md

### High-star but less repository-aware: Composio `file-organizer`

`ComposioHQ/awesome-claude-skills` shows about 77k GitHub stars, and the individual `file-organizer` skill shows about 6.5k installs on Skills.sh. The skill reviews a general workspace, finds duplicates, proposes a folder/move plan, asks before changes, and logs moves. Its examples are general file/workspace organization; the skill does not set out a procedure for tracing code consumers, test references, or canonical-document relationships. The repository page checked did not show a license. Sources: https://github.com/ComposioHQ/awesome-claude-skills/blob/master/file-organizer/SKILL.md and https://www.skills.sh/composiohq/awesome-claude-skills/file-organizer

### Recommendation for this repository

Use `project-fold` as the closest existing checklist to borrow from, not as an automatic bulk mover. Its popularity is low and its target folder scheme is opinionated. Before any actual moves, preserve the repo's current documentation rules and classify with evidence, then produce a per-file destination table. This checkout already has many uncommitted changes, so a broad migration should be planned and reviewed before execution. No install or file movement was performed in this research turn.

## Timeline

- 2026-10-14 - 初次比较 GitHub 项目整理、文档治理和代码简化技能。
