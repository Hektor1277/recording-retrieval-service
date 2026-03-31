# 新线程启动指引

## 本线程必须先调用的 Skill
新线程开始后，先依次调用：
1. [$thread-handoff](C:\Users\HIT-IVAFFR\.codex\skills\thread-handoff\SKILL.md)
2. [$permission-env-autopilot](C:\Users\HIT-IVAFFR\.codex\skills\permission-env-autopilot\SKILL.md)
3. [$project-preflight-bootstrap](C:\Users\HIT-IVAFFR\.codex\skills\project-preflight-bootstrap\SKILL.md)

说明：
- `thread-handoff`（线程交接）引用的自动导出脚本在本仓库中不存在，所以本交接包是手工维护的替代方案。
- 新线程不要跳过 `preflight`（预检）；在用户确认预检完成前，不要进入新的实现阶段。

## 先读这些文件
1. [handoff_overview.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/docs/thread-handoff/2026-03-30/handoff_overview.md)
2. [project_context.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/docs/thread-handoff/2026-03-30/project_context.md)
3. [progress.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/docs/thread-handoff/2026-03-30/progress.md)
4. [decisions.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/docs/thread-handoff/2026-03-30/decisions.md)
5. [next_actions.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/docs/thread-handoff/2026-03-30/next_actions.md)
6. [risks_open_questions.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/docs/thread-handoff/2026-03-30/risks_open_questions.md)
7. [environment_bootstrap.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/docs/thread-handoff/2026-03-30/environment_bootstrap.md)
8. [preflight-checklist.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/docs/thread-handoff/2026-03-30/preflight-checklist.md)
9. [environment-reset-checklist.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/docs/thread-handoff/2026-03-30/environment-reset-checklist.md)

## 当前结论
- 实际工作仓库是 [app](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app)
- 当前分支是 `codex/retrieval-pipeline-v1`
- 当前 HEAD 是 `262a0a5e28dce83bcef9751c3a9eb05c174b96ee`
- 最新可信 live 基线是：
  - [parent_work_eval_schumann_op54_results_v73.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/output/parent_work_eval_schumann_op54_results_v73.json)
  - [parent_work_eval_schumann_op54_access_v73.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/output/parent_work_eval_schumann_op54_access_v73.json)
- 必须显式注意：当前仍未恢复到此前最好表现
  - 历史最好：`versionFinalHit = 22/28`，`versionCandidateHit = 23/28`
  - 当前正确环境基线：`versionFinalHit = 18/28`，`versionCandidateHit = 18/28`
  - 因此，新线程的第一优先级不是加新功能，而是先把版本命中率恢复到至少历史最好水平

## 新线程第一目标
1. 固定使用项目 `.venv` 跑完整评估和回归，不要再用 `Anaconda` Python。
2. 先修复版本命中率回退：
   - 目标至少恢复到 `versionFinalHit = 22/28`
   - 目标至少恢复到 `versionCandidateHit = 23/28`
3. 仅在上述回退修复完成后，再继续扩大平台规则或新特性。

## 先执行的验证
```powershell
cd 'E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app'
git status --short
$env:PYTHONPATH='.'
& '.\.venv\Scripts\python.exe' -m pytest '.\tests' -q
& '.\.venv\Scripts\python.exe' '.\scripts\run_parent_work_eval.py' `
  --output '.\output\parent_work_eval_schumann_op54_results_resume.json' `
  --access-report '.\output\parent_work_eval_schumann_op54_access_resume.json' `
  --dataset-output '.\output\parent_work_eval_schumann_op54_dataset_resume.json'
```

## 如果需要用户介入
当前不需要用户立刻介入。

只有在新线程发现以下情况时，才需要联系用户：
- `.venv` 中 `playwright`（浏览器自动化）不可用
- 本地浏览器/登录态丢失，导致 `Bilibili browser rescue`（Bilibili 浏览器救援链路）完全失效
- `config/bilibili-storage-state.json` 丢失或失效

如果用户手动运行评估，只需提醒：
```powershell
cd 'E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app'
$env:PYTHONPATH='.'
& '.\.venv\Scripts\python.exe' '.\scripts\run_parent_work_eval.py' ...
```
不要使用 `E:\Anaconda\anaconda3\python.exe`。
