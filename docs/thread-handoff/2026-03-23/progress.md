# 当前进展

## 代码层
- [browser_fetcher.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/browser_fetcher.py)
  已支持共享浏览器上下文、`storage state` 复用、`Cookie/userAgent/referer` 注入、`Bilibili` 导航重试
- [http_sources.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/http_sources.py)
  已支持 `WBI search`、`Bilibili`/`YouTube` 主平台并发、站点级预算调整、`primary-only concerto query`、`site:` 回捞与浏览器回退
- [pipeline.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/pipeline.py)
  已加强 `exact-link` 过滤、年份冲突处理、模糊上传簇排序、最终链接保留逻辑
- [platform_clients.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/platform_clients.py)
  已支持 `Bilibili WBI` 相关调用

## 配置与工具
- [capture_bilibili_storage_state.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/scripts/capture_bilibili_storage_state.py)
  可抓取登录态
- [sync_bilibili_cookie_from_storage_state.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/scripts/sync_bilibili_cookie_from_storage_state.py)
  可从 `storage state` 自动同步 `Cookie`
- [bilibili-storage-state-setup.md](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/docs/bilibili-storage-state-setup.md)
  已补完整使用说明

## 验证结果
- 全量测试：
  `& '.\.venv\Scripts\python.exe' -m pytest '.\tests' -q`
  结果：`130 passed`
- 聚焦回归：
  [real_data_focus_milestone_latest.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/output/real_data_focus_milestone_latest.json)
  结果：`5/6 finalHit`, `6/6 candidateHit`
- 全量回归：
  [real_data_milestone_full.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/output/real_data_milestone_full.json)
  结果：`9/15 finalHit`, `12/15 candidateHit`
