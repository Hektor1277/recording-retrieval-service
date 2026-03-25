# 2026-03-25 Parent Real Dataset Eval

## Goal

基于父项目 `data/library` 的真实录音数据，抽取单一作品的全部条目，生成 `full`（全信息）与 `partial`（残缺信息）对照样本，直接跑当前检索链路，观察真实命中率并据此迭代。

## Dataset Choice

- 作品：Schumann `Piano Concerto, Op.54`
- 选择原因：
  - 共 `15` 条录音，规模适中，便于单轮完整 live 回归
  - `14/15` 带 `YouTube / Bilibili` 真值链接，可计算严格 `hit rate`（命中率）
  - 涵盖 `soloist / conductor / orchestra / date` 等协作字段，适合检验协奏曲链路

## Tooling Added

- `app/services/parent_work_eval.py`
  - 从父项目 `works.json / recordings.json / composers.json` 生成真实评估样本
  - 统一 `canonicalize_url`（链接规范化）、`build_recording_scenarios`（样本生成）、`summarize_results`（结果汇总）
- `scripts/audit_parent_work_links.py`
  - 对父项目某一作品的原始 `YouTube / Bilibili` 真值链接做 `availability + metadata match`（可用性 + 元数据匹配）审计
  - 输出 `link audit`（链接审计）JSON，区分：
    - `available`
    - `available_but_suspicious`
    - `unavailable`
- `scripts/run_parent_work_eval.py`
  - 直接执行某一作品的整组 live 评估
  - 同时输出：
    - `dataset`：测试样本
    - `results`：检索结果
    - `access report`：访问事件明细
- `tests/test_parent_work_eval.py`
  - 锁定样本生成、汇总口径与父项目根路径解析

## Findings

### Baseline

- 首轮严格真值结果：
  - `overall`: `2/28 finalHit`, `2/28 candidateHit`
  - `full`: `1/14 finalHit`
  - `partial`: `1/14 finalHit`

### Root Cause 1

- 父项目真实条目大量只有中文 `Credit.displayName`
- 但 `Credit.personId` 可在父项目 `people.json` 中反查：
  - `nameLatin`
  - `aliases`
- 旧链路几乎未利用 `personId`
- 结果：
  - 英文人名 query（查询词）大量缺失
  - 真实分布下 `YouTube / Bilibili` 召回明显塌陷

### Optimization 1

- 在 `pipeline.InputNormalizer` 中新增 `LibraryPersonNameLookup`
- 通过 `personId -> people.json` 自动补齐：
  - `primary_names_latin`
  - `secondary_names_latin`
  - `ensemble_names_latin`

### Optimization 2

- 基于 `people.json.aliases` 继续扩展 query 用拉丁名：
  - 英文别名
  - 缩写
  - `ascii-folded`（去重音）变体，如 `Furtwängler -> Furtwangler`
- 调整 `build_query_lead_terms`，让主副演奏者的别名组合真正进入 query 池

## Result After Optimization

- 第二轮严格真值结果：
  - `overall`: `7/28 finalHit`, `10/28 candidateHit`
  - `full`: `4/14 finalHit`, `5/14 candidateHit`
  - `partial`: `3/14 finalHit`, `5/14 candidateHit`

- 第三轮在相同作品上复跑：
  - 指标与第二轮持平
  - 说明本轮增益已收敛，当前剩余问题不再主要是“拉丁名缺失”

### Relaxed Evaluation

- 新增 `relaxed hit`（宽松命中）口径：
  - 保留原有 `strict URL hit`（严格 URL 命中）
  - 额外统计“同平台 + 高置信候选 + 不同上传链接”的 `same_platform_alt_upload`
- 第四轮结果：
  - `overall`
    - `strict`: `8/28 finalHit`, `10/28 candidateHit`
    - `relaxed`: `11/28 finalHit`, `12/28 candidateHit`
  - `full`
    - `strict`: `5/14 finalHit`, `5/14 candidateHit`
    - `relaxed`: `6/14 finalHit`, `6/14 candidateHit`
  - `partial`
    - `strict`: `3/14 finalHit`, `5/14 candidateHit`
    - `relaxed`: `5/14 finalHit`, `6/14 candidateHit`

- `strict miss` 归因：
  - `same_platform_alt_upload`: `3`
  - `final_selection_after_llm_timeout`: `1`
  - `recall_miss`: `16`

- 代表性 `same_platform_alt_upload` 样本：
  - `Radu Lupu / Giulini 1980`
    - 真值：`BV1RiZJYAEBD`
    - 最终命中：`BV1vM4m1D7Br`
    - 候选标题直接写明 `Schumann: Piano Concerto, Op.54 / Radu Lupu`
    - `confidence=0.97`
  - `Cortot / Fricsay 1951`
    - 真值：`BV1Pr4y1Q74W`
    - 最终命中：`BV1vL5ozzEyp`
    - 候选为同平台合集上传，描述中明确标注 `Schumann: Piano Concerto in A Minor, Op.54` 与 `1951.5.15`
    - `confidence=0.81`

## Current Interpretation

- 本轮修复已经把问题从“系统性查不到”拉回到“部分场景能召回，但仍存在精确真值与最终筛选缺口”
- 剩余失败主要分三类：
  - `candidateHit=false`
    - 仍有部分艺术家/乐团组合没有召回到真值链接
  - `candidateHit=true` 但 `finalHit=false`
    - 候选已出现，但最终保留窗口或 LLM 归并未采纳
  - 真值口径偏严
    - 某些结果是同一演出版本的其他上传链接，但不等于父项目当前保存链接

## Follow-up Optimization

### Optimization 3

- 继续沿 `recall_miss`（召回缺失）排查，发现父项目真实失败样本中有一批目标视频标题直接使用中文简写：
  - `舒曼钢协`
  - `a小调钢协`
- 旧链路虽然能生成 `piano concerto / klavierkonzert` 等拉丁别名，但不会把 `钢协` 这类中文短别名送进 Bilibili 实际查询列表。
- 本轮补了两处：
  - `build_work_aliases` 新增中文 `piano concerto`（钢琴协奏曲）短别名：
    - `钢协`
    - `a小调钢协`
  - 中文 host 的 `_queries_for_host` 保底保留 `1` 条最短 `alias query`（别名查询），避免被较长的 `primary / zh / latin` 查询全部挤掉

### Fifth Run

- 第五轮结果：
  - `overall`
    - `strict`: `9/28 finalHit`, `12/28 candidateHit`
    - `relaxed`: `12/28 finalHit`, `14/28 candidateHit`
  - `full`
    - `strict`: `5/14 finalHit`, `6/14 candidateHit`
    - `relaxed`: `6/14 finalHit`, `7/14 candidateHit`
  - `partial`
    - `strict`: `4/14 finalHit`, `6/14 candidateHit`
    - `relaxed`: `6/14 finalHit`, `7/14 candidateHit`

- 与第四轮相比：
  - `strict finalHit`: `8 -> 9`
  - `strict candidateHit`: `10 -> 12`
  - `relaxed finalHit`: `11 -> 12`
  - `relaxed candidateHit`: `12 -> 14`
  - `recall_miss`: `16 -> 14`

- 这轮直接拉回的样本包括：
  - `Annie Fischer / Christoph Perick 1985 full`
  - `Benno Moiseiwitsch partial`

### Remaining Failure Shape

- 剩余 `relaxed final miss` 仍以 `recall_miss` 为主，但失败画像已经更清晰：
  - `full miss`
    - `Grinberg / Eliasberg 1958`
    - `Kempff / Dorati 1959`
    - `de Lara / Whyte 1951`
    - `Richter / Ferencsik 1954`
  - `cross-platform same performance`
    - `Gieseking / Furtwängler 1942`
    - `Claudio Arrau / Jochum 1977`
    - 当前结果能找到高置信 `YouTube` 版本，但不属于现有“同平台替代上传”宽松口径
  - `final selection gap`
    - `Virsaladze / Rudin full`
    - `Alicia de Larrocha partial` 仍有 `final_selection_after_llm_timeout`

- 说明下一轮如果继续提升真实命中率，优先级应从“再加更多短 query”切到两类：
  - 长尾人名/俄语转写的 `recall`（召回）增强
  - 是否引入“跨平台同版”辅助评估口径，但不能覆盖现有严格口径

## Ground Truth Audit

- 第六轮先不改召回，而是对父项目原始真值做健康度审计，避免把“原始链接过时”误判成检索失败。
- 审计方法：
  - `YouTube` 使用 `oEmbed`
  - `Bilibili` 使用 `x/web-interface/view`
  - 每条原始链接都抓取当前标题 / 上传者
  - 用同一录音的 `full + partial` 两个样本分别打 `match score`，取最高分，避免“标题未写齐全部协作字段”导致的误伤

- 审计结果：
  - `20/20 available`
  - `0/20 unavailable`
  - `18/20 available`
  - `2/20 available_but_suspicious`
  - 说明当前舒曼钢协数据集没有真实失效链接，至少在 `2026-03-25` 这次审计时，评估基线仍然可用

- 当前唯一明确可疑的原始真值都落在 `Alicia de Larrocha / Sawallisch 1977`：
  - `bilibili:BV1EUE4zgEDH`
    - 标题是 `Larrocha拉罗查现场录音③勃拉姆斯、舒曼 Brahms Schumann`
    - 更像合集页，而不是直接指向单一 `Schumann Piano Concerto`
    - `matchScore=0.0`
  - `youtube:j4kYjcLRpNY`
    - 虽然标题写明 `Schumann Concerto in A minor, Op.54 (1977 Live)`，但缺少关键协作线索，和当前录音条目的耦合度很弱
    - `matchScore=0.06`

- 这说明：
  - 当前真实评估里的主问题不是“链接失效”
  - 更像是少数父项目历史真值本身就偏宽、偏合集或缺少唯一性
  - 下一轮如果要进一步提高评估可信度，应该优先把这些 `available_but_suspicious` 原始链接单独标注，而不是先放宽检索口径

## Artifact Paths

- 数据集：
  - `output/parent_work_eval_schumann_op54_dataset_v5.json`
- 结果：
  - `output/parent_work_eval_schumann_op54_results_v5.json`
- 访问报告：
  - `output/parent_work_eval_schumann_op54_access_v5.json`
- 链接审计：
  - `output/parent_work_eval_schumann_op54_link_audit_v2.json`

## Next Candidates

- 优先继续看：
  - `available_but_suspicious` 的父项目原始真值标注
  - `candidateHit=true && finalHit=false`
  - `LLM timeout`（LLM 超时）导致的最终链接漏采纳
  - 长尾钢琴家/指挥的 `query enrichment`（查询富化）
  - 同演出跨平台/多上传的“严格真值”判定口径
