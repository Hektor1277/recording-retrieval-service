# Environment Reset Checklist

新线程恢复前，建议按顺序确认：

1. 进入工作仓库：
```powershell
cd 'E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app'
```

2. 检查工作区状态：
```powershell
git status --short
```

3. 检查虚拟环境 Python：
```powershell
& '.\.venv\Scripts\python.exe' --version
```

4. 检查测试框架可用：
```powershell
& '.\.venv\Scripts\python.exe' -m pytest --version
```

5. 检查关键本地配置是否存在：
- [platform-search.local.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/config/platform-search.local.json)
- [llm.local.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/config/llm.local.json)
- [bilibili-storage-state.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/config/bilibili-storage-state.json)

6. 如需浏览器链路，确认 Playwright/Edge 可用：
- 只在需要时再跑浏览器相关测试或脚本

7. 记录环境阻塞：
- 若遇到 `Permission denied`、`No module named pytest`、浏览器缺依赖、网络失败，先在新线程执行 `permission-env-autopilot` 的排障流程，再继续。
