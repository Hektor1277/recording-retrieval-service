# Preflight Checklist

## 执行顺序

### 1. 确认仓库状态
```powershell
cd 'E:\Workspace\codex\Introduction to Classical Music\tools\recording-retrieval-service\app'
git status --short
```

注意：
- 当前工作区本来就是 dirty 的
- 新线程不要把已有未提交改动误当成异常
- 重点确认没有意外的新漂移

### 2. 确认解释器与依赖
```powershell
$env:PYTHONPATH='.'
& '.\.venv\Scripts\python.exe' -c "import sys; print(sys.executable)"
& '.\.venv\Scripts\python.exe' -c "import playwright; print(playwright.__version__)"
```

### 3. 跑测试
```powershell
& '.\.venv\Scripts\python.exe' -m pytest '.\tests' -q
```

### 4. 跑一轮舒曼钢协完整评估
```powershell
& '.\.venv\Scripts\python.exe' '.\scripts\run_parent_work_eval.py' `
  --output '.\output\parent_work_eval_schumann_op54_results_resume.json' `
  --access-report '.\output\parent_work_eval_schumann_op54_access_resume.json' `
  --dataset-output '.\output\parent_work_eval_schumann_op54_dataset_resume.json'
```

### 5. 对比关键指标
恢复线程后至少要确认：
- `versionFinalHit`
- `versionCandidateHit`
- `strictMissReasons.recall_miss`

当前参照基线：
- [parent_work_eval_schumann_op54_results_v73.json](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/output/parent_work_eval_schumann_op54_results_v73.json)

历史最好目标：
- `versionFinalHit = 22/28`
- `versionCandidateHit = 23/28`

## 通过条件
- `.venv` 正常
- `playwright` 可导入
- `pytest` 通过
- 新跑的舒曼钢协评估能够稳定复现至少 `v73` 量级

只有完成这些后，才进入下一轮实现。
