# 风险与开放问题

## 风险 1：错误解释器再次被用于 live 评估
风险：
- 会直接让 `playwright` 缺失
- 导致 `browser rescue` 失效
- 产生误导性的极低命中率

应对：
- 新线程所有 live 命令统一写成 `.venv\Scripts\python.exe`

## 风险 2：当前历史最好表现尚未恢复
现状：
- 历史最好：`versionFinalHit = 22/28`，`versionCandidateHit = 23/28`
- 当前：`18/28`，`18/28`

这不是噪声，可以视为真实功能缺口。

## 风险 3：剩余 miss 以 bundled upload 为主
这类页面的特点是：
- 标题不干净
- 多作品混排
- 关键证据靠简介和上下文词

如果新线程继续只优化“单作品干净标题”的 query，收益会很低。

## 风险 4：Apple Music / Apple Music Classical 仍有波动
现状：
- `itunes.apple.com` 与 `classical.music.apple.com` 基本健康
- `music.apple.com` 仍有轻微退化迹象

结论：
- Apple 目前不是第一故障点
- 但新线程回归时仍要一起监控，避免主平台修复时再次误伤 Apple

## 开放问题
1. 剩余 `recall_miss` 中，有多少是“搜索没带回”，有多少是“带回了但评分没抬起来”？
2. 当前 bundled 线索更适合进入：
   - query pack（查询包）
   - 结果重排
   - 还是 description-aware scoring（简介感知评分）？
3. `Bilibili` 上 bundled 上传的标题结构是否能进一步抽取出稳定模式，例如：
   - `艺术家 + 年份 + 地点 + 多作品`
   - `艺术家 / 艺术家 + 电台/乐团 + 多作品`
4. `partial` 场景是否需要更系统地区分：
   - 单乐章正确版本
   - 仅同演奏者泛化版本

这些问题应在新线程围绕剩余 `recall_miss` 样本做实证分析后再定。
