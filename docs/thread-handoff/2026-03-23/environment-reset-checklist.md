# 环境重置检查

当新线程怀疑环境已漂移时，按这个顺序检查：

1. `git status --short`
2. `& '.\.venv\Scripts\python.exe' -V`
3. `& '.\.venv\Scripts\python.exe' -m pytest '.\tests' -q`
4. 检查 [platform-search.local.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/config/platform-search.local.json) 是否仍在
5. 检查 [bilibili-storage-state-setup.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/docs/bilibili-storage-state-setup.md) 指定的登录态与 Cookie 同步流程是否仍可执行

如果 `Bilibili` 搜索明显退化：
- 先重新抓取 `storage state`
- 再运行 `sync_bilibili_cookie_from_storage_state.py`
- 最后重跑聚焦回归
