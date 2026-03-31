# 当前进展

## 这轮已经确认并修复的点

### 1. 运行环境误用导致的假退化
已经确认：
- `E:\Anaconda\anaconda3\python.exe` 环境缺少 `playwright`（浏览器自动化）
- 这会导致 `Bilibili browser rescue`（Bilibili 浏览器救援链路）在 live 评估中实际不可用
- 使用项目 [app/.venv](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/.venv) 后，`playwright 1.58.0` 正常可用，结果明显恢复

### 2. Bilibili 搜索入口修复
已经在 [http_sources.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/http_sources.py) 修复：
- `Bilibili browser search` 不再只试 `/video`
- 现在优先试 `/all`
- 若失败或提取不足，再退回 `/video`

### 3. Bilibili HTML 解析器修复
同样已在 [http_sources.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/http_sources.py) 修复：
- 旧逻辑只认 `\"arcurl\":\"...\"`
- 新逻辑支持：
  - `arcurl:"..."`
  - `href="//www.bilibili.com/video/BV..."`

这一修复已通过 live HTML 验证：此前解析不到任何结果的页面，现在可正确提取包含目标 `BV` 的结果集。

### 4. Bundle-aware query（合集感知查询）已补入
已新增更适合合集上传的查询形态，例如：
- `Fischer Prick NHK Schumann concerto 1985`
- `Kempff Dorati Schumann concerto 1959`
- 包含 `Hungary / Budapest / 1954 / Ferencsik` 这种上下文词的查询

## 当前可信验证结果

### 单元/集成测试
最新全量测试：
```text
274 passed in 7.81s
```

### 舒曼钢协 live 基线
正确 `.venv` 环境下的最新可信基线：
- [parent_work_eval_schumann_op54_results_v73.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/output/parent_work_eval_schumann_op54_results_v73.json)
- [parent_work_eval_schumann_op54_access_v73.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/output/parent_work_eval_schumann_op54_access_v73.json)

指标：
- `finalHit = 14/28`
- `candidateHit = 14/28`
- `relaxedFinalHit = 15/28`
- `relaxedCandidateHit = 15/28`
- `versionFinalHit = 18/28`
- `versionCandidateHit = 18/28`
- `strictMissReasons`：
  - `recall_miss = 13`
  - `same_platform_alt_upload = 1`

### Host 侧状态
从 [parent_work_eval_schumann_op54_access_v73.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/output/parent_work_eval_schumann_op54_access_v73.json) 可见：
- `api.bilibili.com`: `350 requests`, `0 failures`
- `search.bilibili.com`: `90 requests`, `0 failures`
- `www.youtube.com`: `412 requests`, `0 failures`
- `www.googleapis.com`: `1 request`, `1 failure`
- `itunes.apple.com`: `152 requests`, `0 failures`
- `classical.music.apple.com`: `47 requests`, `0 failures`
- `music.apple.com`: `115 requests`, `1 failure`

这说明：
- 当前主问题不是所有外部链路都坏了
- `Bilibili` 搜索和 API 在正确环境下是可工作的
- 剩余缺口主要来自版本召回本身

## 必须显式记录的回退
虽然这轮已经修复了环境误判和 Bilibili 解析 bug，但系统表现仍未恢复到此前最好水平：
- 历史最好：`versionFinalHit = 22/28`
- 历史最好：`versionCandidateHit = 23/28`
- 当前：`18/28` 与 `18/28`

因此：
- 当前不能视为“链路已经恢复”
- 新线程必须把恢复版本命中率作为第一修复目标
