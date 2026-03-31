# 项目背景

项目目标是把父项目中的古典音乐版本条目，自动检索为可消费的版本资源链接与辅助字段，优先覆盖 `YouTube`、`Bilibili`，并为父项目提供稳定、低耦合的调用接口。

当前项目状态已经从“小样本定点修复”推进到“父项目真实数据集评估”阶段，核心目标分成三层：
- 检索层：提高 `same recording`（同版）召回与排序质量
- 评估层：用父项目真实条目生成 `full/partial` 对照样本，观测严格与宽松命中率
- 联调层：为父项目提供尽量薄的调用面，让父项目只关注接口和协议，而不需要关心内部检索细节

当前主链路涉及的关键模块：
- [pipeline.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/pipeline.py)
- [http_sources.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/http_sources.py)
- [platform_clients.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/platform_clients.py)
- [service_client.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/service_client.py)
- [parent_work_eval.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/parent_work_eval.py)

当前真实评估的基准作品是父项目舒曼《Piano Concerto, Op.54》，因为它同时包含：
- 单平台与双平台真值
- 协奏曲场景下的主奏/指挥/乐团/年份信息
- 同版不同上传、多分P、合集、首章节等复杂包装形态
