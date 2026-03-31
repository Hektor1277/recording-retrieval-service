# 环境重置检查单

本文件对应 `thread-handoff`、`permission-env-autopilot`、`project-preflight-bootstrap` 三个 Skill 的落地结果。

## 一、线程恢复后的最低动作
1. 打开 [START_NEW_THREAD.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/docs/thread-handoff/2026-03-30/START_NEW_THREAD.md)
2. 进入 [app](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app)
3. 用 `.venv` 跑 `pytest`
4. 用 `.venv` 跑舒曼钢协完整评估

## 二、环境陷阱

### 陷阱 1：跑错 Python
症状：
- `playwright` 导入失败
- `browser rescue` 不执行
- `versionFinalHit` 异常大幅下降

修复：
- 改用 `.venv\Scripts\python.exe`

### 陷阱 2：误信极低 live 结果
症状：
- 结果突然从接近历史最好掉到极低水平
- 但单测未同步大面积失败

修复：
- 先核对解释器
- 再看 `access` 报告中是否存在 `Bilibili browser` 路径缺失

### 陷阱 3：把手工交接包当成自动导出包
症状：
- 去查找 `.codex-handoff/current/manifest.json`
- 去跑不存在的 `export_handoff.py`

修复：
- 当前仓库没有这些脚本
- 直接用本目录下的手工交接文档

## 三、需要保留的现有文件
- [platform-search.local.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/config/platform-search.local.json)
- [llm.local.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/config/llm.local.json)
- [bilibili-storage-state.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/config/bilibili-storage-state.json)

## 四、何时需要用户介入
仅在以下情况才需要：
- `.venv` 中 `playwright` 也不可用
- `bilibili-storage-state.json` 丢失或已失效
- 本地浏览器环境被系统策略拦截

默认情况下，新线程可直接继续，不需要用户额外操作。
