# UI And Playwright Fallback Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Playwright fallback for JS-heavy sources and rebuild the standalone UI into a workspace/display split that matches the retrieval workflow.

**Architecture:** Keep the owner-facing `/v1/jobs*` contract unchanged. Add browser fallback inside the source provider layer, expose only UI-local helper endpoints for document opening and text analysis if needed, and move the UI to a stateful client-side workspace that renders an entry-centric display instead of raw JSON panels.

**Tech Stack:** Python 3.13, FastAPI, asyncio, httpx, Playwright for Python, vanilla JS, CSS, pytest, PyInstaller.

---

### Task 1: Lock The New Behaviors With Tests

**Files:**
- Modify: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\tests\test_standalone_ui.py`
- Modify: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\tests\test_pipeline_logic.py`
- Create: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\tests\test_ui_support_endpoints.py`
- Create: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\tests\test_playwright_fallback.py`

**Step 1: Write failing UI tests**

- Assert the index page contains:
  - workspace buttons for `文本分析` / `开始搜索` / `刷新条目`
  - a status bar
  - display tabs container
  - no raw JSON preview headings
- Assert a UI helper endpoint can expose current source-profile file paths and open-target metadata without touching owner APIs.

**Step 2: Run the focused tests and confirm they fail**

Run:

```powershell
& '.venv\Scripts\python.exe' -m pytest tests\test_standalone_ui.py tests\test_ui_support_endpoints.py -q
```

Expected: failures on missing workspace/display UI and helper endpoints.

**Step 3: Write failing fallback tests**

- Assert the source provider falls back to a browser fetcher when HTTP fetch returns insufficient metadata.
- Assert the fallback failure degrades to warnings instead of crashing the item.

**Step 4: Run the focused tests and confirm they fail**

Run:

```powershell
& '.venv\Scripts\python.exe' -m pytest tests\test_pipeline_logic.py tests\test_playwright_fallback.py -q
```

Expected: failures on missing browser fallback integration.

### Task 2: Add Playwright Fallback In The Retrieval Layer

**Files:**
- Modify: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\app\services\http_sources.py`
- Modify: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\app\services\retrieval.py`
- Create: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\app\services\browser_fetcher.py`
- Modify: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\pyproject.toml`

**Step 1: Implement a browser fetcher wrapper**

- Create a small service that:
  - lazily imports Playwright
  - prefers system Edge via `channel="msedge"`
  - uses a global semaphore of 2
  - returns title/meta text for a URL
  - degrades cleanly when Playwright or Edge is unavailable

**Step 2: Route HTTP fetch misses into browser fallback**

- In `HttpSourceProvider`, use browser fallback only when:
  - HTTP fetch fails
  - or metadata is empty / clearly insufficient
- Keep timeouts short and bounded by the pipeline deadline.

**Step 3: Verify tests pass**

Run:

```powershell
& '.venv\Scripts\python.exe' -m pytest tests\test_pipeline_logic.py tests\test_playwright_fallback.py -q
```

Expected: PASS.

### Task 3: Rebuild The Standalone UI Around Workspace And Display

**Files:**
- Modify: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\app\ui\index.html`
- Modify: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\app\ui\assets\app.js`
- Modify: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\app\ui\assets\styles.css`
- Modify: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\app\main.py`

**Step 1: Add UI-only helper endpoints**

- Add endpoints to:
  - return source-profile file paths currently in use
  - trigger OS open for the two profile directories or representative files
- Do not touch `/v1/jobs*`.

**Step 2: Replace raw debug panels with entry-centric UI**

- Left workspace:
  - raw text
  - core fields
  - work type selector
  - `文本分析`, `开始搜索`, `刷新条目`
  - buttons to open `high-quality` and `streaming` profile files
- Right display:
  - top tab bar
  - one entry card showing the current selected variant
  - status bar only, no JSON console panels

**Step 3: Use client state for preview and search results**

- `文本分析`: parse raw text and fill workspace fields
- `刷新条目`: update right-side preview entry from current workspace
- `开始搜索`: submit the standard `/v1/jobs` request and merge the result into display state
- When multiple candidate variants exist, build tabs using distinguishing labels such as orchestra / platform / source title.

**Step 4: Verify tests pass**

Run:

```powershell
& '.venv\Scripts\python.exe' -m pytest tests\test_standalone_ui.py tests\test_ui_support_endpoints.py -q
```

Expected: PASS.

### Task 4: Ship Editable Source-Profile Templates

**Files:**
- Modify: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\materials\source-profiles\high-quality\global.txt`
- Modify: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\materials\source-profiles\high-quality\orchestral.txt`
- Modify: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\materials\source-profiles\high-quality\concerto.txt`
- Modify: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\materials\source-profiles\high-quality\opera_vocal.txt`
- Modify: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\materials\source-profiles\high-quality\chamber_solo.txt`
- Modify: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\materials\source-profiles\high-quality\piano.txt`
- Modify: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\materials\source-profiles\high-quality\violin.txt`
- Modify: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\materials\source-profiles\streaming\global.txt`
- Modify: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\materials\source-profiles\streaming\orchestral.txt`
- Modify: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\materials\source-profiles\streaming\concerto.txt`
- Modify: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\materials\source-profiles\streaming\opera_vocal.txt`
- Modify: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\materials\source-profiles\streaming\chamber_solo.txt`
- Modify: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\materials\source-profiles\streaming\live.txt`
- Modify: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\materials\source-profiles\streaming\piano.txt`
- Modify: `E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app\materials\source-profiles\streaming\violin.txt`

**Step 1: Replace placeholder content with commented templates**

- Each file must explain:
  - one line per hostname / URL
  - top to bottom = higher to lower priority
  - `#` lines are comments
  - how global/category/tag stacking works

**Step 2: Add category-specific guidance for high-quality sources**

- Explain that:
  - `global.txt` is always loaded first
  - category file applies next
  - tag files like `piano.txt` or `violin.txt` refine the category

**Step 3: Verify the loader still accepts them**

Run:

```powershell
& '.venv\Scripts\python.exe' -m pytest tests\test_source_profiles.py -q
```

Expected: PASS.

### Task 5: Full Verification And Packaging

**Files:**
- Verify only

**Step 1: Run the full test suite**

```powershell
& '.venv\Scripts\python.exe' -m pytest tests -q
```

Expected: all tests pass.

**Step 2: Build the portable package**

```powershell
cmd /c build-portable.cmd
```

Expected: zip and `dist\portable` updated successfully.

**Step 3: Run real browser smoke checks**

- Start source service on an isolated port.
- Start portable service on another isolated port.
- Use Playwright to:
  - open the UI
  - click `文本分析`
  - click `刷新条目`
  - click `开始搜索`
  - confirm the right-side entry updates and status bar changes
  - capture screenshots under `output\playwright\`

**Step 4: Report exact evidence**

- test command output
- build output path
- screenshot paths
- any remaining known limitations
