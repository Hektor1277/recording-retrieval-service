# 关键决策

1. `Bilibili` 继续采用 `WBI search + detail API` 优先，HTML 与浏览器抓取只作为回退。
2. 父项目真实评估继续保留两套口径：
   - `strict URL hit`
   - `relaxed hit`
   当前 `relaxed` 仅接受 `same_platform_alt_upload`，不自动放宽到跨平台同版。
3. 父项目历史真值链接优先级已确认并写入排序语义：
   - 独立且仅相关内容的全量视频
   - 含其他内容的多分P视频
   - 合集
   - 单章节视频，仅允许首章节/第一乐章
4. 因此当前检索逻辑不再把 `合法合集/多分P/第一乐章` 简单视为错误结果，而是把它们作为“同版但次优包装”处理。
5. `same recording` 与 `packaging priority` 已显式拆开：
   - `same_recording_score` 负责判断是不是同版
   - `sort_link_candidates` 再按包装优先级做最终顺序
6. 父项目真值健康度审计结论是：
   - 当前舒曼钢协数据集没有真实失效链接
   - 少数可疑真值主要是历史录入偏合集或标题唯一性不足，不是错链或死链
7. 联调层当前仍是 OpenAI-compatible `chat/completions + response_format=json_object` 路径，不是正式 `tool calling` 协议；后续若要做父项目联合调试，应在不破坏现有主路径的前提下并行加实验适配层。
