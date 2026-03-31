# 下一轮直接工作

## 第一优先级
- 专攻 `heifetz-lead-only`
- 目标：把 [real_data_focus_milestone_latest.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/output/real_data_focus_milestone_latest.json) 中该样本从 `candidateHit=true, finalHit=false` 推到 `finalHit=true`

建议切入点：
- 比较 `youtube:8Aclk_O4bSc` 与 `youtube:9YWr1UcbZE8` 的标题、描述、上传者、时长与年份信号
- 检查是否需要在 `ambiguous upload cluster` 下进一步提高“带作品号 + 带主从人物组合”的排序权重
- 必要时增加针对 `Heifetz sparse query` 的回归测试

## 第二优先级
- 回到长批次全量回归，优先看：
  - `bohm-no-date`
  - `bohm-conductor-only`
  - `arrau-no-date`

建议切入点：
- 重点看“无日期”场景下年份过滤与错误年份上传的权重
- 检查 `Bohm` 的乐团错配为何还会压住正确链接
- 检查 `Arrau` 是否需要更强的钢琴独奏场景别名或平台偏好

## 第三优先级
- 在保持当前 `Bilibili` 配置闭环不破坏的前提下，再扩大样本量
- 优先新增：
  - `Bilibili-only`
  - `YouTube-only`
  - `concerto sparse`
  - `orchestral conductor-only`

## 建议验证顺序
1. `pytest` 定点失败测试
2. 聚焦真实回归
3. 全量真实回归
