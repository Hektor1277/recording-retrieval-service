# 2026-03-24 Gieseking Hydration Balance

## 背景

上一轮 `Bilibili search-stage optimization`（Bilibili 搜索阶段优化）已经把 `Annie` 拉回，但 `gieseking-full` 仍然卡住。进一步拆解后，问题分成两层：

1. `browser query selection`（浏览器查询选择）仍然过窄，`Gieseking` 最稳定的中间精确 query 会被 5 条上限挤掉。
2. 即使目标已经进入 Bilibili merged rows（合并结果）前排，多 host 合并时也会因为 `deep bilibili + youtube`（Bilibili 深位 + YouTube 并存）导致正确 YouTube 或 Bilibili 目标落在 hydration 初始窗口之外。

## 改动

### 1. Bilibili 浏览器 query 默认上限从 5 提到 6

- `select_bilibili_browser_queries()` 默认 `max_queries` 从 `5` 提升到 `6`。
- 结果是像 `Gieseking` 这种“头部泛 query + 中间精确 query + 尾部精确英文 query”结构可以同时保住，不再只能二选一。

### 2. 多 host 且 Bilibili 深位时，扩大初始 hydration 窗口

- 新增 `should_expand_initial_streaming_window()`。
- 当存在至少两个 `priority streaming host`（主优先级流媒体 host）且其中 `Bilibili` 有 `>= 9` 条候选时，初始 hydration 窗口从 `12` 扩到 `16`。
- 这不是全局放大，而是只针对当前真实盘面里最典型的 `deep bilibili + multi-host mix`（Bilibili 深位且多 host 混合）场景。

### 3. 保持跨 host Bilibili 深位配额

- `merge_streaming_host_rows()` 里 Bilibili 的 `per_host_cap` 保持在 `10`，确保 `Gieseking` 这类目标能真正进入 merged rows。
- 但是否真正进入 hydration，则交给上面的 `initial window expansion`（初始窗口扩展）来兜底，避免只靠单一 host cap 硬挤。

## 测试

新增/更新回归：

- `test_search_bilibili_samples_precise_browser_queries_beyond_first_three`
- `test_select_bilibili_browser_queries_keeps_precise_middle_conductor_query`
- `test_merge_streaming_host_rows_preserves_deeper_bilibili_slice_when_multiple_hosts`
- `test_search_streaming_broadens_initial_window_for_deep_bilibili_multi_host_mix`

静态验证：

- `pytest tests/test_search_connectivity.py -q -k "bilibili and (api or metadata or browser or noise or canonicalizes or coverage or precise or deeper or conductor or multiple_hosts)"` -> `14 passed`
- `pytest tests -q` -> `147 passed`

动态验证：

- 焦点 live：`4/5 finalHit`，`5/5 candidateHit`
- 全量 live：`13/15 finalHit`，`14/15 candidateHit`

这轮直接改善：

- `gieseking-full` 从 `finalHit=false` 提升到 `finalHit=true`

## 当前剩余

全量 live 当前剩余未解：

- `arrau-no-date`：`finalHit=false`，`candidateHit=false`
- `heifetz-lead-only`：`finalHit=false`，`candidateHit=true`

## 下一步

下一轮优先级建议：

1. `arrau-no-date`
   - 这是当前唯一仍然 `candidateHit=false` 的场景，信息增益最高。
2. `heifetz-lead-only`
   - 召回已到，但最终采纳仍未收敛，属于评分/终选阶段问题。
