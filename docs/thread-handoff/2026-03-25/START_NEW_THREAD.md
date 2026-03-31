# 新线程启动指引

## 先读这些文件
1. [manifest.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/.codex-handoff/current/manifest.json)
2. [project_context.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/.codex-handoff/current/project_context.md)
3. [progress.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/.codex-handoff/current/progress.md)
4. [decisions.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/.codex-handoff/current/decisions.md)
5. [next_actions.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/.codex-handoff/current/next_actions.md)
6. [risks_open_questions.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/.codex-handoff/current/risks_open_questions.md)
7. [environment_bootstrap.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/.codex-handoff/current/environment_bootstrap.md)
8. [preflight-checklist.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/docs/thread-handoff/2026-03-25/preflight-checklist.md)

## 当前判断
- 实际工作仓库是 [app](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app)
- 当前分支是 `codex/retrieval-pipeline-v1`
- 最新已推送提交是 `262a0a5e28dce83bcef9751c3a9eb05c174b96ee`
- 当前代码基线已把父项目收录优先级落实到检索排序：
  `独立全量 > 多分P/合集 > 第一乐章`
- 当前工作区在本线程结束时除交接目录外应为干净；新线程开始后先跑一次 `git status --short`

## 先执行的验证
```powershell
cd 'E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app'
git status --short
& '.\.venv\Scripts\python.exe' -m pytest '.\tests' -q
& '.\.venv\Scripts\python.exe' '.\scripts\audit_parent_work_links.py' --output '.\output\parent_work_eval_schumann_op54_link_audit_resume.json'
```

## 新线程第一目标
- 继续攻真实长尾 `recall_miss`
- 优先看：
  - `Grinberg / Eliasberg 1958`
  - `Richter / Ferencsik 1954`
  - `de Lara / Whyte 1951`
  - `Kempff / Dorati 1959`
- 在代码层，优先落点：
  - [pipeline.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/pipeline.py)
  - [http_sources.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/http_sources.py)
  - [parent_work_eval.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/parent_work_eval.py)

## 重要说明
- 父项目舒曼钢协的原始真值链接在 `2026-03-25` 审计时仍是 `20/20 available`，所以当前主问题不是死链，而是长尾召回和少量历史真值可疑性。
- 仓库内没有 `thread-handoff` skill 文档提到的自动导出/加载脚本，本次交接包为手工维护。
- 新线程开始后，要先完成 `preflight` 并让用户确认，再进入新的实现。
