# 风险与开放问题

## 风险
- `YouTube Data API` 当前仍不稳定，访问报告里常见 `www.googleapis.com` 退化为 `quotaExceeded`
- 长批次全量回归的结果仍会被外部环境波动影响，尤其是网页搜索结果页的排序变化
- `Bilibili` 虽然已明显稳定，但 `search.bilibili.com` 平均延迟仍偏高，且浏览器回退仍是高成本路径

## 开放问题
- `Heifetz lead-only` 到底是需要更强的标题锚点权重，还是需要更强的上传簇内平台偏好？
- `Bohm` 与 `Arrau` 这些长批次失败，主要是查询模板问题，还是平台实时结果波动问题？
- 全量 `9/15` 是否已经足够作为下一轮继续扩样本的基线，还是应先把 `Bohm/Arrau/Heifetz` 收紧到更高水平？
