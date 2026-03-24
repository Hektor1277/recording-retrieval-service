# Bernstein Ranking Stabilization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 稳定 `bernstein-fantastique-conductor-only` 的最终链接选择，避免 live 回归时正确 `Bilibili` 目标掉出 `finalLinks`。

**Architecture:** 先做根因定位，确认是 `exact-link ranking`（精确链接排序）还是 `final link filtering`（最终链接过滤）在无日期指挥场景里过度偏向 `YouTube`。修复保持最小改动，只调整相关排序或过滤规则，并用回归测试锁住行为。

**Tech Stack:** Python 3.13, pytest, PowerShell, real-data regression script

---

### Task 1: 计划与基线

**Files:**
- Create: `docs/plans/2026-03-24-bernstein-ranking-stabilization.md`
- Read: `docs/thread-handoff/2026-03-23/next_actions.md`
- Read: `output/real_data_focus_milestone_latest.json`
- Read: `output/real_data_focus_resume.json`

**Step 1: 读取交接与当前回归结果**

Run: `git status --short`

Expected: 只看到本轮文档与开发改动。

**Step 2: 记录 live 基线**

Run: `& '.\.venv\Scripts\python.exe' '.\scripts\real_data_regression.py' --only bernstein-fantastique-conductor-only --output '.\output\real_data_bernstein_baseline.json' --access-report '.\output\real_data_bernstein_baseline_access.json'`

Expected: 能稳定复现当前 `candidateHit=true` 但 `finalHit` 可能波动的问题。

**Step 3: 提交前检查**

Run: `git diff -- docs/plans/2026-03-24-bernstein-ranking-stabilization.md`

Expected: 只有新增计划文档。

### Task 2: 根因定位

**Files:**
- Read: `app/services/pipeline.py`
- Read: `tests/test_pipeline_logic.py`
- Read: `scripts/real_data_regression.py`

**Step 1: 提取候选链接排序证据**

Run: 针对 `Bernstein` 单场景打印 `same_recording_score`、标题锚点、年份冲突、平台、最终保留列表。

Expected: 明确知道正确 `Bilibili` 链接是在排序阶段落后，还是在最终过滤阶段被剔除。

**Step 2: 找到同类已工作的参考**

Run: 阅读 `Heifetz` 和现有 `exact-link` 测试。

Expected: 确认当前模糊上传簇规则对“主奏/指挥稀疏查询”的保护方式。

**Step 3: 写出单一假设**

Expected: 用一句话表述“我认为根因是 X，因为 Y”。

### Task 3: TDD 修复

**Files:**
- Modify: `tests/test_pipeline_logic.py`
- Modify: `app/services/pipeline.py`

**Step 1: 写失败测试**

新增一个最小测试，复现“无日期、仅指挥信息时，正确 `Bilibili` 完整录音被两个 `YouTube` 候选压出 `finalLinks`”。

**Step 2: 运行测试确认失败**

Run: `& '.\.venv\Scripts\python.exe' -m pytest '.\tests\test_pipeline_logic.py' -q`

Expected: 新测试失败，且失败原因与预期一致。

**Step 3: 最小化实现**

只修改和根因直接相关的排序/过滤逻辑，不顺手改其它规则。

**Step 4: 运行测试确认通过**

Run: `& '.\.venv\Scripts\python.exe' -m pytest '.\tests\test_pipeline_logic.py' -q`

Expected: 新旧相关测试一起通过。

### Task 4: 项目梳理与清洗

**Files:**
- Review: `output/`
- Review: `docs/thread-handoff/2026-03-23/`

**Step 1: 清理临时输出**

删除仅用于调试、无需纳入本次里程碑的临时文件。

**Step 2: 核对工作区**

Run: `git status --short`

Expected: 只剩本次应提交的代码、测试和必要文档变更。

### Task 5: 完整验证与提交

**Files:**
- Modify: `output/real_data_focus_resume.json`（如需要保留最新验证结果）

**Step 1: 跑完整测试**

Run: `& '.\.venv\Scripts\python.exe' -m pytest '.\tests' -q`

Expected: 全量通过。

**Step 2: 跑聚焦真实回归**

Run: `& '.\.venv\Scripts\python.exe' '.\scripts\real_data_regression.py' --only annie-full annie-no-group gieseking-full bernstein-fantastique-conductor-only heifetz-lead-only karajan-alpine-full --output '.\output\real_data_focus_resume.json' --access-report '.\output\real_data_focus_resume_access.json'`

Expected: `bernstein-fantastique-conductor-only` 不回退，聚焦集维持或优于当前基线。

**Step 3: 检查差异**

Run: `git diff --stat`

Expected: 改动范围与计划一致，没有无关噪音。

**Step 4: 提交并推送**

Run:
```bash
git add <relevant files>
git commit -m "fix: stabilize bernstein exact-link ranking"
git push
```

Expected: 本轮里程碑形成独立可追踪提交。
