# Platform API-First Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 YouTube、Apple Music、Bilibili 建立 API-first 搜索通道、网页降级路径和多上传候选链接策略，并补齐用户配置清单。

**Architecture:** 新增独立的平台搜索配置层与平台 API 客户端层，`HttpSourceProvider` 只负责调度“API 搜索 -> 网页搜索 -> 页面水合”链路。平台访问状态继续纳入统一访问遥测，最终结果允许在“同版本不同上传”场景下保留多个高置信链接供用户选择。

**Tech Stack:** Python, FastAPI, httpx, pytest, JSON config

---

### Task 1: Add Platform Search Config

**Files:**
- Create: `app/services/platform_search_config.py`
- Create: `config/platform-search.example.json`
- Modify: `app/services/retrieval.py`
- Test: `tests/test_platform_search_config.py`

**Step 1: Write the failing test**
- 验证 `platform-search.local.json` 可读取 YouTube API key、Apple developer token、Bilibili cookie/header，并支持环境变量覆盖。

**Step 2: Run test to verify it fails**
- Run: `pytest tests/test_platform_search_config.py -q`

**Step 3: Write minimal implementation**
- 实现配置 dataclass、默认路径、示例文件和加载逻辑。

**Step 4: Run test to verify it passes**
- Run: `pytest tests/test_platform_search_config.py -q`

### Task 2: Implement Platform API Clients

**Files:**
- Create: `app/services/platform_clients.py`
- Modify: `app/services/http_sources.py`
- Test: `tests/test_search_connectivity.py`

**Step 1: Write the failing test**
- 为 YouTube API、Apple Music API、Bilibili API 各写一条“优先使用 API，失败再回退网页”的测试。

**Step 2: Run test to verify it fails**
- Run: `pytest tests/test_search_connectivity.py -q`

**Step 3: Write minimal implementation**
- 新建平台客户端。
- YouTube: `search.list`
- Apple Music: catalog search API
- Bilibili: web-interface search API with configurable headers/cookie
- 失败时记录 API 访问遥测并自动降级到现有网页搜索。

**Step 4: Run test to verify it passes**
- Run: `pytest tests/test_search_connectivity.py -q`

### Task 3: Keep Multiple Equivalent Upload Links

**Files:**
- Modify: `app/services/pipeline.py`
- Modify: `tests/test_pipeline_logic.py`

**Step 1: Write the failing test**
- 验证同版本多上传且关键信息一致时，最终结果保留多个候选资源链接供用户选择。

**Step 2: Run test to verify it fails**
- Run: `pytest tests/test_pipeline_logic.py -q`

**Step 3: Write minimal implementation**
- 调整 final link 选择策略，对高相似度、近分数的平台链接保留更多条目。

**Step 4: Run test to verify it passes**
- Run: `pytest tests/test_pipeline_logic.py -q`

### Task 4: Add User Setup Checklist

**Files:**
- Create: `docs/platform-api-setup-checklist.md`
- Modify: `README.md`

**Step 1: Write the failing test**
- 不需要自动化测试；文档需覆盖用户注册、验证码、token/cookie 获取、配置路径和验证命令。

**Step 2: Write minimal implementation**
- 给出 YouTube、Apple Music、Bilibili 各自的注册/配置步骤，以及最小验证命令。

### Task 5: Verify With Regression

**Files:**
- Modify: `scripts/real_data_regression.py` if needed
- Output: `output/real_data_round_platform_api_first.json`
- Output: `output/real_data_round_platform_api_first_access.json`

**Step 1: Run targeted verification**
- Run: `pytest tests -q`

**Step 2: Run regression**
- Run: `python .\scripts\real_data_regression.py --output .\output\real_data_round_platform_api_first.json --access-report .\output\real_data_round_platform_api_first_access.json`

**Step 3: Inspect access summary**
- 对比 `www.googleapis.com`、`api.music.apple.com`、`api.bilibili.com`、`www.youtube.com`、`search.bilibili.com`、`music.apple.com` 的访问状态。
