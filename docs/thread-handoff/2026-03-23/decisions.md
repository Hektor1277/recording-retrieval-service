# 关键决策

1. `Bilibili` 采用 `WBI search` 优先，HTML 搜索与浏览器搜索作为降级补位。
2. `storage state + Cookie + userAgent` 同时保留，作为浏览器与 HTTP 双通路的稳定上下文。
3. `DuckDuckGo HTML endpoint` 已从搜索策略中移除，不再作为回退搜索引擎。
4. 对 `concerto`（协奏曲）类场景，查询模板必须保留“作品名 + 作品号 + 主奏者”的 `primary-only query`，不能被协作者与乐团查询完全挤掉。
5. `exact-link` 排序在模糊上传簇中优先看标题锚点、年份、作品号、时长、上传者与浏览量，而不是只看粗 `same_recording_score`。
6. 对父项目并发调用场景，访问事件和警告采用请求级隔离，避免不同条目互相污染访问统计。
7. 登录态文件 [bilibili-storage-state.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/config/bilibili-storage-state.json) 已加入忽略规则，不能提交。
