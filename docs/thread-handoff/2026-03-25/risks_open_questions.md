# 风险与开放问题

## 当前风险
- live 检索结果仍受外部搜索排序波动影响，尤其是 `YouTube` 网页结果与 `Bilibili` 站内搜索的实时变化。
- 真实集总盘分数仍不高，当前舒曼钢协基线是 `strict 9/28`，说明系统仍处于“长尾召回不稳”阶段。
- 真实评估里仍混有少量“历史真值偏合集/弱唯一性”条目，会影响严格口径判断。
- `tmp-pytest-wrapper/` 在广域扫描时仍会报 `Permission denied`，虽然不影响主链路，但会污染大范围 `git/rg` 输出。

## 开放问题
- `cross-platform same performance`（跨平台同版）是否应进入未来的辅助评估口径，而不影响当前严格口径？
- `Alicia de Larrocha / Sawallisch 1977` 这类历史真值是否应由父项目单独修订，而不是让检索系统去迁就？
- 长尾 `recall_miss` 更主要是人名别名问题，还是平台实时结果深位召回问题？
- 父项目后续如果切到正式 `tool calling` 联调协议，现有 `json_object` 主路径是否需要旁路兼容层？
