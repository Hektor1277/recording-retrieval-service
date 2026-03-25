# 2026-03-25 YouTube Query Coverage And Tool Audit

## 本轮目标

本轮同时推进两件事：

1. 修复 `arrau-no-date` 的真实回归失败。
2. 开始梳理项目当前的 `tool calling interface`（工具调用接口）和相关逻辑，为后续联合调试提供入口。

## 里程碑结果

### 1. `arrau-no-date` 已恢复

根因拆成两层：

#### 输入归一化层

- `Arrau` 数据本身的 `title` 是 `阿劳 - Beethovenfest Bonn 1970`。
- 旧逻辑在 `InputNormalizer` 中只会从标题里抽出 `1970`，把真正有区分度的 `Beethovenfest Bonn` 丢掉。
- 这导致 `arrau-no-date` 的 query 退化成“作品 + 演奏者 + 纯年份”，丢失现场上下文。

修复：

- 在 [pipeline.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/pipeline.py) 中新增 `extract_title_performance_context()`。
- 对 `chamber_solo` 场景，当 `performanceDateText` 为空且标题中存在 `context + year`（上下文 + 年份）片段时，优先保留完整上下文，而不是只取年份。

#### YouTube 检索层

- 修完归一化后，`Tdg-DT8rTUQ` 已经能够稳定由强 query 召回。
- 但旧的 `_search_streaming_platform()` 在合并多条 YouTube query 结果时，仍然会让前面宽泛 query 的 generic hits（泛化命中）长期占前排，导致后面精确 query 的 top hit 被压到 host slice 深位。
- 对 `Arrau` 来说，这会把目标 `Tdg-DT8rTUQ` 压到 YouTube host 结果后排，再被多 host 合并和 hydration 截掉。

修复：

- 在 [http_sources.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/http_sources.py) 中新增：
  - `merge_streaming_query_groups()`
  - `should_merge_streaming_query_coverage()`
- 当前仅对 `YouTube Search` 启用 `per-query coverage merge`（按 query 的覆盖合并），让后续精确 query 的头部结果可以提前进入最终窗口。

### 2. 当前盘面

静态验证：

- `pytest tests -q` -> `149 passed`

动态验证：

- 焦点 live：`arrau-full / arrau-no-date / heifetz-full / heifetz-lead-only` -> `3/4 finalHit`, `4/4 candidateHit`
- 全量 live：`14/15 finalHit`, `14/15 candidateHit`

本轮直接恢复：

- `arrau-full`
- `arrau-no-date`

当前剩余唯一未解：

- `heifetz-lead-only`

## Tool Calling Interface 审计

### 当前入口

#### UI 文本分析入口

- 路由：`POST /ui/analyze-text`
- 文件：[main.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/main.py)
- 逻辑：
  - 先走本地规则分析 `analyze_raw_text()`
  - 如果配置了 LLM，再调用 `llm_client.analyze_input()`
  - 仅在字段为空时用 LLM 返回值补空

#### 检索阶段的 LLM 归并入口

- 文件：[pipeline.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/pipeline.py)
- 逻辑：
  - 先跑 `existing-link / high-quality / streaming / fallback`
  - 再按预算和歧义度决定是否调用 `llm_client.synthesize()`
  - LLM 返回 `acceptedUrls` 后，再进入规则装配

#### LLM 适配层

- 文件：[llm_client.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/llm_client.py)
- 当前协议：
  - 使用 OpenAI-compatible `POST {base_url}/chat/completions`
  - 通过 `response_format = {\"type\": \"json_object\"}` 要求 JSON 输出
  - 当前**没有**使用 `tools` / `tool_choice` / function calling（函数调用）
  - 也没有 `json_schema`（JSON 模式约束）

### 当前接口特征

1. 这是 `JSON-only contract`（仅 JSON 契约），不是 `tool-calling contract`（工具调用契约）。
2. `analyze_input()` 和 `synthesize()` 都依赖 prompt 约束 + `parse_json_object()` 做宽松解析。
3. `normalize_llm_payload()` 只做轻量字段清洗，没有严格结构校验。

### 后续联合调试最值得盯的点

1. `main.py:/ui/analyze-text`
   - 当前会吞掉 `llm_client.analyze_input()` 异常并静默回退到规则结果，联调时如果看不到日志，容易误以为 LLM 没有被调用。
2. `pipeline.py:llm synthesis gate`
   - `allow_realtime_synthesis`
   - `minimum_synthesis_timeout_seconds`
   - `should_skip_llm_synthesis()`
   - 这三个门会决定 LLM 是否真正被调用。
3. `llm_client.py:_chat_json`
   - 当前是 `json_object` 而不是 `tools`，如果后续要切到真正的工具调用，需要从这里开始改协议和测试夹具。

## 下一步建议

1. 继续攻 `heifetz-lead-only`
   - 当前已经是唯一剩余失败场景。
   - 它已经从之前的 `candidate=true / final=false` 震荡到这轮 `candidate=false / final=false`，说明需要重新看 YouTube/Bilibili 召回与终选两侧的交互。
2. 工具调用联调
   - 下一轮如果开始做真实 `tool calling`，建议先在 `llm_client.py` 增加一个并行的实验适配层，不直接覆盖当前 `json_object` 路径。
