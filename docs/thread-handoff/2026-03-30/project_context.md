# 项目背景

## 项目目标
本服务负责把父项目中的古典音乐“版本条目”自动检索为可消费的资源链接，并输出结构化候选，优先覆盖三个主平台：
- `Bilibili`
- `YouTube`
- `Apple Music / Apple Music Classical`

项目当前真正追求的不是“命中特定答案链接”，而是：
1. 尽可能命中正确版本的高质量候选链接
2. 对三大主平台分别独立给出候选
3. 对不确定但可能正确的版本，保留 `yellow`（黄区，存疑候选）供人工判断

## 当前评估口径
当前评估已经从单一 `strict URL hit`（严格 URL 命中）扩展为多层口径：
- `finalHit`：严格命中目标链接
- `candidateHit`：目标链接出现在候选中
- `versionFinalHit`：最终链接中存在高置信正确版本，即便不是原始目标 URL
- `versionCandidateHit`：候选中存在高置信正确版本

新线程请优先关注：
- `versionFinalHit`
- `versionCandidateHit`

因为真实上线时没有“标准答案 URL”，真正关键的是版本候选质量。

## 关键模块
- [pipeline.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/pipeline.py)
  负责候选评分、最终链接筛选、平台独立候选分层
- [http_sources.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/http_sources.py)
  负责各平台查询构造、搜索、聚合和部分 host-specific（站点特化）逻辑
- [browser_fetcher.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/browser_fetcher.py)
  负责浏览器级证据抓取、截图和搜索页渲染层提取
- [platform_clients.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/platform_clients.py)
  负责平台 API 和结构化元数据获取
- [parent_work_eval.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/parent_work_eval.py)
  负责 live 数据集评估和多口径命中统计

## 当前主基准
主基准仍是舒曼《Piano Concerto, Op.54》完整评估：
- [parent_work_eval_schumann_op54_results_v73.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/output/parent_work_eval_schumann_op54_results_v73.json)
- [parent_work_eval_schumann_op54_access_v73.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/output/parent_work_eval_schumann_op54_access_v73.json)

当前可信基线：
- `finalHit = 14/28`
- `candidateHit = 14/28`
- `relaxedFinalHit = 15/28`
- `relaxedCandidateHit = 15/28`
- `versionFinalHit = 18/28`
- `versionCandidateHit = 18/28`

这仍低于本项目此前已达到的最好表现：
- `versionFinalHit = 22/28`
- `versionCandidateHit = 23/28`

新线程必须先恢复这一回退。
