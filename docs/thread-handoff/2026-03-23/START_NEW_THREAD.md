# 新线程启动指引

## 先读这些文件
1. [manifest.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/.codex-handoff/current/manifest.json)
2. [project_context.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/.codex-handoff/current/project_context.md)
3. [progress.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/.codex-handoff/current/progress.md)
4. [decisions.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/.codex-handoff/current/decisions.md)
5. [next_actions.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/.codex-handoff/current/next_actions.md)
6. [risks_open_questions.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/.codex-handoff/current/risks_open_questions.md)
7. [environment_bootstrap.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/.codex-handoff/current/environment_bootstrap.md)
8. [preflight-checklist.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/docs/thread-handoff/2026-03-23/preflight-checklist.md)

## 当前判断
- 实际工作仓库是 [app](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app)
- 当前分支是 `codex/retrieval-pipeline-v1`
- 最新已推送提交是 `333c8382a9ffb3382a9be90accb08f3a69b0af34`
- 当前工作区在本线程结束时应为干净；新线程开始后先跑一次 `git status --short`

## 先执行的验证
```powershell
cd 'E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app'
git status --short
& '.\.venv\Scripts\python.exe' -m pytest '.\tests' -q
& '.\.venv\Scripts\python.exe' '.\scripts\real_data_regression.py' --only annie-full annie-no-group gieseking-full bernstein-fantastique-conductor-only heifetz-lead-only karajan-alpine-full --output '.\output\real_data_focus_resume.json' --access-report '.\output\real_data_focus_resume_access.json'
```

## 新线程第一目标
- 继续攻 `heifetz-lead-only`
- 然后处理长批次全量回归里仍不稳定的 `bohm-no-date`、`bohm-conductor-only`、`arrau-no-date`
- 保持 `Bilibili` 链路配置闭环，不要破坏 `storage state + Cookie + userAgent` 这套组合

## 重要说明
- 本仓库缺少 `thread-handoff` 技能说明里提到的 `scripts/export_handoff.py`、`scripts/load_handoff.py`、`generate_preflight_checklist.py`
- 本次交接包是手工更新的，不是脚本导出产物
- 新线程仍要先完成一次人工 `preflight`（预检）确认，再进入继续开发
