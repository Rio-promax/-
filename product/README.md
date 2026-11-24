# 多源内容知识库

这是一个本地优先的多来源内容理解与知识归档产品。当前以 Windows 电脑端和 Bilibili 视频总结闭环为重点，未来按统一适配框架扩展到小红书、抖音、YouTube、网页、本地文件与手机端采集。

目标产品结构采用四个一级区域：**内容接入区、任务区、知识库、设置**。当前代码仍是“开始与任务、内容库、设置”三个入口，属于待重构的信息架构差距。

## 产品目录边界

| 目录 | 职责 |
|---|---|
| `docs/` | 需求正本、过程方案、调研依据与验收材料 |
| `src/` | 正式源码、测试和迁移；`services/core/` 是 Python 后端，`services/desktop-shell/` 是桌面壳源码 |
| `local/` | 不进入 Git 的数据库、知识归档、模型、日志、编译产物与实验数据 |
| `.venv/` | 当前启动脚本使用的 Python 环境 |

`pyproject.toml`、启动脚本和本说明保留在产品根层，因为现有安装与启动命令以此处为工作目录。桌面壳源码从 `local/experiments-platform-shell/login-shell/` 归入 `src/services/desktop-shell/`；现有 Release 可执行文件在 `local/desktop-shell/`。

## 产品基线

当前产品、设计和开发共同基线为 [产品架构五图](docs/README.md)：

1. 产品全景决策总览
2. 功能能力结构
3. 信息对象结构
4. 页面与导航结构
5. 状态与产品缺口

旧版产品愿景、需求细节、进度与任务材料已移入 `docs/历史参考/2026-08-29-XMind产品基线切换/`，只用于追溯。

## 本地运行

在 `product` 目录安装测试依赖并运行测试：

```powershell
python -m pip install ".[test]"
python -m pytest -q
```

启动本地服务：

```powershell
python -m uvicorn app.api.main:app --app-dir src/services/core --host 127.0.0.1 --port 8765
```

随后在浏览器打开 `http://127.0.0.1:8765/`。本地数据库、模型和归档运行数据位于 `local/`，不会进入 Git。

## 共享多账号服务

共享服务使用独立认证数据库和账号数据目录；它不读取或迁移本地单用户数据库。
公开注册关闭，管理员在服务端运行：

```powershell
python -m app.api.shared create-account --username alice
python -m uvicorn app.api.shared:app --app-dir src/services/core --host 127.0.0.1 --port 8766
```

默认认证库和账号数据位于 `local/product-auth.db` 与 `local/accounts/`。可用
`PRODUCT_AUTH_DATABASE_URL` 和 `PRODUCT_ACCOUNT_DATA_ROOT` 覆盖。产品登录只在 HTTPS
请求下签发会话 Cookie；HTTPS 反向代理须向 Uvicorn 传递可信的 `X-Forwarded-Proto`，
并将 `--forwarded-allow-ips` 限定为代理地址。`PRODUCT_ALLOW_INSECURE_HTTP=1` 仅用于隔离的本机测试，
不得用于公网服务。

`app.api.main:app` 仍是本地单用户入口；`app.api.shared:app` 是独立的账号服务入口。
