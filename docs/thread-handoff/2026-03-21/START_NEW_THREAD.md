# 新线程启动指南

## 读取顺序
1. 打开实现仓库目录：
   - `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app`
2. 读取正式交接包：
   - `.codex-handoff/current/manifest.json`
   - `.codex-handoff/current/project_context.md`
   - `.codex-handoff/current/progress.md`
   - `.codex-handoff/current/decisions.md`
   - `.codex-handoff/current/next_actions.md`
   - `.codex-handoff/current/risks_open_questions.md`
   - `.codex-handoff/current/environment_bootstrap.md`
3. 补充读取本轮源文件：
   - `docs/thread-handoff/2026-03-21/`
4. 查看最新真实回归结果：
   - `output/real_data_round11_b.json`
   - `output/real_data_focus_round11_h.json`

## 推荐命令
```powershell
cd 'E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app'
& '.venv\Scripts\python.exe' 'C:\Users\HIT-IVAFFR\.codex\skills\thread-handoff\scripts\load_handoff.py' --start-dir .
& '.venv\Scripts\python.exe' -m pytest tests -q
& '.venv\Scripts\python.exe' '.\scripts\real_data_regression.py' --output '.\output\real_data_round11_resume.json'
```

## 新线程建议先做的事
- 优先看 `spring-lead-only`
- 然后看整批 8 条回归稳定性
- 最后再处理 UI warning 乱码清理
