---
name: doubao-creator-topic-submission
description: "执行豆包达人选题的飞书提报全流程。当用户给出 brief 与飞书 Wiki/Sheets，或说‘跑今天的表’‘今天的表来了，开跑’‘按 brief 跑新表’‘达人选题提报’‘补提/复核未通过达人’‘同步创作 Skill 待定’‘达人囤积’时使用。负责读取实时 brief、定位日表、复制整本工作簿、调研与生成四段式 PC Skill 选题、只写副本并回读、把同日创作 Skill 中是否合作精确等于待定的达人同步到固定长期池，并生成未通过明细飞书文档。"
metadata:
  version: 1.1.0
  requires:
    bins: ["lark-cli"]
---

# 豆包达人选题提报工作流

本 Skill 是批次编排层，不替代 `doubao-task-mode-cases`。后者负责案例设计和 Skill 路由，本 Skill 负责把实时 brief、达人研究、飞书副本、长期“达人囤积”、并发保护、回读验收和未通过明细串成一次可复跑的交付。

## 适用边界

- 整批日表、补提复核、待定同步、逐行汇报：使用本 Skill。
- 只设计一个豆包案例、不涉及飞书批次：使用 `doubao-task-mode-cases`。
- 只做普通表格单元格编辑：使用 `lark-sheets`。
- 默认 `execute` 模式会创建完整副本，并只写副本、固定达人囤积表和本批未通过明细文档；用户明确说“只审不写”时使用 `audit` 模式，禁止复制、建文档、改表或任何其他云端写入，只生成本地预览。

## 开始前必读

按顺序读取，不得把这一步委派给子 Agent：

1. 本 Skill 的 [项目配置](references/project-config.md)、[决策门控](references/policy-gates.md)、[表格与囤积协议](references/sheet-and-pool-protocol.md)、[研究与选题规格](references/research-and-topic-spec.md)。
2. `lark-shared`、`lark-drive`、`lark-sheets`、`lark-doc` 的 `SKILL.md`。
3. 从可用 Skills 中定位 `doubao-task-mode-cases`，完整读取其 `SKILL.md`、`references/能力地图.md`、`references/客户选题反馈与经验沉淀.md`；涉及网页、应用或可视化时再读对应质量规范。
4. 真正调用某个 lark-cli 写命令前，按命令帮助中的要求，用 `lark-cli skills read ...` 读取版本匹配的 reference；禁止凭旧参数或本 Skill 的示意命令猜 payload。

## 规则优先级

从高到低：

1. 用户本轮最新明确要求；
2. 实时读取到的 brief；
3. 当前表格与历史记录里的合作状态、拉黑、已合作和客户反馈；
4. 本 Skill 的项目规则；
5. `doubao-task-mode-cases` 的历史经验与质量建议。

必须执行的最新口径：**只要符合实时 brief、没有保护性阻断，且题目不完全重复，就应提报。** 同行业、同人群、同一个 Skill 或同一能力大类本身不是淘汰理由；旧规则中“一个能力模式只保留一个案例”只用于提升创意质量，不得在日常达人提报中当一票否决。

以下安全不变量不能被静默放宽：源表只读、写前完整复制、按表头定位列、真实行号来自读取结果、`是否合作` 仅精确匹配“待定”、写前检查 revision、写后逐格回读。用户若明确要求改变这些安全边界，先说明风险并再次确认精确目标。

## 执行状态机

`DISCOVERED → SOURCE_SNAPSHOTTED → COPY_CREATED → COPY_VERIFIED → PLAN_BUILT → PREWRITE_REVALIDATED → COPY_WRITTEN_VERIFIED → POOL_SYNCED_VERIFIED → REPORT_VERIFIED → COMPLETE`

任一步出现版本漂移、部分写入或回读不一致，进入 `PARTIAL_NEEDS_REVIEW`。保留 manifest 和已成功坐标，停止后续写入；不得自动删数据、不得整批盲重跑。

## 标准执行流程

### 0. 建立批次

- 从用户输入或 [项目配置](references/project-config.md) 得到 `brief_url`、`source_url`、日期、目标工作表线索和固定池 URL。
- 默认日期使用 Asia/Shanghai 的当前日期。URL 的 `sheet=` 只是定位线索，不等于“今天创作 Skill 表”。
- 运行 `lark-cli auth status --json --verify`，以 `ok=true`、`verified` 和 user identity 判断登录态；只有认证确实失效或缺 scope 时才进入授权流程。
- 创建一份本地批次 manifest，使用 [batch-manifest.json](templates/batch-manifest.json)。初始状态是 `DISCOVERED` 草稿，不是审计结论；只有 brief、源表、表头、全行覆盖、历史题索引和 pool 快照齐全才可进入 `PLAN_BUILT`。令牌只记录资源 token，不记录 access token、Cookie 或密钥。

### 1. 读取 live brief

- 用 `lark-doc` 读取 brief 最新版本，记录标题、`revision_id`、受众、推广能力、时间窗、平台要求、最终产物标准和禁用表达。
- brief 每次都重新读取，不缓存活动内容。配置文件里保存的是链接，不是 brief 结论。
- 把用户本轮补充写入“本批覆盖项”；用户要求只影响明确范围，不得外推。

### 2. 只读盘点工作簿

- 用 `drive +inspect` 解包 Wiki，确认底层对象是 spreadsheet；用 `sheets +workbook-info` 读取工作表清单。
- 根据显式 sheet、日期、工作表标题和用户语义，唯一定位本批 PC 提报表与同日“创作 Skill 提报”表。候选为 0 或大于 1 时停止写入并消歧。
- 读取完整有效区域，按 Unicode trim 后的精确表头映射达人、主页、机构、合作状态、客户反馈和选题列；每个映射记录 `sheet_id + header + column + match_count=1`，目标表与创作 Skill 专项分开记录。匹配 0 个或多个都不得猜列。
- `[row=N]` 是真实行号，`col_indices` 是真实列映射。不得用数组下标、序号列或手数列号推导坐标。

### 3. 创建并验证完整副本

- 记录复制前源表 revision；使用 Drive 原生 spreadsheet copy 复制整个底层文件，不得用 CSV、导出导入或只复制当前 worksheet 代替。
- 直接使用 copy API 返回的新 token；记录复制后源表 revision。两次 revision 不同则重新盘点并重新复制。
- 比较源/副本 token、工作表数量、顺序、标题、隐藏状态和关键 used range；目标 PC 表与同日创作 Skill 表必须在副本中唯一存在。
- 后续提报写操作白名单只有：`copy_token + target_sheet_id + topic_column`。源 token 的 writeset 必须永远为空。

### 4. 同步长期“达人囤积”

- 从源工作簿的同日创作 Skill 专项读取所有有效行；只把 Unicode trim 后**严格等于 `待定`**的状态选中。`暂定`、`待定中`、`待定（跟进）`、空白、`否` 均不命中。
- 每个专项行先记录不可省略的源行快照：达人、原始主页、平台、机构、原状态、sheet/row/revision/source URL 以及“是否合作”的表头和列坐标。用 `scripts/workflow_guard.py normalize-profile` 从这份快照重算主页去重键；保留原始主页，禁止手填任意 key。
- 短链、作品链接或只有姓名的模糊键不得自动合并。姓名 + 机构备用键可用于新记录和同批幂等，但跨日期 update/noop 必须带结构化同源证据或人工身份确认，不接受一个自由布尔值代替证据。
- 固定池是跨日期单表：已存在则更新最近来源与最新信息，不覆盖首次来源；不存在才追加；源专项永不回写。
- 囤积表单独做 revision 检查、dry-run、fail-fast 批处理和逐格回读；它与提报是否通过互相独立。

### 5. 保护预筛与历史索引

- 先处理当前/历史明确 `否`、拉黑、已合作、硬禁行业、明确权限禁用和同批重复主页。
- 历史题相同不等于达人永久失效：先尝试换一个符合 brief、核心任务或最终产物不同的题；只有业务状态阻断才归为保护性拒绝。
- 为每一源行建立行指纹：平台、主页去重键、达人名、机构、当前状态、关键备注、原始主页和源行号。写前必须重验。
- 全量读取可访问历史题，结构化成 `core_task + key_input + final_artifact + lifecycle` 键集合并标记快照完整；不得只查当前页面或只搜标题文字。

### 6. 调研达人和真实需求

- 在已登录的平台主页核验身份、真人证据、近期内容、粉丝需求和自然 PC 场景；验证码、游客残缺或链接失效时，不得用搜索摘要伪造结论。
- 对候选方向查近期优质案例与真实痛点；研究深度和记录字段见 [研究与选题规格](references/research-and-topic-spec.md)。
- 先理解达人，再选 Skill；不能先想功能再套人设。

### 7. 决策并迭代题目

逐行只能取以下状态之一：

- `SUBMIT`：符合 brief、无保护阻断、不是完全重复。
- `BUSINESS_BLOCK`：明确否、拉黑、已合作、硬禁或明确不可用。
- `NEEDS_EVIDENCE`：身份、真人、主页、权限或登录证据暂时不足。
- `RETOPIC`：当前题不符合 brief、非 PC、时间窗/数据不可行或与历史题完全重复，但达人仍可换题。
- `ANOMALY`：表格结构、重复键、版本漂移或工具异常，必须人工复核。

每行 manifest 必须记录：当前行号、达人、主页去重键、行指纹、决定、枚举原因代码、brief_fit、protection_block、历史匹配、证据、修复条件和责任动作。`BUSINESS_BLOCK` 必须带业务阻断证据，`NEEDS_EVIDENCE` 必须带缺口/所需证据/下一步，`RETOPIC` 必须带改核心任务或最终产物的尝试，`ANOMALY` 必须带观察和处理动作。任意自由 reason code 不得通过守门。

`SUBMIT` 另带 PC 命中、主 Skill、核心任务、关键输入、最终产物、生命周期、查重键和四段式。同批 `SUBMIT` 的查重键不得重复，也不得命中历史完全重复键。

对没有业务阻断的达人，首个想法失败后应继续换核心任务或最终产物；不得因为“和别人用了同一个 Skill”直接留空。生成完整逐行决策表，并验证 `决策总数 = 数据行总数`。

### 8. 写四段式

每条选题严格四行，标签和顺序不得变化：

```text
身份：
功能：
痛点 / 场景：
具体实现与步骤：
```

每行尽量一句。内容只保留“真实身份 + Skill、简单痛点 + 豆包做什么 + 最终产物”，不要把研究过程和长背景塞进单元格。写前运行 `scripts/workflow_guard.py validate-topic`。

### 9. 写前重验与 fail-fast 批处理

- 在真正写入前重新获取源、副本、固定池 revision，并重读所有待写行的姓名、主页、状态、备注和目标单元格。
- 源表 revision 变化：按主页键 + 达人名重新映射；行结构变化或副本已过期时，创建最新完整副本，禁止复用旧行号。
- 副本或固定池 revision 与计划不一致：重读、重算，不得强写。
- 用 manifest 生成逐地址 writeset；禁止把稀疏行压成一个大矩形，禁止用空字符串暗示清空。
- 按 copy/pool 分两个 transaction，守门脚本从 writeset 生成规范化 envelope，把 **top-level spreadsheet token + 全部 operations** 一起算 SHA-256。顶层 token 只能分别是 copy token 或固定 pool token，永远不能是 source token。
- 先 dry-run，再用与 dry-run **完全相同的 token、operation count 和 payload hash** 调用 `sheets +batch-update`；两次 receipt 都写入 manifest。大 JSON 通过 stdin，禁止 `--continue-on-error`。
- 这只是 fail-fast 批处理，不声称网络与服务端具有绝对原子性。copy 阶段失败时 pool 阶段全部标记 skipped 并验证未改；任一失败或跳过均延后最终文档、保留成功坐标并进入 `PARTIAL_NEEDS_REVIEW`。该状态 validator 必须返回 `ok=false` 且 `safe_to_execute=false`，不得作为续写通行证。高风险确认遵循 `lark-shared`。

### 10. 回读与对账

- 每个写入单元格回读达人名、合作状态、选题、机构备注/反馈，并对选题文本做规范化后精确比对，不只检查“非空”。
- 跳过行确认未变；副本 changeset/diff 只能包含计划中的选题单元格。
- 固定池回读去重键、名称、原状态、当前状态、首次/最近日期、来源表、源行和源表链接；全池去重键必须唯一。
- 固定池写后的 `key → row` 全集必须精确等于“写前历史集 + 已验证成功的 insert”，不接受只回读一个无关且唯一的 key 作为成功证明。
- 对账：`decision_total = submit + business_block + needs_evidence + retopic + anomaly`；`pending_detected = inserted + updated + noop + rejected_anomaly`。

### 11. 创建“未通过明细”飞书文档

- 按 [rejection-report.md](templates/rejection-report.md) 生成内容；先读 `lark-doc` 当前版本的创建、XML、样式和创建工作流 reference，再创建文档。
- `execute` 模式才创建云端文档；`audit` 模式只按同一模板生成本地预览，云端 writeset 必须为 0。
- 文档分开写 `BUSINESS_BLOCK`、`NEEDS_EVIDENCE`、`RETOPIC`、`ANOMALY`；每条都带当前行、达人、主页键、原因代码、证据、修复条件和责任动作，不要把可补证/可换题的人写成“达人不行”。
- 任何实际应为 `SUBMIT` 却未写入的行属于 false negative：先修复副本再生成最终文档。
- 创建前从最终非 `SUBMIT` 行生成 `expected_rows`，每行键为 `decision:row:profile_key`，并对达人、决定、reason、证据、修复条件和责任动作计算内容 hash。创建后用 `docs +fetch` 回读 revision、标题、逐行 hash 和整文 hash；`actual_rows` 必须与 `expected_rows` 全集一致，不接受单个 `readback_verified=true` 代替证据。

### 12. 最终交付

最终回复必须包含：

- brief 标题与本次读取 revision；
- 原表链接、执行副本链接、目标工作表；
- 提报写入/未写/异常数量及实际修改范围；
- 固定达人囤积链接和新增/更新/无变化/异常数量；
- 未通过明细飞书文档链接；
- 回读结论和仍需用户处理的阻塞。

不得只说“已完成”。交付前用 [execution-report.md](templates/execution-report.md) 的检查表逐项验收。

## 离线保护工具

下列相对路径均以本 `SKILL.md` 所在目录为根；调用前先解析 Skill 实际安装目录，或把工作目录切到该目录，不要假设用户项目根就是 Skill 根。

```bash
python3 scripts/workflow_guard.py is-pending --value ' 待定 '
python3 scripts/workflow_guard.py normalize-profile --url 'https://www.douyin.com/user/ABC?share=1' --platform 抖音
python3 scripts/workflow_guard.py validate-topic --file ./topic.txt
python3 scripts/workflow_guard.py derive-plan-evidence --file ./batch-manifest.json
python3 scripts/workflow_guard.py validate-manifest --file ./batch-manifest.json
python3 scripts/workflow_guard.py hash-text --file ./report-readback.txt
python3 -m unittest discover -s tests -v
```

`derive-plan-evidence` 只输出源行指纹、transaction token/count/hash 和报告 expected rows；其 `dry_run/execute` 保留为 null，必须在真实调用后用 receipt 填入，不得伪造成功。脚本只做确定性清洗与校验，不访问网络、不复制表格、不执行飞书写入。云端写操作始终通过对应 lark Skill 明确执行并回读。
