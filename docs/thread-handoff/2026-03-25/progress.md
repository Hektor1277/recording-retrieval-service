# 当前进展

## 代码能力
- [http_sources.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/http_sources.py)
  已完成 `Bilibili WBI search`、`detail API hydration`、中文短别名、host-aware 查询预算、以及按父项目规则处理 `多分P/合集/首章节` 的同版评分。
- [pipeline.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/pipeline.py)
  已完成模糊上传簇排序、`same recording` 与 `packaging priority`（包装优先级）拆分，以及最终链接排序中 `独立全量 > 合集/多分P > 第一乐章` 的稳定表达。
- [platform_clients.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/platform_clients.py)
  已支持 `Bilibili view API` 与 `WBI search` 的主结构化路径。
- [service_client.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/service_client.py)
  已把父项目联调抽象为 `health / create_job / get_job / get_results / cancel_job / wait_for_results / run_job`。
- [parent_work_eval.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/parent_work_eval.py)
  已支持真实数据集生成、`strict/relaxed` 命中统计、`same_platform_alt_upload` 归因，以及真值链接健康度辅助函数。

## 新增工具
- [run_parent_work_eval.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/scripts/run_parent_work_eval.py)
  可对父项目单一作品整组 live 评估。
- [audit_parent_work_links.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/scripts/audit_parent_work_links.py)
  可审计父项目原始 `YouTube/Bilibili` 真值链接是否仍可用、是否可疑。

## 最新验证基线
- 全量测试：
  `& '.\.venv\Scripts\python.exe' -m pytest '.\tests' -q`
  结果：`173 passed`
- 父项目真实集评估：
  [parent_work_eval_schumann_op54_results_v6.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/output/parent_work_eval_schumann_op54_results_v6.json)
  结果：`strict 9/28 finalHit, 12/28 candidateHit`
  `relaxed 11/28 finalHit, 13/28 candidateHit`
- 父项目真值链接审计：
  [parent_work_eval_schumann_op54_link_audit_v2.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/output/parent_work_eval_schumann_op54_link_audit_v2.json)
  结果：`20/20 available`，其中 `2/20 available_but_suspicious`

## 最近关键提交
- `262a0a5` `Align retrieval with parent link priority`
- `10bfa0f` `Add parent ground truth link audit`
- `27376c6` `Improve parent dataset recall aliases`
- `c939f77` `fix: isolate browser fetcher per event loop`
- `bba2491` `fix: isolate llm clients per event loop`
