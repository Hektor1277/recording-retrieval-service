# 交接总览

本轮完成了一个可提交里程碑，重点是 `Bilibili retrieval`（Bilibili 检索链路）加固、`exact-link ranking`（精确链接排序）强化，以及本地配置闭环补齐。

已完成并推送的提交：
- 分支：`codex/retrieval-pipeline-v1`
- 提交：`333c8382a9ffb3382a9be90accb08f3a69b0af34`
- 提交信息：`feat: harden bilibili retrieval and exact-link ranking`

核心结果：
- `pytest` 全量：`130 passed`
- 聚焦真实回归：`finalHit=5/6`，`candidateHit=6/6`
- 全量真实回归：`finalHit=9/15`，`candidateHit=12/15`

当前最值得继续的方向：
- `Heifetz lead-only` 的同版多上传歧义
- 长批次全量回归的稳定性，尤其是 `Bohm` 和 `Arrau`
