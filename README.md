# Recording Retrieval Service

本目录承载独立工具 `Recording Retrieval Service`，中文名统一为“版本自动检索工具”。

它同时服务两种入口：

- `Contract Surface`（合同面）：供父项目 owner 通过本地 HTTP 协议调用。
- `Standalone Surface`（独立面）：工具自身提供 `Web UI`（网页界面），用户可直接启动并手工提交检索任务。

## 目录用途

- 存放工具自己的源码、依赖、缓存、日志、下载产物和打包脚本。
- 不直接读写主项目的 `apps/`、`packages/`、`data/` 或 `apps/site/public/`。
- 与父项目的唯一正式集成面仍是 [`PROTOCOL.md`](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/PROTOCOL.md) 定义的本地 HTTP 协议。

## 阅读顺序

1. [`PROJECT_CONTEXT.md`](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/PROJECT_CONTEXT.md)
2. [`PROTOCOL.md`](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/PROTOCOL.md)
3. 本文件

## 当前实现

- 后端：`Python + FastAPI`（快速接口框架）
- 启动模式：
  - `python -m app.main --mode service`
  - `python -m app.main --mode ui`
- 默认地址：`http://127.0.0.1:4780`
- 协议版本：`v1`
- 当前检索器：`StubRetriever`（占位检索器），用于联调合同、状态机和 UI

## 本地开发

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m app.main --mode service
.\.venv\Scripts\python.exe -m app.main --mode ui
```

也可以使用包装脚本：

```powershell
.\start-service.cmd
.\start-ui.cmd
.\install-windows.cmd
.\build-portable.cmd
.\scripts\start-service.cmd
.\scripts\start-ui.cmd
```

推荐优先双击根目录的 `start-ui.cmd` 或 `start-service.cmd`。

## 目录结构

```text
tools/recording-retrieval-service/
  README.md
  PROJECT_CONTEXT.md
  PROTOCOL.md
  pyproject.toml
  app/
    main.py
    models/
    services/
    ui/
  tests/
  scripts/
  packaging/
  cache/
  logs/
  downloads/
```

## Standalone UI

独立 UI 首版只提供：

- 单条版本检索表单
- 原始请求 JSON 预览
- 任务状态轮询
- 终态结果展示

不提供：

- owner 候选审查
- 项目数据写回
- batch 模板解析

## Windows 便携分发

便携包脚本位于 `packaging/build-portable.ps1`，当前策略是：

- 使用 `PyInstaller onedir`（单目录可执行包）生成 `recording-retrieval-service.exe`
- 附带 `start-service.cmd` 与 `start-ui.cmd`
- 每次输出新的发布目录到 `dist/releases/`
- 同时生成一个可直接交付的 `dist/recording-retrieval-service-portable-<timestamp>.zip`

## owner 调用前提

- 服务已启动
- `GET /health` 可达
- `protocolVersion === "v1"`

## 非目标

- 不直接修改项目数据文件
- 不直接写入 owner 的 `AutomationRun`
- 不直接维护候选审查状态
- 不直接解析批量导入模板文本
