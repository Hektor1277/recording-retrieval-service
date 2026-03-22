# 线程切换总览

本目录是 `2026-03-21` 的线程交接源文件，供 `thread-handoff`（线程交接）技能导出正式交接包时使用。

## 文件说明
- `project_context.md`：项目定位、目标与当前重点
- `progress.md`：当前实现进度与已验证结果
- `decisions.md`：已固定的技术与产品决策
- `next_actions.md`：新线程应直接执行的动作
- `risks_open_questions.md`：风险、未决问题、踩坑点
- `environment_bootstrap.md`：环境恢复与常用命令

## 推荐恢复顺序
1. 读取 `.codex-handoff/current/` 正式交接包
2. 读取本目录源文件
3. 执行 `preflight checklist`（预检清单）
4. 先跑测试，再跑真实回归，再继续编码
