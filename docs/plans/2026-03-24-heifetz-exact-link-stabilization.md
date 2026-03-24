# Heifetz Exact-Link Stabilization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 稳定 `heifetz-lead-only` 的 `exact-link ranking`（精确链接排序），让聚焦回归在 live 波动下更稳定地保留目标 `YouTube` 链接。

**Architecture:** 先确认 `Heifetz` 的问题发生在候选召回、模糊上传簇排序，还是最终链接裁剪。修复只针对 `ambiguous upload cluster`（模糊上传簇）和 `final link limit`（最终链接数量限制）的最小规则调整，并通过测试锁住行为。

**Tech Stack:** Python 3.13, pytest, PowerShell, real-data regression script

---

### Task 1: 基线与计划

**Files:**
- Create: `docs/plans/2026-03-24-heifetz-exact-link-stabilization.md`
- Read: `output/real_data_focus_resume.json`
- Read: `tests/test_pipeline_logic.py`

**Step 1: 记录当前聚焦回归表现**

Run: `& '.\.venv\Scripts\python.exe' '.\scripts\real_data_regression.py' --only heifetz-lead-only --output '.\output\real_data_heifetz_baseline.json' --access-report '.\output\real_data_heifetz_baseline_access.json'`

Expected: 明确单场景和批量场景是否表现一致。

**Step 2: 记录 batch 行为**

Run: 用同一个 retriever 顺序执行聚焦场景，打印 `Heifetz` 的 final/candidate 链接。

Expected: 定位波动发生在 fresh 还是 reused 路径。

### Task 2: 根因定位

**Files:**
- Read: `app/services/pipeline.py`
- Read: `tests/test_pipeline_logic.py`

**Step 1: 提取排序证据**

打印候选链接的 `confidence`、标题锚点、时长、上传者、浏览量、作品号命中。

**Step 2: 对照已有 Heifetz 测试**

确认现有测试已覆盖什么，缺口在哪里。

**Step 3: 写出单一假设**

Expected: 用一句话说明当前回退的根因。

### Task 3: TDD 修复

**Files:**
- Modify: `tests/test_pipeline_logic.py`
- Modify: `app/services/pipeline.py`

**Step 1: 新增失败测试**

复现 `heifetz-lead-only` 在模糊上传簇里丢失 canonical upload（规范上传）的情况。

**Step 2: 运行失败测试**

Run: `& '.\.venv\Scripts\python.exe' -m pytest '.\tests\test_pipeline_logic.py' -q`

Expected: 新测试先失败。

**Step 3: 最小修复**

仅改 `Heifetz` 暴露出的排序/裁剪规则，不顺手做无关重构。

**Step 4: 运行相关测试**

Run: `& '.\.venv\Scripts\python.exe' -m pytest '.\tests\test_pipeline_logic.py' -q`

Expected: 相关测试全部通过。

### Task 4: 里程碑验证与提交

**Step 1: 清理调试产物**

删除 `Heifetz` 调试输出。

**Step 2: 完整验证**

Run:
- `& '.\.venv\Scripts\python.exe' -m pytest '.\tests' -q`
- `& '.\.venv\Scripts\python.exe' '.\scripts\real_data_regression.py' --only annie-full annie-no-group gieseking-full bernstein-fantastique-conductor-only heifetz-lead-only karajan-alpine-full --output '.\output\real_data_focus_resume.json' --access-report '.\output\real_data_focus_resume_access.json'`
- `& '.\.venv\Scripts\python.exe' '.\scripts\real_data_regression.py' --output '.\output\real_data_full_verify.json' --access-report '.\output\real_data_full_verify_access.json'`

**Step 3: 提交并推送**

Run:
```bash
git add <relevant files>
git commit -m "fix: stabilize heifetz exact-link selection"
git push
```
