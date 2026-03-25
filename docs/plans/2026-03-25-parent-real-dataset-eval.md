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

## Current Interpretation

- 本轮修复已经把问题从“系统性查不到”拉回到“部分场景能召回，但仍存在精确真值与最终筛选缺口”
- 剩余失败主要分三类：
  - `candidateHit=false`
    - 仍有部分艺术家/乐团组合没有召回到真值链接
  - `candidateHit=true` 但 `finalHit=false`
    - 候选已出现，但最终保留窗口或 LLM 归并未采纳
  - 真值口径偏严
    - 某些结果是同一演出版本的其他上传链接，但不等于父项目当前保存链接

## Artifact Paths

- 数据集：
  - `output/parent_work_eval_schumann_op54_dataset_v3.json`
- 结果：
  - `output/parent_work_eval_schumann_op54_results_v3.json`
- 访问报告：
  - `output/parent_work_eval_schumann_op54_access_v3.json`

## Next Candidates

- 优先继续看：
  - `candidateHit=true && finalHit=false`
  - `LLM timeout`（LLM 超时）导致的最终链接漏采纳
  - 同演出跨平台/多上传的“严格真值”判定口径
