# 核心服务代码地图

此处是产品核心服务的代码入口。新增文件先按职责进入现有包；不要为一个场景再造一层 `base_foundation / model_wrappers / business_modules` 目录。

桌面壳是并列服务，源码位于 [`../desktop-shell/`](../desktop-shell/)；其 Release 产物保存在 `product/local/desktop-shell/`，不要混入 Python 核心服务包。

| 层次 | 当前位置 | 放入什么 |
|---|---|---|
| 基础概念 | `app/domain/` | 与平台、模型和界面无关的领域对象、状态与规则 |
| 能力接口 | `app/ports/`、`src/packages/contracts/` | Python 侧能力接口及跨端共享契约；外部实现不得倒灌进接口 |
| 外部实现 | `app/adapters/` | 来源采集、ASR、摘要等具体服务或模型调用；按能力继续使用 `sources/`、`asr/`、`summary/` |
| 平台连接 | `app/platforms/` | 平台账号、授权、连接状态与平台配置；具体抓取实现进入 `adapters/sources/` |
| 业务能力 | `app/knowledge/`、`app/archive/` | 知识处理、检索和归档规则；业务流程编排进入 `app/workflows/` |
| 数据与交付 | `app/db/`、`app/api/`、`app/ui/` | 持久化、HTTP 接口及用户界面 |
| 工程配套 | `migrations/`、`tests/`、`tools/` | 数据库迁移、正式测试、核心服务专用的开发工具 |

依赖方向以领域概念和接口为内层：`api/ui → workflows/业务能力 → ports/domain`；`adapters/db` 实现外部能力，由入口装配。模型调用、第三方 SDK、平台登录细节应留在外部实现层，不进入 `domain/`。

当前 `app/knowledge/siliconflow_retrieval.py` 同时体现检索业务与具体模型服务，属于后续代码调整时要拆清的边界；目前保留原路径，避免仅为目录整齐破坏导入。根层 `tools/` 的探测与基准脚本也须先核对调用路径，再决定是否归入本目录 `tools/`。修改包路径时同步更新导入、启动配置和引用文档。

RAG 索引与关系入口：`app/knowledge/ask_index.py` 管理可重建的文本／向量索引与来源片段；`app/db/rag_store.py` 持有主题、正式细标签、开发者审核审计和 SQLite 关系投影；`app/api/main.py` 装配 `/dev/rag` 开发接口，页面位于 `app/ui/dev-rag.*`。对应 schema 迁移进入 `migrations/versions/`；归档与原始内容仍是来源依据，不把长文本复制进关系投影。
