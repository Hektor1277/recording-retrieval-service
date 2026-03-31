# 环境启动说明

## 工作目录
```powershell
cd 'E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app'
```

## 必须使用的 Python
唯一推荐解释器：
```powershell
.\.venv\Scripts\python.exe
```

不要使用：
```powershell
E:\Anaconda\anaconda3\python.exe
```

原因：
- `Anaconda` 环境缺少 `playwright`
- 会导致 `browser rescue` 路径失效

## 必要本地配置
以下文件应存在：
- [platform-search.local.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/config/platform-search.local.json)
- [llm.local.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/config/llm.local.json)
- [bilibili-storage-state.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/config/bilibili-storage-state.json)

## 快速自检
```powershell
cd 'E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app'
$env:PYTHONPATH='.'
& '.\.venv\Scripts\python.exe' -c "import sys; print(sys.executable)"
& '.\.venv\Scripts\python.exe' -c "import playwright; print(playwright.__version__)"
& '.\.venv\Scripts\python.exe' -m pytest '.\tests' -q
```

## 如果 `playwright` 导入失败
先确认是不是跑错了解释器。

仅当 `.venv` 里也失败时，才继续检查：
- 本地浏览器安装
- `playwright` 依赖是否损坏
- `bilibili-storage-state.json` 是否失效

## 当前环境判定
本轮已确认：
- `.venv` 正常
- `playwright 1.58.0` 可用
- `Bilibili browser search` 在 `.venv` 下能真实返回目标 `BV`
