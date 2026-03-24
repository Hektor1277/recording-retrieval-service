# 2026-03-24 Bilibili Search-Stage Optimization

## 背景

本轮针对 `Bilibili search-stage`（Bilibili 搜索阶段）做收敛，根因不是详情页清洗，而是：

1. `browser later-query starvation`（浏览器后续查询饿死）：首个宽泛 query 很容易吃满预算，后续更精确的 query 根本进不了候选。
2. `API/browser merge truncation`（API 与浏览器合并截断）：Bilibili API 结果噪声较大，但旧逻辑会让 API 结果先占满 hydration 窗口。
3. `cross-host under-allocation`（跨 host 分配不足）：多 host 合并时，Bilibili 只有 4 个 hydration 名额，导致已经进入 Bilibili 前排的目标链接仍然被截断。

## 改动

### 1. 浏览器查询覆盖从“前几条”改成“完整 query 池抽样”

- `select_bilibili_browser_queries()` 现在直接从完整 query 池抽样，不再受 HTML 搜索 query depth 的过早截断影响。
- 策略保留头部泛化 query，同时抽样尾部更精确的 query，避免 `Annie` 这类精确英文 query 永远进不了浏览器链路。

### 2. Bilibili 浏览器结果不再被首个 query 提前截断

- `_search_platform_via_browser_pages()` 对 Bilibili 改成按 query 收集结果，再做统一合并。
- `merge_bilibili_browser_query_rows()` 会为每个 query 保留前 3 条覆盖位，确保后续 query 的精确命中不会被首个宽 query 吞掉。

### 3. Bilibili 站内搜索改成 browser-first

- `_search_bilibili()` 最终合并改成 `browser -> api -> engine`。
- 理由是当前真实数据里，Bilibili browser search（浏览器搜索）比 API search（API 搜索）更能召回目标视频；API 仍保留为补充，不再主导前排。

### 4. 多 host 合并时提高 Bilibili hydration 配额

- `merge_streaming_host_rows()` 中，Bilibili 在多 host 场景下的 `per_host_cap` 从 `4` 提升到 `6`。
- 目标是让已经进入 Bilibili 前 5-6 位的真实目标链接能被真正 hydration，而不是在跨 host 合并时再次丢失。

## 测试

新增/覆盖的回归点：

- `test_bilibili_browser_search_keeps_later_query_hit_even_when_first_query_fills_budget`
- `test_search_bilibili_keeps_browser_coverage_when_api_rows_fill_budget`
- `test_search_bilibili_samples_precise_browser_queries_beyond_first_three`
- `test_merge_streaming_host_rows_preserves_deeper_bilibili_slice_when_multiple_hosts`

## 结果

静态验证：

- `pytest tests/test_search_connectivity.py -q -k "bilibili and (api or metadata or browser or noise or canonicalizes or coverage or precise or deeper)"` -> `13 passed`
- `pytest tests -q` -> `145 passed`

动态验证：

- 聚焦 live：`6/7 finalHit`，`6/7 candidateHit`
- 全量 live：`11/15 finalHit`，`12/15 candidateHit`

本轮直接拉回：

- `annie-full`
- `annie-no-group`
- `bohm-conductor-only`

当前剩余主阻塞：

- `gieseking-full`

## 下一步

`Gieseking` 还存在显著的 Bilibili live volatility（Bilibili 实时波动）：同样的 query 组合在不同轮次里，目标视频有时能进 browser rows，有时完全消失。下一轮应继续拆两件事：

1. 对 `Gieseking` 做 query-level recall instrumentation（按 query 级别的召回诊断），确认哪类 query 在 live 波动下最稳定。
2. 如果目标继续只在 Bilibili 深位出现，考虑引入 `promising browser hit escalation`（有前景浏览器命中扩窗）而不是继续固定 12 条窗口。
