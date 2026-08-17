# 表格、副本与达人囤积协议

## 1. 资源与写入白名单

每批显式记录：

```text
brief_url / brief_revision
source_url / source_token / source_revision
target_sheet_id / creator_skill_sheet_id
copy_token / copy_revision
pool_token / pool_sheet_id / pool_revision
topic_column / status_column / homepage_column / creator_column
```

`templates/batch-manifest.json` 是 `DISCOVERED` 草稿骨架，不是完成审计的证明。只有填齐 live brief、源表与固定池 revision、sheet manifest、目标表和创作 Skill 表的精确表头映射、完整行覆盖、历史题键集合、创作 Skill 全表扫描和 pool 快照后，audit 才能进入 `PLAN_BUILT`。

每个表头映射使用以下形状，两个 sheet 分开记录：

```json
{"sheet_id":"creator-sheet","header":"是否合作","column":"D","match_count":1}
```

`match_count` 不等于 1、列坐标重复或 sheet_id 不匹配均不可写。

允许的云端写入只有：

1. 完整复制 spreadsheet 产生新副本；
2. `copy_token + target_sheet_id + topic_column`；
3. 配置中的固定 `pool_token + pool_sheet_id` 固定字段；
4. 本批“未通过明细”新文档。

源 token、源目标表、源创作 Skill 专项的 writeset 必须为空。

## 2. Wiki 解析与盘点

常用读路径：

```bash
lark-cli drive +inspect --url '<wiki-or-sheet-url>' --as user
lark-cli sheets +workbook-info --url '<wiki-or-sheet-url>' --as user
lark-cli sheets +revision-get --url '<wiki-or-sheet-url>' --as user
lark-cli sheets +csv-get --url '<url>' --sheet-id '<sheet_id>' --range '<full-current-region>' --as user
```

命令只是形状示意；执行前读取当前 lark Skill reference 和 `--help`。

`+csv-get` 的 `[row=N]` 是唯一可用于回写的行号来源；返回 `has_more`、截断、warning 或未知末行时继续读取，直到覆盖完整 current region。隐藏行默认也属于数据，不能因页面筛选而丢失。

每个源行建立指纹：

```text
platform + normalized_profile_key + creator_name + agency + raw_status + key_note + raw_homepage + source_row
```

名称重复时不能只用姓名定位。主页键重复时保留源行并进入异常处理。

## 3. 完整复制

只接受 Drive 原生 file copy，源类型必须是 `sheet`：

```bash
lark-cli schema drive.files.copy --format json
lark-cli drive files copy \
  --params '{"file_token":"<source_spreadsheet_token>"}' \
  --data '{"folder_token":"<resolved_folder_token>","name":"<copy_name>","type":"sheet"}' \
  --as user
```

- Wiki token 不能直接当 `file_token`，先 `drive +inspect` 取底层 token/type。
- 目标 folder token 必须解析，不得猜。优先保留源文件所在文件夹；无法取得时明确选择用户可写目标。
- 直接使用 API 返回的新 token，不按名称搜索副本。
- `source_revision_before_copy` 与 `source_revision_after_copy` 不同：副本视为过期，重新盘点并重新复制。
- 副本验证至少比较：token 不同、sheet 数量/顺序/标题/隐藏状态、目标表唯一存在、同日创作 Skill 表唯一存在、关键 used range 尺寸一致。

## 4. Revision 与行漂移

计划阶段、写前阶段、写后阶段分别记录 revision。

- 源表写前发生变化：重读决策相关列，按 `normalized_profile_key + creator_name` 重新映射；若插行、删行、工作表结构变化或副本不再对应，创建最新完整副本。
- 副本 revision 在计划后变化：放弃旧 writeset，重读并重建计划。
- 固定池在查重后变化：重读全池去重键与目标行，重新 upsert。
- API 没有 compare-and-swap 时，采用“revision 重验 → 尽快写 → 立即回读”；不得声称绝对无并发。
- 不复用旧 `[row=N]`，不按数组位置平移。

## 5. 待定精确筛选

对状态只做 Unicode NFKC 与边缘空白清理，随后严格比较：

```text
normalize(status) == "待定"
```

正例：`待定`、` 待定 `、全角空格包围的 `待定`。

反例：`暂定`、`待定中`、`暂待定`、`待定（跟进）`、`推进中`、空白、`否`、错误值。

扫描专项表全部当前有效行，不按“提报时间”过滤旧日期。pool 写前再次读取候选源行；如果状态已变化，取消该条同步并记状态漂移。

## 6. 主页去重键

优先稳定主页 URL：

- host 小写，移除 `www.` 等展示前缀；
- 去 scheme、query、fragment 和尾斜杠；
- 保留能唯一识别账号的 user/profile/author/space 路径与 ID；
- 加平台命名空间，避免跨平台碰撞；
- 原始主页链接永远另列保留。

作品页、视频页、笔记页、分享短链不是稳定主页键。无法解析时：

1. 有平台 + 达人名 + 机构名：生成 fallback key，可用于插入新记录和同批幂等；跨日期命中历史 fallback 时，只有同一来源记录或另有身份一致证据才能更新，否则记 `ANOMALY`；
2. 只有姓名：生成 ambiguous key，只记录异常，不自动与历史合并；
3. 同名不同主页保留两人；同主页改名更新最近信息，不追加。

脚本：

```bash
python3 scripts/workflow_guard.py normalize-profile \
  --url '<raw_url>' --platform '<platform>' --name '<creator>' --agency '<agency>'
```

## 7. 固定池 upsert

- 写前扫描全池主页去重键；已有重复键时停止自动 upsert，不“取第一条”。
- 新键：追加一行，写首次与最近字段。
- 已有稳定键：首次收录日期、首次来源工作表、首次源行号保持不变；更新最近同步日期、最近来源工作表、最近源行号、当前状态和最新可用信息。
- 已有 fallback 键：默认不跨日期自动合并；同一来源记录可做幂等 noop，其他情况先补主页或身份一致证据。
- 相同输入重跑应满足：新增 0、总行数不变；最新字段相同则无变化。
- proposal 与 pool 是两个独立事务；一个成功不能代表另一个成功。

每个创作 Skill 源行先生成 `source_snapshot`：达人、原始主页、平台、机构、原状态、source sheet/title/row/revision/URL、状态表头和列，再计算快照 SHA-256。`profile_key/key_kind/auto_merge/same_batch_dedupe` 必须由守门脚本从该快照重算并精确对账；`raw_status_prewrite`、`values.原是否合作`与快照原状态一致，`values.当前状态` 必须是规范化后的“待定”。

每个待定候选还需声明 `sync_action`、`target_row`、`expected_fingerprint`、完整 `values` 和 `changed_fields`。`insert/update` 的 changed_fields 必须与 pool writeset 逐字段一一对应；`noop/anomaly` 不得带任何 pool write。更新历史行时，首次收录日期、首次来源工作表、首次源行号不得出现在 changed_fields，且 before/after 值必须一致。fallback 跨日 update/noop 必须带可与源行和 pool 快照核对的同源证据，或带确认人、证据 URL 和说明的人工确认。

## 8. Fail-fast 批处理与逐格验收

逐地址生成 op，不把稀疏行压成大矩形。每个 op 至少记录：

```text
target, token, sheet_id, row, column, action, value, expected_fingerprint
```

- 标准流程只允许 `set` 非空值，不允许 `clear`；`null` 或空字符串也不得表示清空。若用户真的要清空，必须脱离本标准流程，单独确认精确坐标和恢复方案。
- 同一批不允许重复 cell address。
- 四段文本按 literal value 写入，避免被解析成公式。
- 本地 validator 只能证明 manifest 与 writeset 内部一致，不能代替 Feishu 的真实 dry-run、revision 重验与写后回读。执行器仍必须从守门后的同一 payload 文件/stdin 发起两次调用，不得人工重组。
- copy/pool 分别建 transaction；规范 envelope 必须同时包含 target、top-level spreadsheet token 和按 `sheet_id,row,column` 排序的完整 operations。对 envelope 做 UTF-8 canonical JSON SHA-256，避免“业务 body 一样，但顶层 token 指向源表”。
- 先调用 `+batch-update --dry-run` 检查顶层 token、sheet、范围和操作数；真写 receipt 的 token、payload hash 和 operation count 必须与 dry-run receipt 精确一致。
- 真写使用 fail-fast 模式，禁止 `--continue-on-error`；大 payload 通过 stdin 传入。不假设批次具有绝对原子性；客户端超时、断网或服务端错误后都先回读，再判断哪些坐标已生效。
- 用户说“跑/执行”视为对本协议白名单内写入的明确请求；若 CLI 仍返回 `confirmation_required`，按 `lark-shared` 展示精确目标和风险后处理，禁止静默加 `--yes`。

## 9. 回读与验收

副本每个 op 回读：行号、达人名、原合作状态、选题、机构备注/客户反馈。规范化换行与尾部空白后精确比对值；不能只判非空。

固定池每个 key 回读：达人名、原始主页、规范键、原状态、当前状态、首次/最近日期、首次/最近来源、源行号、源表链接；写后扫描全池唯一性。

验收等式：

```text
decision_total = submit + business_block + needs_evidence + retopic + anomaly
pending_detected = inserted + updated + noop_existing + rejected_anomaly
writes_planned = writes_succeeded + writes_failed + writes_skipped
```

写后重跑本地 validator；副本 diff 必须是计划 writeset 的子集。copy 阶段失败后，pool 所有计划坐标必须是 `skipped_due_to_prior_failure=true`，且回读验证未被改写；最终文档 action 必须是 `defer`。任何不闭合或回读不一致进入 `PARTIAL_NEEDS_REVIEW`，该状态 validator 会返回非成功，不能续写。

固定池写后不只检查 key 唯一；`postwrite_key_rows` 必须精确等于写前 `key→row` 加上已验证成功的 insert。

## 10. 未通过文档

创建文档前按 `lark-doc` 当前 reference 读取创建、XML、样式与创建工作流。创建后 `docs +fetch` 回读，不以 create 返回的 `ok` 代替内容验收。

报告只写本批最终未提交项，按四类分节；每条必须包含表格当前行号、达人、规范化主页键、原因代码、证据、修复条件和责任动作。若 revision 变化导致行号调整，文档使用最新行号并保留原行号到 manifest，不继续展示过期坐标。

创建前从决策行重算 `expected_rows`：`row_key=decision:row:profile_key`，`section=decision`，`content_sha256` 覆盖 creator/profile/decision/reason/evidence/fix/owner。回读后记录文档 token、revision、title_readback、`actual_rows` 和整文 hash；两组行键与 hash 必须全集一致。单独填 `readback_verified=true` 不构成证据。`audit` 模式只生成本地预览并对账 hash，不调用 `docs +create`。
