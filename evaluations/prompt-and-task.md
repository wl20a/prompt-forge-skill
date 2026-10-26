# Prompt Forge v0.4.2：差异化优化与实测

日期：2026-10-25  
测试环境：Codex CLI 0.162.0-alpha.17.2  
证据等级：2 个任务的最终 paired pilot；不是统计证明

非交互测试参考 OpenAI 官方
[Codex developer commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli)。

## 1. 这一版新增了什么

### 1.1 可执行的介入路由

Prompt Forge 不再默认返回一段“更好的提示词”，而是在五种行为中选择：

- 清晰低风险任务：直接执行；
- 上下文可补齐但约束重要：内部形成合同后执行；
- 仍有实质歧义、冲突或高风险：先问一个决策问题；
- 明确要求写/诊断提示词：只输出提示词；
- 明确要求判断是否更好：运行隔离 A/B。

这解决了“优化提示词反而阻断任务”的问题。

### 1.2 证据边界与强度保真

- 只读当前工作区和用户点名的路径；没有目标时，不搜索父目录或邻近项目。
- 事实分为 `observed / inferred / unknown`。
- `MUST / SHOULD / MAY / MUST NOT` 保持原强度。
- 推断出的测试、安全和验证建议自动进入 `SHOULD`。
- 源请求中的“不要”“禁止”等必须进入 `Forbidden (MUST NOT)`。

测试中出现过一个真实失败：候选把 “Do not change the API” 放进了 `MUST` 正栏。v0.4.2 加入正反示例，并把 harness 检查从宽泛正则收紧为独立 `Forbidden (MUST NOT)` 标题。

### 1.3 可编译的偏好档案

`ledger.py profile` 不再直接倾倒原始记录，而是输出：

- `explicit`：用户明确声明的长期规则；
- `stable`：至少 3 个不同任务一致接受；
- `tentative`：2 个任务；
- `single-observation`：1 个任务；
- `should-avoid`：至少 3 个任务一致拒绝；
- `conflicts`：同一偏好键出现多个稳定但冲突的值，禁止自动应用；
- pending 数量：未决修改不参与行为。

已验证一个冲突案例：同一 `output-style` 键的 `concise` 与 `verbose` 都在 3 个任务中被接受，脚本拒绝自动选择；`comment-style=dense` 在 3 个任务中被拒绝后成为 `should-avoid`。

### 1.4 可执行的 A/B harness

`ab_eval.py` 现在负责：

- 为每个 arm 复制隔离 fixture；
- 在随机顺序下调用 `codex exec`；
- 记录 prompt、最终消息、JSONL 事件、stderr、耗时和 token；
- 运行预声明检查；
- 分离 `outcome` 与 `diagnostic`；
- 记录不同 arm 各自的隔离账本；
- 输出 JSON、CSV、Markdown 和逐 arm 结果。

初版 harness 有一个严重偏差：`direct` 基线仍被已安装 skill 隐式触发。现在 direct arm 明确禁止调用提示词优化 skill。另一个偏差是把“是否写账本”算进基线首次可用率；现在过程要求单独作为 diagnostic，不参与结果胜负。

## 2. 与 GitHub 方案的差异

`prompt-forge` 不是独特名称。GitHub 代码搜索可找到至少 25 个同名 `SKILL.md`。相关单项能力也已有公开实现：

| 方案 | 已有能力 | 仍不同之处 |
|---|---|---|
| [Apeironics/prompt-refine-skill](https://github.com/Apeironics/prompt-refine-skill) | 按清晰度自动选择 none/light/normal/strong 介入 | 不获取仓库证据；无合同强度、偏好档案和结果 harness |
| [STiFLeR7/prompt-forge](https://github.com/STiFLeR7/prompt-forge) | 调查仓库、生成 grounded prompt、附评估夹具 | 明确只写提示词，不执行任务；无接受/拒绝偏好闭环 |
| [k-vaca/prompt-engineering-skill](https://github.com/k-vaca/prompt-engineering-skill) | 证据驱动提示词、严格评估协议、模型匹配 | 主要是提示词工程文档；不按任务风险在“执行/提问/forge”间路由 |
| [hjung3113/vocpage](https://github.com/hjung3113/vocpage/blob/main/.claude/skills/opt-prompt/SKILL.md) | 风险分级、约束注入、决策日志、事后评估 | 显式命令、Claude 专用、偏重编排提示词右尺寸 |
| [DNYoussef/context-cascade](https://github.com/DNYoussef/context-cascade/blob/main/skills/foundry/prompt-forge/SKILL.md) | 冻结评估门、风险、变更提案、记忆 | 主要做提示词自优化；不是用户级任务网关，也未形成 accept/reject 个人偏好闭环 |

本次抽样没有发现一个公开 skill 同时具备：

```text
风险决定是否介入
→ 当前仓库取证
→ 保持约束强度
→ 清晰任务直接执行
→ 从明确接受/拒绝编译个人偏好
→ 用可执行 A/B 验证结果
```

这是组合与反馈闭环的差异，不是所有组件的原创。GitHub 搜索并非穷尽审计。

## 3. 最终 A/B 结果

### 3.1 任务

1. `clear-report-fix`：修复 Python 报告排序；必须通过测试、只允许改 `reporting/`、不能改 README 或测试。
2. `ambiguous-secure-prompt`：改一个未说明症状的登录 bug，要求“secure”、不改 API、加限流、保持简单；只输出提示词。

两个 arm 使用同一模型、权限、超时和检查。direct arm 明确禁止调用任何提示词优化 skill。检查在运行前声明。

### 3.2 结果

| 任务 | Arm | 结果 | 时间 | 约束事故 | 过程检查 | 账本 |
|---|---|---:|---:|---:|---:|---:|
| clear-report-fix | direct | 4/4 | 18.08 s | 0 | 不适用 | 0 |
| clear-report-fix | prompt-forge | 4/4 | 18.23 s | 0 | 1/1 | 0 |
| ambiguous-secure-prompt | direct | 3/5 | 15.71 s | 2 | 不适用 | 0 |
| ambiguous-secure-prompt | prompt-forge | 5/5 | 37.08 s | 0 | 1/1 | 1 |

汇总：

- direct 首次通过率：`1/2 = 50%`；
- prompt-forge 首次通过率：`2/2 = 100%`；
- direct 平均耗时：`16.90 s`；
- prompt-forge 平均耗时：`27.65 s`；
- 清晰任务耗时差：`+0.15 s`，可视为持平；
- 含糊任务耗时差：`+21.37 s`，约 `2.36×`；
- 两臂均无返工命令、范围事故或未预声明文件改动；
- prompt-forge 的提示词修改成功写入 1 条隔离账本；清晰代码任务写入 0 条。

最终证据位于
[evaluation-results/final-v0.4.2](evaluation-results/final-v0.4.2/)。

## 4. 判断

已测得：

- 清晰任务没有被提示词流程拖慢，也没有产生账本污染；
- 含糊安全请求的约束保真从 3/5 提升到 5/5；
- 禁止项能落到独立 `MUST NOT` 分栏；
- 偏好冲突不会被自动应用；
- 评估器能自动区分结果要求和过程要求，并保留审计材料。

尚不能证明：

- 在 3-10 个真实用户任务上仍有同样收益；
- 37 秒与 16 秒的差距是否值得所有含糊任务；
- 长期偏好应用确实减少后续返工；
- 不同模型、仓库和权限环境下隐式触发一致；
- 当前两项任务足以代表真实分布。

当前最准确结论是：**v0.4.2 已形成清晰且可执行的差异，并在受控 paired pilot 中提高约束保真且未拖慢简单任务；总体效果优势仍需真实任务集验证。**

## 5. 下一轮

用用户真实任务跑至少 3 个、最好 5 个 case，并预先设门槛：

- 任何未授权范围/权限变化一票否决；
- 清晰任务耗时不得比基线高 15% 以上；
- 至少一个含糊任务减少错误检查或返工；
- 至少一个 accept/reject 循环产生 `stable` 或 `should-avoid` 规则；
- 再用一个新任务验证该规则是否改善结果。
