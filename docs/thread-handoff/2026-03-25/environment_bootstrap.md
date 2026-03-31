# 环境恢复说明

## 当前环境
- OS：Windows
- Shell：PowerShell
- Python：`3.13.5`
- 虚拟环境：`app\.venv`
- 浏览器自动化：本机 `Microsoft Edge` + `Playwright`

## 关键本地配置
- [platform-search.local.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/config/platform-search.local.json)
- [llm.local.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/config/llm.local.json)
- [bilibili-storage-state.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/config/bilibili-storage-state.json)

## 已知环境注意点
- 默认系统 `python` 不保证带 `pytest`，实际工作统一使用：
  `& '.\.venv\Scripts\python.exe'`
- PowerShell 不支持 `&&`，多条命令要分行执行。
- 仓库缺少 `thread-handoff` skill 文档里提到的：
  - `scripts/export_handoff.py`
  - `scripts/load_handoff.py`
  - `scripts/generate_env_reset_checklist.py`
  - `project-preflight-bootstrap/scripts/generate_preflight_checklist.py`
  所以本次交接包是手工维护，不依赖仓库内自动导出脚本。
- 大范围扫描时会遇到：
  `warning: could not open directory 'tmp-pytest-wrapper/': Permission denied`
  这是已知噪声，不是当前主阻塞。

## Bilibili 上下文
- `storage state + Cookie + userAgent` 仍是当前稳定配置闭环。
- 如需重新抓取登录态，可用：
  [capture_bilibili_storage_state.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/scripts/capture_bilibili_storage_state.py)
- 如需从 `storage state` 同步 `Cookie`，可用：
  [sync_bilibili_cookie_from_storage_state.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/scripts/sync_bilibili_cookie_from_storage_state.py)
