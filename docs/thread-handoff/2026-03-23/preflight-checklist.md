# Preflight 预检清单

## 新线程开始前必须确认
- 当前目录是 [app](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app)
- `git status --short` 为空，或你明确知道新增改动来自哪里
- `.venv` 可用，`python -m pytest` 能运行
- 网络可访问 `www.youtube.com`、`api.bilibili.com`、`search.bilibili.com`、`www.bing.com`
- 本地 `platform-search.local.json` 存在且未丢失 `bilibili` 配置
- 如需 `Bilibili` 强上下文，确认 `storage state` 仍有效；如果失效，重新抓取并同步 `Cookie`

## 推荐检查命令
```powershell
cd 'E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app'
git status --short
& '.\.venv\Scripts\python.exe' -m pytest '.\tests' -q
```

## 用户确认门禁
新线程开始后，不要直接进入实现；先让用户确认：
- 环境仍然可用
- 网络与权限仍然通过
- 可以继续开发
