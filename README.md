# 多源内容知识库项目

这是一个本地优先的多源内容分析与知识库项目。产品开发、文档依据、工具和归档按职责分开。

## 工作区目录树

- [`product/`](product/README.md) — 产品工程。安装、启动和测试命令见产品入口。
  - [`docs/`](product/docs/README.md) — 产品文档入口，内有细分目录和落盘规则。
    - `基线/` — 产品结构、需求正本、路线、执行规则和[当前进度台账](product/docs/基线/当前进度台账.md)。
    - `过程/` — 按月的方案与实施记录，以及调研、笔记、样例、审计和附件。过程图片统一落到 `过程/assets/`，现有 `docs/assets/` 有历史散放的附件。
    - `临时/`、`历史参考/` — 未定稿或已替代的材料，按 [AGENTS.md](AGENTS.md) 的默认排除规则读取。
  - `src/` — 正式源码、测试、迁移和共享契约。
    - [`services/core/`](product/src/services/core/README.md) — Python 核心服务。新增代码按代码地图的职责归位，测试、迁移和服务专用工具也在此分支。
    - [`services/desktop-shell/`](product/src/services/desktop-shell/) — Windows 桌面壳源码。
    - [`services/mobile-shell/`](product/src/services/mobile-shell/README.md) — 移动端壳源码和构建入口。
    - [`packages/contracts/`](product/src/packages/contracts/) — 跨端共享契约。
  - `local/` — 运行数据、日志、编译产物和实验资料。按需定位具体数据。
  - `.venv/` — Python 环境。
- [`skills/`](skills/README.md) — 可复用的产品架构五图技能及其制图规范。
- [`tools/`](tools/) — 仓库层的探测和批量基准脚本。核心服务专用工具放入核心服务的 `tools/`。
- 根层 `local/` — 当前存有后端日志。产品运行数据的归位入口见 `product/local/`，日志只在排查对应问题时读取。
- `archive/` — 历史归档，按 [AGENTS.md](AGENTS.md) 的默认排除规则读取。
- 根层点号目录 — Git 与工具入口、协作和执行记录，由使用它们的工具管理。涉及相应工具时按需查看。

## 查找与落盘

- 已知路径时直接打开目标。需要定位时，从上面的树选择相关分支，打开该分支的入口，找到正本或目标包即停止展开。
- 新增文件先按职责和生命周期选分支，再看该分支的落盘规则。已有文件的位置只能作为线索。优先用现有目录，新增子目录应有独立的版本、备份或忽略规则。
- 新增未被现有导航覆盖的文件或目录，或调整目录职责与入口时，同步更新最近一层的引导文件。顶层入口变化时更新本页。
