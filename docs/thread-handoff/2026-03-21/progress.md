# 当前进展

## 已完成的大项
- 服务框架、协议接口、UI、便携包打包链路已建立并可运行。
- `Playwright fallback`（浏览器回退）已接入来源抓取。
- 文本分析已重写并支持：
  - `orchestral`
  - `concerto`
  - `opera_vocal`
  - `chamber_solo`
- 已支持角色感知的关键词构造：
  - `orchestral`：指挥、乐团、年份
  - `concerto`：独奏者、指挥、乐团、年份
  - `chamber_solo`：主参与者、协作者、年份
- 已支持人物别名文档、乐团缩写文档、双模型 `LLM` 配置文档、来源文档的 UI 打开入口。
- 已增加真实父项目数据回归脚本：`scripts/real_data_regression.py`

## 本线程结束时的代码状态
- 关键测试全量通过：`81 passed`
- 当前开发分支：`codex/retrieval-pipeline-v1`
- 子仓库远端：`https://github.com/Hektor1277/recording-retrieval-service.git`
- Python：`3.13.5`

## 最近一轮重要优化
- 协作型体裁的查询词改为“组合人物优先”。
- 查询词生成从“按人物刷完”改为“按查询形状交错展开”，前几条更容易命中关键协作关系。
- 阶段预算向 `streaming`（资源平台）倾斜，降低 `fallback`（兜底搜索）与 `LLM synthesis`（LLM 归并）的预算占比。
- 当已有强资源候选时，允许跳过 `fallback`。
- `fallback` 搜索改为并发搜索引擎请求。
- 增加 HTTP 文本缓存，降低重复页面请求成本。
- 提高“多作品合辑”负向惩罚，修复 `Spring Sonata`（春天奏鸣曲）被同组合合辑压过的问题。

## 最新真实数据结果
- 全量回归文件：`output/real_data_round11_b.json`
  - `total=8`
  - `finalHit=3`
  - `candidateHit=3`
- 聚焦回归文件：`output/real_data_focus_round11_h.json`
  - `annie-no-group`：`finalHit=true`
  - `spring-full`：`finalHit=true`
  - `spring-lead-only`：`finalHit=false`

## 当前稳定可复现的改善
- `bohm-full` / `bohm-no-date`：可回到目标 `YouTube` 链接
- `annie-full` / `annie-no-group`：当前聚焦回归可回到目标 `YouTube` 链接
- `arrau-no-date`：在聚焦回归中可回到目标链接
- `spring-full`：当前聚焦回归可回到目标链接
