# 风险与未决问题

## 当前风险
- 实时外网搜索高度依赖第三方平台返回，批量场景稳定性仍不足。
- `LLM` 请求偶尔会出现 `peer closed connection without sending complete message body`，这会导致归并退回规则模式。
- `Spring` 这类室内乐双人合作条目，在关键信息缺失时仍可能偏向单人或合辑候选。
- UI 中仍有部分 warning 文案为旧乱码字符串。

## 未决问题
- 是否要继续提高 `streaming` 搜索的 host 内部深度，还是改成更严格的 host 级阶段限时与部分返回。
- 是否需要针对 `YouTube` / `Bilibili` 增加更强的站点特化解析，而不是只靠通用标题/简介/正文规则。
- 是否需要引入专门的“室内乐协作者回补”策略：
  - 当仅给一个主参与者时，主动提升常见协作者版本的检索权重。
- 是否要把真实回归样本集合扩大到更多体裁，以防当前优化过拟合现有 8 条样本。

## 注意事项
- 父仓库与子仓库是两个 `git` 边界，不要混淆提交。
- 当前工作区是脏的，不能随意回滚用户已有改动。
- 新线程恢复后，优先读取：
  - `.codex-handoff/current/`
  - `docs/thread-handoff/2026-03-21/`
  - `output/real_data_round11_b.json`
  - `output/real_data_focus_round11_h.json`
