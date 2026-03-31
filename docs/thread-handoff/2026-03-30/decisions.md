# 关键决策

## 已确认的决策

### 1. 评估与实现必须以项目 `.venv` 为准
原因：
- `Anaconda` 环境缺少 `playwright`
- 会让 `browser rescue` 链路假性失效
- 会制造错误的 live 回退结论

结论：
- 后续所有 live 评估、preflight、关键验证，一律以 [app/.venv](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/.venv) 为准

### 2. 当前最高优先级是恢复 `versionFinalHit/versionCandidateHit`
原因：
- 真正上线时没有标准答案 URL
- 版本级高质量候选才是系统核心能力
- 当前 `18/28` 仍显著低于历史最好 `22/28` 和 `23/28`

结论：
- 新线程先修版本命中率，不先扩平台功能，不先加次级优化

### 3. 当前最大瓶颈是召回，不是平台互挤
原因：
- 本轮已经检查过 `finalLinks` 平台互挤边界
- 当前主要损失项仍是 `recall_miss`
- 特别是 bundled upload（合集上传）和多作品标题场景

结论：
- 下一步优先做搜索/query/result audit（查询与结果审计）
- 暂不把主要精力放在 final 层重排细节

### 4. Bilibili 搜索应优先 `/all`
原因：
- `/all` 页面在当前站点结构下更容易暴露真实结果卡片
- 只走 `/video` 会漏掉一批实际可见结果

结论：
- 保持 `/all -> /video` 的搜索顺序

### 5. Bilibili 解析器必须兼容当前页面形态
原因：
- 站点输出并不稳定
- 只支持一种旧格式会造成无结果假象

结论：
- 继续保留对 `arcurl:"..."` 和直接 `href` 的兼容解析

### 6. `thread-handoff` skill 的脚本资源在本仓库不存在
原因：
- 仓库中不存在 `scripts/export_handoff.py`
- 也不存在 `scripts/load_handoff.py` 和 `scripts/generate_env_reset_checklist.py`

结论：
- 当前交接文档采用手工维护
- 新线程不要浪费时间去找这些不存在的脚本，应直接使用本交接包
