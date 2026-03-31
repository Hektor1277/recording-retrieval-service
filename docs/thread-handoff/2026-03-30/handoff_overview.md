# 交接概览

本轮热切换的核心结论如下：

1. 当前主问题不是 `finalLinks`（最终链接）跨平台互挤，而是版本级 `recall`（召回）仍明显不足。
2. 本轮已经确认一个重要环境陷阱：
   - 用 `E:\Anaconda\anaconda3\python.exe` 跑完整 live 评估时，`playwright` 不可用，`browser rescue`（浏览器救援）链路会失效。
   - 用项目 [app/.venv](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/.venv) 跑同样评估时，`playwright 1.58.0` 可用，结果显著恢复。
3. 本轮已经修复两个真实的 `Bilibili` 搜索问题：
   - 浏览器搜索页入口从仅 `/video` 改为优先 `/all`，再回退 `/video`
   - HTML 解析器不再只认旧格式 `\"arcurl\":\"...\"`，现在支持 `arcurl:"..."` 和直接 `href="//www.bilibili.com/video/BV..."`
4. 即便上述修复已经生效，当前版本命中率仍明显低于历史最好表现：
   - 历史最好：`versionFinalHit = 22/28`，`versionCandidateHit = 23/28`
   - 当前正确环境基线：`versionFinalHit = 18/28`，`versionCandidateHit = 18/28`

这意味着新线程的第一个目标应当是“修复回退”，不是“继续扩功能”。

## 推荐新线程阅读顺序
- [START_NEW_THREAD.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/docs/thread-handoff/2026-03-30/START_NEW_THREAD.md)
- [progress.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/docs/thread-handoff/2026-03-30/progress.md)
- [next_actions.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/docs/thread-handoff/2026-03-30/next_actions.md)
- [environment_bootstrap.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/docs/thread-handoff/2026-03-30/environment_bootstrap.md)

## 本轮最重要的产物
- 可信基线：
  - [parent_work_eval_schumann_op54_results_v73.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/output/parent_work_eval_schumann_op54_results_v73.json)
  - [parent_work_eval_schumann_op54_access_v73.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/output/parent_work_eval_schumann_op54_access_v73.json)
- 关键代码：
  - [http_sources.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/http_sources.py)
  - [pipeline.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/pipeline.py)
  - [browser_fetcher.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/browser_fetcher.py)
  - [parent_work_eval.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/parent_work_eval.py)

## 本轮结论一句话版
正确环境已经找回，Bilibili 搜索入口和解析器 bug 也已修掉，但主基线仍未恢复到 `22/28` 与 `23/28`，说明剩余问题是实打实的版本召回问题，必须在新线程优先修复。
