# 2026-03-25 Parent Integration Wrapper

## 背景

当前服务对外协议已经稳定在 `/v1/jobs` 系列接口，但父项目如果直接接 HTTP（超文本传输协议）细节，仍然需要自己处理：

- `create_job`（创建作业）
- `poll status`（轮询状态）
- `fetch results`（拉取结果）
- `cancel on timeout`（超时取消）

这会把本项目的时序细节泄漏到父项目里，不利于后续联合调试和协议稳定。

## 本轮目标

在本项目内部提供一个轻量 `service client`（服务客户端）封装，让父项目优先依赖：

- `protocol models`（协议模型）
- `run_job`（提交并等待结果）
- `wait_for_results`（等待结果）
- `cancel_job`（取消作业）

而不是自己拼接 `/v1/jobs/...` 请求流程。

## 本轮实现

新增 `app/services/service_client.py`：

- `RecordingRetrievalServiceClient.health()`
- `RecordingRetrievalServiceClient.create_job()`
- `RecordingRetrievalServiceClient.get_job()`
- `RecordingRetrievalServiceClient.get_results()`
- `RecordingRetrievalServiceClient.cancel_job()`
- `RecordingRetrievalServiceClient.wait_for_terminal_status()`
- `RecordingRetrievalServiceClient.wait_for_results()`
- `RecordingRetrievalServiceClient.run_job()`

## 联调建议

父项目第一阶段联调建议直接使用 `run_job()`，只消费：

- `CreateJobRequest`（创建请求）
- `ResultsResponse`（结果响应）

联合调试时，再按需要下钻：

- `JobStatusResponse`（状态响应）
- `cancel_on_timeout`（超时取消）
- `/ui/analyze-text` 输入分析链路
- `llm_client.py` 的 `json_object` 路径

## 后续方向

- 如父项目需要同步调用面，可在现有异步 client（客户端）之上补一层 blocking wrapper（阻塞式封装）。
- 如后续转向真正的 `tool calling`（工具调用）协议，优先在 `llm_client.py` 新增旁路适配层，不覆盖当前稳定的 `json_object` 主路径。
