# 项目背景与目标

## 项目定位
- `Recording Retrieval Service`（版本检索服务）是父项目 `Introduction to Classical Music`（古典音乐导聆网站）的外部工具。
- 父仓库路径：`E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service`
- 实际实现仓库路径：`E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app`
- 父仓库保留协议与背景文档；`app/` 是独立 `git`（版本控制）仓库。

## 核心目标
- 根据用户输入或维护工具协议输入的少量非结构化信息，检索并整合特定版本条目的资源链接与补充信息。
- 第一优先级是资源链接命中率与正确性。
- 第二优先级是补全 `performanceDateText / venueText / albumTitle / label / releaseDate / images`。
- 对外协议保持 `v1` 不变。

## 当前实现形态
- 后端：`Python + FastAPI + asyncio/httpx`
- UI：同进程托管的本地网页
- 搜索来源：高质量来源文档、资源平台文档、搜索引擎兜底
- 浏览器回退：`Playwright`（浏览器自动化）已接入，但目前主要瓶颈仍是实时站点返回质量与批量场景超时
- LLM：双模型配置
  - `reasoning model`（推理模型）：`deepseek-reasoner`
  - `fast model`（快速模型）：`deepseek-chat`

## 当前重点
- 真实父项目条目回归测试
- 不同体裁与不同信息完整度下的资源链接命中率优化
- 尤其关注 `concerto`（协奏曲）与 `chamber_solo`（室内乐/独奏）多人协作条目的检索质量
