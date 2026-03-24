# Bilibili Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Strengthen Bilibili retrieval quality and efficiency by preferring structured detail APIs over noisy page HTML for video hydration.

**Architecture:** Keep the current Bilibili search entrypoint, but add a detail hydration layer that fetches structured video metadata by `bvid/aid` before falling back to HTML or browser rendering. Use API detail fields as the primary source for title, description, uploader, duration, views, and page parts, then keep the existing HTML/browser path only as a resilience fallback when API data is unavailable or incomplete.

**Tech Stack:** Python, `httpx`, existing `PlatformSearchClients`, pytest regression tests, live regression scripts.

---

### Task 1: Capture the failing Bilibili detail gap

**Files:**
- Modify: `tests/test_search_connectivity.py`
- Modify: `app/services/platform_clients.py`
- Modify: `app/services/http_sources.py`

**Step 1: Write the failing test**

Add a regression test that simulates:
- `Bilibili` search returns a video URL
- `x/web-interface/view` returns structured detail JSON
- HTML page is sparse or noisy
- `_fetch_page_record()` still produces high-quality metadata without requiring browser fallback

**Step 2: Run test to verify it fails**

Run: `pytest .\tests\test_search_connectivity.py -q -k "bilibili_detail_api"`

Expected: FAIL because Bilibili detail hydration does not exist yet.

**Step 3: Write minimal implementation**

Add:
- Bilibili URL parsing helper (`bvid` / `aid`)
- `PlatformSearchClients.fetch_bilibili_video_detail(...)`
- HTTP source path that prefers API detail for Bilibili before HTML extraction

**Step 4: Run test to verify it passes**

Run: `pytest .\tests\test_search_connectivity.py -q -k "bilibili_detail_api"`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_search_connectivity.py app/services/platform_clients.py app/services/http_sources.py
git commit -m "fix: prefer bilibili detail api hydration"
```

### Task 2: Tighten Bilibili metadata cleaning

**Files:**
- Modify: `app/services/http_sources.py`
- Modify: `tests/test_search_connectivity.py`

**Step 1: Write the failing test**

Add a regression test where Bilibili structured detail contains:
- page part names
- performer metadata
- noisy or related-video style text

Assert that the cleaned metadata preserves useful recording signals while excluding known noise fragments.

**Step 2: Run test to verify it fails**

Run: `pytest .\tests\test_search_connectivity.py -q -k "bilibili_metadata_clean"`

Expected: FAIL because current cleaning is still page-text centric.

**Step 3: Write minimal implementation**

Update Bilibili metadata assembly to:
- use structured fields first
- limit free-text body to safe segments
- keep page-part text bounded
- avoid mixing unrelated page chrome into the scoring input

**Step 4: Run test to verify it passes**

Run: `pytest .\tests\test_search_connectivity.py -q -k "bilibili_metadata_clean"`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_search_connectivity.py app/services/http_sources.py
git commit -m "fix: tighten bilibili metadata cleaning"
```

### Task 3: Verify wider impact

**Files:**
- Verify only: `tests/*`
- Verify only: `scripts/real_data_regression.py`
- Review outputs: `output/*.json`

**Step 1: Run focused regression**

Run:
- `pytest .\tests -q`
- `python .\scripts\real_data_regression.py --only annie-full annie-no-group gieseking-full bohm-conductor-only --output .\output\real_data_bilibili_hardening_focus.json --access-report .\output\real_data_bilibili_hardening_focus_access.json`

Expected:
- pytest green
- no regression on Annie
- ideally improved Bilibili-heavy scenarios

**Step 2: Run wider regression if focus looks safe**

Run:
- `python .\scripts\real_data_regression.py --output .\output\real_data_full_verify.json --access-report .\output\real_data_full_verify_access.json`

Expected: Full snapshot for milestone decision.

**Step 3: Commit milestone**

```bash
git status --short --untracked-files=all
git commit -m "fix: harden bilibili hydration and cleanup"
git push
```
