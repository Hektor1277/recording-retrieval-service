# 下一轮直接工作

## 第一优先级
- 继续攻真实长尾 `recall_miss`
- 当前最值得切入的样本：
  - `Grinberg / Eliasberg 1958`
  - `Richter / Ferencsik 1954`
  - `de Lara / Whyte 1951`
  - `Kempff / Dorati 1959`

建议切入点：
- 增强长尾钢琴家/指挥的 `latin alias / transliteration`（拉丁别名/转写）富化
- 检查父项目 `people.json` 是否还缺关键别名
- 对 `Richter / Grinberg / de Lara` 这类人名增加更贴近站内标题习惯的查询形式

## 第二优先级
- 单独标注父项目 `available_but_suspicious` 真值
- 当前明确可疑的是 `Alicia de Larrocha / Sawallisch 1977` 的两条原始链接：
  - `bilibili:BV1EUE4zgEDH`
  - `youtube:j4kYjcLRpNY`

建议切入点：
- 不要先改检索口径
- 先把这类历史真值在评估报告里单独标记出来，避免污染检索效果判断

## 第三优先级
- 联调链路继续向“父项目只关心接口和协议”推进
- 当前入口：
  [service_client.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/service_client.py)

建议切入点：
- 在不改现有 `/ui/analyze-text` 主路径的前提下，继续审视：
  - [llm_client.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/services/llm_client.py)
  - [main.py](/E:/Workspace/codex/Introduction%20to%20Classical%20Music/tools/recording-retrieval-service/app/app/main.py)

## 建议验证顺序
1. 先跑定点 `pytest`
2. 再跑舒曼真实集或更小的焦点子集
3. 最后再跑整套 `pytest`
