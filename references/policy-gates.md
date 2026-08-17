# 决策门控

## 一句话原则

没有业务保护阻断时，只要能写出符合 live brief、PC 场景成立且不完全重复的题，就应提报。相似不是重复；第一版题不成立时先换题，不先淘汰达人。

## 判定顺序

### 1. `BUSINESS_BLOCK`：保护性阻断

命中任一项，本批不写：

- 当前表明确 `是否合作=否`；
- 同一规范化主页在历史记录中明确为否、拉黑或已合作，且没有用户本轮明确解除；
- 同批出现相同稳定主页，已确定另一行是有效主记录；重复行只保留一条并记录来源；
- 命中用户在本项目中已确认的长期硬禁行业：装修、房产、母婴、AI 营销；本轮用户若明确解除某一类，以最新说明为准，不能从其他 brief 静默推断解除；
- live brief 或用户本轮明确禁止的达人类型、行业、能力、平台或权限；
- 需要未开放/未授权能力，且没有可替代 Skill 路径。

不得只凭昵称、机构宽泛标签或旧推测生成 `BUSINESS_BLOCK`。

### 2. `NEEDS_EVIDENCE`：证据或条件不足

暂时不写，但不是业务拒绝：

- 主页链接失效、跳到作品页/短链且无法解析稳定主页；
- 只凭昵称推断“老师/学生/医生/程序员”，缺少主页简介或本人作品证据；
- 非游客完整内容不可见、验证码/风控拦截、登录状态无效；
- 真人出镜、任教学科、职业或 Skill 权限是 brief 必需条件，但尚未核实；
- 历史记录冲突，无法判断是同一达人或不同账号。

记录“已确认事实、缺失证据、补齐条件、证据链接”，不能写空泛的“信息不足”。

### 3. `RETOPIC`：当前题不成立，可换题

达人本身没有业务阻断，但当前想法命中：

- 不符合 live brief 的目标人群、能力或最终产物；
- 手机单次对话即可完成，PC-1/2/3 只命中 0–1 项；
- 只是输出一段文字，没有文件、多步执行、网页/应用、稳定工作流或 Office 组合产物；
- 数据不可得、时间窗已过、Skill 生命周期或能力边界选错；
- 与历史题“核心任务 + 输入动作 + 最终产物/生命周期”完全相同。

进入 `RETOPIC` 后，至少尝试改变核心任务或最终产物；如果找到合格新题，应转为 `SUBMIT`，不能继续留在未通过表。

### 4. `SUBMIT`：应提报

同时满足：

- 真实身份与达人内容方向有可追溯证据；
- 符合 live brief 与用户本轮说明；
- 没有 `BUSINESS_BLOCK`；
- PC 场景至少命中 PC-1/2/3 中两项；
- Skill 路由和产物生命周期成立；
- 与历史题不完全重复；
- 四段式完整、简洁、可执行。

## 完全重复如何判

判断基于语义任务，不只看标题字面：

```text
duplicate_key = 核心任务 + 关键输入 + 最终产物 + 使用生命周期
```

- 四项核心语义都相同，即使换了标题、行业例子、同义词或主 Skill，仍是完全重复。
- 主 Skill 相同但核心任务或最终产物明显不同，不是完全重复。
- 同行业、同人群、同能力大类、同“可视化/应用生成”标签，单独任何一项都不能判重复。
- 历史题完全重复时优先换任务或产物；不是把达人永久封禁。

主 Skill 作为路由依据单独记录，但不参与“是否完全重复”的键。离线脚本的 `topic-key` 只比较人工已经结构化的字段，不替代语义判断。

## 旧经验如何使用

`doubao-task-mode-cases` 和客户反馈沉淀仍用于：PC 反查、Skill 路由、生命周期、真实痛点、行业风险、表达质量和创意优化。

下列旧经验不得自动升级为拒绝：

- “同一能力模式只留一个最典型案例”；
- “同一个 Skill 已经提过，所以别的达人不能再提”；
- “这个方向比较常见/没那么新”；
- “第一版题不够强”。

它们只触发改题和质量提升。最终门槛是 live brief + 保护状态 + 不完全重复。

## 未通过文档的四类

| 类别 | 对外含义 | 是否可在本批修复 |
| --- | --- | --- |
| BUSINESS_BLOCK | 业务状态或硬规则阻断 | 通常否；需用户明确解除 |
| NEEDS_EVIDENCE | 证据/登录/权限暂缺 | 是，补证后复核 |
| RETOPIC | 当前题不成立 | 是，换核心任务/产物 |
| ANOMALY | 表格、版本或工具异常 | 是，修复技术问题后重试 |

生成最终文档前再审一次：凡已满足 `SUBMIT` 却仍未写入的条目属于 false negative，先修表，不把它包装成未通过原因。

## 枚举原因代码

不接受自由文本 reason code，避免把“同 Skill”、“题不够新”伪装成拒绝。必须使用下列之一，并填齐对应结构化证据：

| 决策 | 允许的 reason code |
| --- | --- |
| SUBMIT | `BRIEF_FIT_UNIQUE_TOPIC` |
| BUSINESS_BLOCK | `CURRENT_STATUS_NO`, `HISTORICAL_STATUS_NO`, `BLACKLISTED`, `ALREADY_COOPERATED`, `DUPLICATE_PROFILE_SAME_BATCH`, `HARD_INDUSTRY_BLOCK`, `LIVE_BRIEF_EXCLUSION`, `CAPABILITY_UNAVAILABLE`, `USER_CONFIRMED_BLOCK` |
| NEEDS_EVIDENCE | `PROFILE_UNAVAILABLE`, `IDENTITY_EVIDENCE_MISSING`, `HUMAN_APPEARANCE_UNVERIFIED`, `LOGIN_OR_RISK_CONTROL_BLOCKED`, `SKILL_PERMISSION_UNVERIFIED`, `HISTORY_IDENTITY_CONFLICT` |
| RETOPIC | `BRIEF_MISMATCH`, `PC_FIT_INSUFFICIENT`, `FINAL_ARTIFACT_INSUFFICIENT`, `DATA_UNAVAILABLE`, `TIME_WINDOW_INVALID`, `CAPABILITY_LIFECYCLE_MISMATCH`, `EXACT_TOPIC_DUPLICATE`, `RETOPIC_ATTEMPTS_EXHAUSTED` |
| ANOMALY | `SHEET_STRUCTURE_ANOMALY`, `DUPLICATE_POOL_KEY`, `REVISION_DRIFT`, `TOOL_FAILURE`, `IDENTITY_KEY_AMBIGUOUS` |

新出现的真实业务原因若不在枚举中，先更新本 Skill 和测试，不用 `OTHER` 绕过。
