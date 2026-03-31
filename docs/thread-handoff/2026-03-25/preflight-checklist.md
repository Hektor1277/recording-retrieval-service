# Preflight 预检清单

## 新线程开始前必须确认
- 当前目录是 [app](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app)
- 当前分支仍是 `codex/retrieval-pipeline-v1`
- `git status --short` 没有意外代码改动
- `.venv` 可用，且 `pytest` 能通过
- 本地配置文件未丢失：
  - [platform-search.local.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/config/platform-search.local.json)
  - [llm.local.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/config/llm.local.json)
- 如要继续 live 检索，网络至少应可访问：
  - `www.youtube.com`
  - `api.bilibili.com`
  - `search.bilibili.com`
  - `www.bing.com`
- 如要继续 `Bilibili` 强上下文链路，确认 `bilibili-storage-state.json` 仍可用

## 推荐检查命令
```powershell
cd 'E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app'
git status --short
& '.\.venv\Scripts\python.exe' -m pytest '.\tests' -q
& '.\.venv\Scripts\python.exe' '.\scripts\audit_parent_work_links.py' --output '.\output\parent_work_eval_schumann_op54_link_audit_resume.json'
```

## 进入实现前的门禁
新线程开始后，先把以上检查结果告诉用户，再让用户确认：
- 环境仍然可用
- 网络与权限没有新阻塞
- 可以继续进入实现

在用户确认 preflight 完成前，不要直接进入新的代码改动。
