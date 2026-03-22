# 环境恢复说明

## 项目根目录
- 父目录：`E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service`
- 实现目录：`E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app`

## 进入开发前应确认
- 当前应在 `app/` 子仓库内工作。
- 虚拟环境存在：`.venv`
- Python 版本：`3.13.5`
- LLM 配置文件：
  - 旧文本配置：`materials/source-profiles/LLM config.txt`
  - 运行时配置：`config/llm.local.json`

## 最常用验证命令
```powershell
& '.venv\Scripts\python.exe' -m pytest tests -q
& '.venv\Scripts\python.exe' '.\scripts\real_data_regression.py' --output '.\output\real_data_round11_b.json'
& '.venv\Scripts\python.exe' '.\scripts\real_data_regression.py' --only annie-no-group spring-full spring-lead-only --output '.\output\real_data_focus_round11_h.json'
```

## 常用单条诊断方式
- 用内联 `python` 脚本调用：
  - `build_default_retriever()`
  - `sample_scenarios()`
  - `build_item()`
- 直接打印：
  - `profile.queries`
  - `result.link_candidates`
  - `result.result.links`
  - `result.warnings`

## 需要优先查看的文件
- `app/services/pipeline.py`
- `app/services/http_sources.py`
- `app/services/input_analysis.py`
- `app/services/llm_client.py`
- `scripts/real_data_regression.py`
- `tests/test_pipeline_logic.py`
- `tests/test_search_connectivity.py`

## 当前环境注意事项
- 批量真实回归速度较慢，网络波动会放大结果差异。
- `LLM` 连接偶尔不稳定，新线程看到归并失败时不要先怀疑评分规则。
- 便携包与 UI 链路当前不是本轮优先事项，优先看资源链接回归。
