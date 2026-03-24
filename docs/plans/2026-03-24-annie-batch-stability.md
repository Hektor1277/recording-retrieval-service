# Annie Batch Stability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 稳定 `annie-full` 与 `annie-no-group` 在长批次 live 回归下的 final links（最终链接），避免出现 `focus` 通过但 `full` 退化为空或错链。

**Architecture:** 先对比 `fresh`、`focus-prefix`、`full-prefix` 三类执行路径，确认问题是候选召回、排序裁剪，还是跨场景共享状态导致的结果漂移。修复优先选可泛化的链路层改动，并补一个更接近真实批次执行方式的验证。

**Tech Stack:** Python 3.13, pytest, PowerShell, real-data regression script

---

### Task 1: 基线锁定

**Files:**
- Create: `docs/plans/2026-03-24-annie-batch-stability.md`
- Read: `output/real_data_focus_resume.json`

**Step 1: fresh 单场景基线**

Run: `& '.\.venv\Scripts\python.exe' '.\scripts\real_data_regression.py' --only annie-full annie-no-group --output '.\output\real_data_annie_baseline.json' --access-report '.\output\real_data_annie_baseline_access.json'`

**Step 2: prefix 对照**

Run: 用同一个 retriever 顺序跑 `focus-prefix` 和 `full-prefix`，打印 `Annie` 的 candidate/final links。

### Task 2: 根因定位

**Files:**
- Read: `app/services/http_sources.py`
- Read: `app/services/pipeline.py`
- Read: `tests/test_search_connectivity.py`

**Step 1: 抓原始候选证据**

打印 `Annie` 命中的候选链接、分数、标题、年份、平台与被裁剪原因。

**Step 2: 单一假设**

用一句话说明到底是检索链路、状态污染还是排序规则导致退化。

### Task 3: TDD 修复

**Files:**
- Modify: `tests/test_search_connectivity.py` or `tests/test_pipeline_logic.py`
- Modify: target production file(s)

**Step 1: 写失败测试**

优先写能复现 long-batch 退化的最小测试；必要时补一个组件级顺序敏感测试。

**Step 2: 先看它失败**

Run: 对应测试文件最小集合。

**Step 3: 最小修复**

只修与根因直接相关的逻辑，不顺带做无关清理。

**Step 4: 再看它变绿**

Run: 对应测试文件全量。

### Task 4: 完整验证与提交

**Step 1: 全量测试**

Run: `& '.\.venv\Scripts\python.exe' -m pytest '.\tests' -q`

**Step 2: 聚焦真实回归**

Run: `& '.\.venv\Scripts\python.exe' '.\scripts\real_data_regression.py' --only annie-full annie-no-group gieseking-full bernstein-fantastique-conductor-only heifetz-lead-only karajan-alpine-full --output '.\output\real_data_focus_resume.json' --access-report '.\output\real_data_focus_resume_access.json'`

**Step 3: 全量真实回归**

Run: `& '.\.venv\Scripts\python.exe' '.\scripts\real_data_regression.py' --output '.\output\real_data_full_verify.json' --access-report '.\output\real_data_full_verify_access.json'`

**Step 4: 清理、提交、推送**

Run:
```bash
git add <relevant files>
git commit -m "fix: stabilize annie batch retrieval"
git push
```
