# 环境恢复说明

## 当前已知环境
- OS：Windows
- Shell：PowerShell
- Python：`3.13.5`
- 虚拟环境：`app\.venv`
- 浏览器：本机 `Microsoft Edge`，当前用于 `Playwright`（浏览器自动化）

## 配置文件
- 本地平台配置：
  [platform-search.local.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/config/platform-search.local.json)
- 示例配置：
  [platform-search.example.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/config/platform-search.example.json)

## Bilibili 相关
- `storage state` 已存在于本地，但属于敏感文件，不应提交
- `Cookie` 可通过脚本自动同步
- `userAgent` 建议保持本机真实浏览器值，不要回退到示例占位字符串

## 缺失的辅助脚本
- 当前仓库不存在 `thread-handoff` 技能说明中提到的导出/加载脚本
- 当前仓库也不存在 `project-preflight-bootstrap` 技能说明中提到的 `generate_preflight_checklist.py`
- 因此本交接依赖手工文档，不依赖脚本恢复
