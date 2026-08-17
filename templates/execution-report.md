# [批次] 执行与回读报告

## 结果

- Brief：
- Brief revision：
- 原表：
- 执行副本：
- 目标工作表：
- 数据行：
- SUBMIT：
- BUSINESS_BLOCK：
- NEEDS_EVIDENCE：
- RETOPIC：
- ANOMALY：
- 实际修改范围：
- writes planned / succeeded / failed / skipped：
- 未通过明细文档：

## 达人囤积同步

- 固定表：
- 专项工作表：
- 精确待定：
- 新增：
- 更新：
- 无变化：
- 异常：

## Revision 与写入证据

- source revision（读取/复制前/写前/结束）：
- copy revision（创建/计划/写前/写后）：
- pool revision（读取/写前/写后）：
- 副本 manifest 证据（sheet 数/顺序/标题/隐藏/范围 hash）：
- copy transaction（top-level token / payload hash / dry-run / execute receipt）：
- pool transaction（top-level token / payload hash / dry-run / execute receipt）：
- source writeset：0
- copy readback：
- pool readback：
- pool postwrite key→row 全集：
- 未通过文档 readback（token/revision/title/row hashes/document hash）：

## 逐行决策

| 行 | 达人 | 主页去重键 | 决策 | 主 Skill | PC-1/2/3 | 题目/原因 | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |  |  |

## 强制验收

```text
[ ] live brief 已读取并记录 revision
[ ] 源表与副本 token 不同
[ ] 副本是整本原生复制，manifest 一致
[ ] 源表 writeset 为 0
[ ] 目标表与同日创作 Skill 表唯一定位
[ ] 表头精确映射，数据全量读取
[ ] 表头映射带 sheet_id/header/column/match_count=1
[ ] 每个源行均有且仅有一个最终决策
[ ] 同 Skill/同行业没有被当作自动重复
[ ] 所有 SUBMIT 均为固定四段式且已回读
[ ] 待定只做精确匹配
[ ] pool 候选已绑定源行快照、状态表头与 normalize-profile 结果
[ ] 固定池首次字段未被覆盖、去重键唯一
[ ] revision 漂移已重读重映射
[ ] 三组计数等式闭合
[ ] dry-run 与 execute 使用完全相同的 payload
[ ] transaction top-level token 不是 source token，且 token/count/hash receipt 闭合
[ ] 失败/超时后已先回读，没有盲目整批重跑
[ ] 未通过文档已创建并回读
[ ] 未通过 expected/actual 行键、行 hash 和整文 hash 全集一致
[ ] “应提报但尚未写入”为 0
```
