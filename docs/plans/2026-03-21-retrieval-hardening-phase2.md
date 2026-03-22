# Retrieval Hardening Phase 2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 移除无效搜索引擎路径，基于真实访问报告强化资源平台抓取与精确链接判别，并扩展真实回归样本。

**Architecture:** 先做根因调查，确认 `DuckDuckGo` 是代码级引入而非来源文档配置；再将访问失败问题拆为平台行为、站点限制与项目策略三层。实现上继续沿用 TDD，分别修改搜索策略、访问遥测与判别规则，并用扩展样本集验证。

**Tech Stack:** Python, FastAPI, httpx, Playwright, pytest

---

### Task 1: Confirm Source Of DuckDuckGo Usage

**Files:**
- Read: `materials/source-profiles/high-quality.txt`
- Read: `materials/source-profiles/streaming.txt`
- Modify: `tests/test_search_connectivity.py`
- Modify: `app/services/http_sources.py`

**Step 1: Write the failing test**
- Add a test asserting the engine path no longer queries `html.duckduckgo.com`.

**Step 2: Run test to verify it fails**
- Run: `pytest tests/test_search_connectivity.py -q`

**Step 3: Write minimal implementation**
- Remove DuckDuckGo from engine fan-out and keep Bing as the default fallback search engine.

**Step 4: Run test to verify it passes**
- Run: `pytest tests/test_search_connectivity.py -q`

### Task 2: Investigate Platform Failure Patterns

**Files:**
- Read: `output/real_data_round12_full_pass2_access.json`
- Modify: `scripts/real_data_regression.py`

**Step 1: Add a regression assertion**
- Ensure access reports carry host-level status, timeout, depth and failure counts.

**Step 2: Run targeted tests**
- Run: `pytest tests/test_real_data_regression.py -q`

**Step 3: Write minimal implementation**
- Keep host summary output stable and include enough data for comparing retries/timeouts.

**Step 4: Run test to verify it passes**
- Run: `pytest tests/test_real_data_regression.py -q`

### Task 3: Improve Exact-Link Disambiguation

**Files:**
- Modify: `tests/test_search_connectivity.py`
- Modify: `app/services/http_sources.py`
- Modify: `app/services/llm_client.py`

**Step 1: Write failing tests**
- Add targeted tests for “same recording, different upload” and “sparse collaborator input” cases.

**Step 2: Run failing tests**
- Run: `pytest tests/test_search_connectivity.py tests/test_pipeline_logic.py -q`

**Step 3: Write minimal implementation**
- Tighten scoring and LLM prompt/routing so exact target links outrank adjacent uploads.

**Step 4: Re-run tests**
- Run: `pytest tests/test_search_connectivity.py tests/test_pipeline_logic.py -q`

### Task 4: Expand Regression Sample Coverage

**Files:**
- Modify: `scripts/real_data_regression.py`
- Modify: `tests/test_real_data_regression.py`

**Step 1: Write failing test**
- Add a test covering expanded scenario generation and masked variants.

**Step 2: Run failing test**
- Run: `pytest tests/test_real_data_regression.py -q`

**Step 3: Write minimal implementation**
- Add more parent-project scenarios and sparse/masked variants for robustness testing.

**Step 4: Verify**
- Run: `pytest tests/test_real_data_regression.py -q`
- Run: `python .\scripts\real_data_regression.py --output .\output\real_data_round_next.json --access-report .\output\real_data_round_next_access.json`
