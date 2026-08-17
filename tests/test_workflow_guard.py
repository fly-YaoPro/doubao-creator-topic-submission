from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import workflow_guard as guard  # noqa: E402


VALID_TOPIC = """身份：跨境电商 Listing 优化博主
功能：浏览器任务 Skill + 文档 Skill
痛点 / 场景：每次上新都要在多个竞品页面和表格间核对关键词、卖点和合规表述，版本一多就容易漏改。
具体实现与步骤：录入产品资料后由豆包对照竞品页面，生成带关键词依据、风险标记和可直接复核的 Listing 文档。"""


def sheet_entry(sheet_id: str, title: str, position: int, used_range: str) -> dict:
    return {
        "sheet_id": sheet_id,
        "title": title,
        "position": position,
        "hidden": False,
        "row_count": 100,
        "column_count": 23,
        "used_range": used_range,
        "used_range_hash": f"hash:{title}:{used_range}",
    }


def header_entry(sheet_id: str, header: str, column: str) -> dict:
    return {
        "sheet_id": sheet_id,
        "header": header,
        "column": column,
        "match_count": 1,
    }


def pool_field_columns() -> dict[str, str]:
    return {field: chr(ord("A") + index) for index, field in enumerate(guard.POOL_FIELDS)}


def new_pool_values(profile_key: str) -> dict[str, str]:
    values = {field: "" for field in guard.POOL_FIELDS}
    values.update(
        {
            "达人名称": "达人甲",
            "主页链接": "https://douyin.com/user/abc?share=1",
            "主页去重键": profile_key,
            "平台": "抖音",
            "机构名": "机构乙",
            "原是否合作": "待定",
            "当前状态": "待定",
            "首次收录日期": "2026-08-05",
            "最近同步日期": "2026-08-05",
            "首次来源工作表": "8.5创作Skill提报",
            "最近来源工作表": "8.5创作Skill提报",
            "首次源行号": "5",
            "最近源行号": "5",
            "提报时间": "2026-08-05",
            "原选题": "原始创作题",
            "源表链接": "https://example.feishu.cn/wiki/source?sheet=creator-source",
        }
    )
    return values


def refresh_transactions(manifest: dict, *, postwrite: bool = False) -> None:
    transactions = {}
    token_by_target = {
        "copy": manifest.get("copy", {}).get("token", ""),
        "pool": manifest.get("pool", {}).get("token", ""),
    }
    for target in ("copy", "pool"):
        target_writes = [write for write in manifest.get("writes", []) if write["target"] == target]
        if not target_writes:
            continue
        token = token_by_target[target]
        payload_hash = guard._sha256(guard._transaction_envelope(target, token, target_writes))
        receipt = {
            "ok": True,
            "attempted": True,
            "top_level_token": token,
            "payload_sha256": payload_hash,
            "operation_count": len(target_writes),
        }
        transactions[target] = {
            "top_level_token": token,
            "payload_sha256": payload_hash,
            "operation_count": len(target_writes),
            "dry_run": {
                key: value for key, value in receipt.items() if key != "attempted"
            },
            "execute": copy.deepcopy(receipt) if postwrite else None,
        }
    manifest["transactions"] = transactions


def valid_manifest() -> dict:
    profile_key = "douyin:douyin.com/user/abc"
    source_url = "https://example.feishu.cn/wiki/source?sheet=creator-source"
    mapping = pool_field_columns()
    values = new_pool_values(profile_key)
    changed_fields = [field for field, value in values.items() if guard.normalize_text(value)]
    pool_writes = [
        {
            "target": "pool",
            "token": "pool-token",
            "sheet_id": "pool-sheet",
            "row": 3,
            "column": mapping[field],
            "logical_field": field,
            "candidate_key": profile_key,
            "action": "set",
            "value": values[field],
            "expected_fingerprint": "EMPTY_ROW:3",
        }
        for field in changed_fields
    ]
    source_manifest = [
        sheet_entry("target-source", "8.5抖音办公任务pc提报", 0, "A1:W60"),
        sheet_entry("creator-source", "8.5创作Skill提报", 1, "A1:O20"),
    ]
    copy_manifest = [
        sheet_entry("target-copy", "8.5抖音办公任务pc提报", 0, "A1:W60"),
        sheet_entry("creator-copy", "8.5创作Skill提报", 1, "A1:O20"),
    ]
    duplicate_key = guard.topic_key(
        "浏览器任务 Skill + 文档 Skill",
        "核对竞品并优化 Listing",
        "产品资料和竞品页面",
        "带依据与风险标记的 Listing 文档",
        "单次交付",
    )
    writes = [
        {
            "target": "copy",
            "token": "copy-token",
            "sheet_id": "target-copy",
            "row": 2,
            "column": "L",
            "action": "set",
            "value": VALID_TOPIC,
            "expected_fingerprint": "fp-row-2",
            "prewrite_value_hash": "hash:empty-cell",
        }
    ] + pool_writes
    source_snapshot = {
        "creator": "达人甲",
        "raw_homepage": "https://douyin.com/user/abc?share=1",
        "platform": "抖音",
        "agency": "机构乙",
        "raw_status": "待定",
        "source_sheet_id": "creator-source",
        "source_sheet_title": "8.5创作Skill提报",
        "source_row": 5,
        "source_revision": 10,
        "source_url": source_url,
        "status_header": "是否合作",
        "status_column": "D",
    }
    manifest = {
        "schema_version": "1.1",
        "mode": "execute",
        "stage": "prewrite",
        "state": "PREWRITE_REVALIDATED",
        "batch": {
            "date": "2026-08-05",
            "timezone": "Asia/Shanghai",
            "user_overrides": [],
        },
        "brief": {
            "url": "https://example.feishu.cn/wiki/brief",
            "title": "测试 brief",
            "revision": 71,
        },
        "source": {
            "url": source_url,
            "token": "source-token",
            "object_type": "sheet",
            "initial_revision": 10,
            "revision_read": 10,
            "revision_before_copy": 10,
            "revision_after_copy": 10,
            "revision_prewrite": 10,
            "replan_generation": 0,
            "old_copy_invalidated": False,
            "remap_evidence": [],
            "target_sheet_id": "target-source",
            "creator_skill_sheet_id": "creator-source",
            "expected_source_rows": [2],
            "creator_skill_expected_rows": [5],
            "creator_skill_scan_complete": True,
            "sheet_manifest": source_manifest,
            "writes": [],
        },
        "copy": {
            "token": "copy-token",
            "source_token": "source-token",
            "source_revision": 10,
            "api_returned_token": "copy-token",
            "object_type": "sheet",
            "manifest_verified": True,
            "sheet_manifest": copy_manifest,
            "revision_planned": 3,
            "revision_prewrite": 3,
            "revision_postwrite": None,
            "target_sheet_id": "target-copy",
            "creator_skill_sheet_id": "creator-copy",
            "topic_column": "L",
        },
        "pool": {
            "url": "https://example.feishu.cn/sheets/pool?sheet=pool-sheet",
            "token": "pool-token",
            "sheet_id": "pool-sheet",
            "revision_planned": 8,
            "revision_prewrite": 8,
            "revision_postwrite": None,
            "allowed_columns": list(mapping.values()),
            "field_columns": mapping,
            "snapshot_complete": True,
            "snapshot_rows": [
                {
                    "row": 2,
                    "profile_key": "douyin:douyin.com/user/old",
                    "fingerprint": "pool-old-fp",
                    "first_seen": {
                        "首次收录日期": "2026-07-27",
                        "首次来源工作表": "7.27创作Skill提报",
                        "首次源行号": "2",
                    },
                }
            ],
            "existing_keys": ["douyin:douyin.com/user/old"],
            "postwrite_keys": [],
            "postwrite_key_rows": {},
        },
        "headers": {
            "target": {
                "creator": header_entry("target-source", "达人名称", "A"),
                "homepage": header_entry("target-source", "主页链接", "B"),
                "agency": header_entry("target-source", "机构名", "C"),
                "status": header_entry("target-source", "是否合作", "D"),
                "topic": header_entry("target-source", "选题", "L"),
                "feedback": header_entry("target-source", "客户反馈", "M"),
            },
            "creator_skill": {
                "creator": header_entry("creator-source", "达人名称", "A"),
                "homepage": header_entry("creator-source", "主页链接", "B"),
                "agency": header_entry("creator-source", "机构名", "C"),
                "status": header_entry("creator-source", "是否合作", "D"),
            },
        },
        "history": {
            "snapshot_complete": True,
            "sources": [
                {
                    "url": source_url,
                    "revision": 10,
                    "rows_scanned": 1,
                    "content_sha256": guard._sha256({"history_rows": []}),
                }
            ],
            "duplicate_keys": [],
        },
        "rows": [
            {
                "row": 2,
                "creator": "达人甲",
                "profile_key": profile_key,
                "fingerprint": "fp-row-2",
                "decision": "SUBMIT",
                "reason_code": "BRIEF_FIT_UNIQUE_TOPIC",
                "brief_fit": True,
                "protection_block": False,
                "historical_match": {
                    "status": "none",
                    "matched_duplicate_keys": [],
                    "evidence": [],
                },
                "evidence": ["https://douyin.com/user/abc"],
                "fix_condition": "已满足",
                "owner_action": "agent_write_copy",
                "pc_hits": ["PC-1", "PC-2", "PC-3"],
                "main_skill": "浏览器任务 Skill + 文档 Skill",
                "core_task": "核对竞品并优化 Listing",
                "key_input": "产品资料和竞品页面",
                "final_artifact": "带依据与风险标记的 Listing 文档",
                "lifecycle": "单次交付",
                "duplicate_key": duplicate_key,
                "topic": VALID_TOPIC,
            }
        ],
        "pool_candidates": [
            {
                "source_row": 5,
                "raw_status": "　待定 ",
                "raw_status_prewrite": "待定",
                "selected": True,
                "profile_key": profile_key,
                "key_kind": "profile_url",
                "auto_merge": True,
                "same_batch_dedupe": True,
                "source_snapshot": source_snapshot,
                "source_fingerprint": guard._source_snapshot_fingerprint(source_snapshot),
                "sync_action": "insert",
                "target_row": 3,
                "expected_fingerprint": "EMPTY_ROW:3",
                "values": values,
                "changed_fields": changed_fields,
                "identity_evidence": [],
            }
        ],
        "writes": writes,
        "counts": {
            "decision_total": 1,
            "submit": 1,
            "business_block": 0,
            "needs_evidence": 0,
            "retopic": 0,
            "anomaly": 0,
            "pending_detected": 1,
            "inserted": 1,
            "updated": 0,
            "noop_existing": 0,
            "rejected_anomaly": 0,
            "writes_planned": len(writes),
            "writes_succeeded": 0,
            "writes_failed": 0,
            "writes_skipped": 0,
        },
        "report": {
            "action": "create",
            "title": "2026-08-05-测试批次-未通过明细",
            "title_readback": "",
            "token": "",
            "revision_postcreate": None,
            "expected_rows": [],
            "actual_rows": [],
            "expected_document_sha256": guard._sha256({"report": "empty-test-report"}),
            "actual_document_sha256": "",
            "preview_verified": False,
            "readback_verified": False,
        },
        "readback": {"copy_addresses": [], "pool_addresses": []},
    }
    refresh_transactions(manifest)
    return manifest


def update_pool_candidate(manifest: dict) -> None:
    """Convert the valid insert candidate to a valid update of the snapshot row."""

    candidate = manifest["pool_candidates"][0]
    old_key = "douyin:douyin.com/user/old"
    values = new_pool_values(old_key)
    values.update(
        {
            "达人名称": "旧达人新昵称",
            "主页链接": "https://douyin.com/user/old",
            "首次收录日期": "2026-07-27",
            "首次来源工作表": "7.27创作Skill提报",
            "首次源行号": "2",
            "最近同步日期": "2026-08-05",
            "最近来源工作表": "8.5创作Skill提报",
            "最近源行号": "5",
        }
    )
    changed_fields = ["达人名称", "最近同步日期", "最近来源工作表", "最近源行号"]
    source_snapshot = copy.deepcopy(candidate["source_snapshot"])
    source_snapshot.update(
        {
            "creator": "旧达人新昵称",
            "raw_homepage": "https://douyin.com/user/old",
        }
    )
    candidate.update(
        {
            "profile_key": old_key,
            "source_snapshot": source_snapshot,
            "source_fingerprint": guard._source_snapshot_fingerprint(source_snapshot),
            "sync_action": "update",
            "target_row": 2,
            "expected_fingerprint": "pool-old-fp",
            "values": values,
            "changed_fields": changed_fields,
            "existing_values": {
                "首次收录日期": "2026-07-27",
                "首次来源工作表": "7.27创作Skill提报",
                "首次源行号": "2",
            },
        }
    )
    copy_write = manifest["writes"][0]
    mapping = manifest["pool"]["field_columns"]
    manifest["writes"] = [copy_write] + [
        {
            "target": "pool",
            "token": "pool-token",
            "sheet_id": "pool-sheet",
            "row": 2,
            "column": mapping[field],
            "logical_field": field,
            "candidate_key": old_key,
            "action": "set",
            "value": values[field],
            "expected_fingerprint": "pool-old-fp",
        }
        for field in changed_fields
    ]
    manifest["counts"].update(
        {
            "inserted": 0,
            "updated": 1,
            "writes_planned": len(manifest["writes"]),
        }
    )
    refresh_transactions(manifest)


def valid_postwrite_manifest() -> dict:
    """Return a fully reconciled execute manifest after successful writes."""

    manifest = valid_manifest()
    manifest["stage"] = "postwrite"
    manifest["state"] = "COMPLETE"
    manifest["copy"]["revision_postwrite"] = 4
    manifest["pool"]["revision_postwrite"] = 9
    manifest["pool"]["postwrite_keys"] = [
        "douyin:douyin.com/user/old",
        "douyin:douyin.com/user/abc",
    ]
    manifest["pool"]["postwrite_key_rows"] = {
        "douyin:douyin.com/user/old": 2,
        "douyin:douyin.com/user/abc": 3,
    }
    for write in manifest["writes"]:
        write["succeeded"] = True
        write["readback_matches"] = True
        write["skipped_due_to_prior_failure"] = False
    manifest["counts"]["writes_succeeded"] = len(manifest["writes"])
    manifest["readback"]["copy_addresses"] = sorted(
        guard._write_address(write)
        for write in manifest["writes"]
        if write["target"] == "copy"
    )
    manifest["readback"]["pool_addresses"] = sorted(
        guard._write_address(write)
        for write in manifest["writes"]
        if write["target"] == "pool"
    )
    manifest["report"] = {
        "action": "create",
        "title": "2026-08-05-测试批次-未通过明细",
        "title_readback": "2026-08-05-测试批次-未通过明细",
        "token": "rejection-report-token",
        "revision_postcreate": 2,
        "expected_rows": [],
        "actual_rows": [],
        "expected_document_sha256": guard._sha256({"report": "empty-test-report"}),
        "actual_document_sha256": guard._sha256({"report": "empty-test-report"}),
        "preview_verified": False,
        "readback_verified": True,
    }
    refresh_transactions(manifest, postwrite=True)
    return manifest


def valid_audit_manifest() -> dict:
    manifest = valid_manifest()
    manifest["mode"] = "audit"
    manifest["stage"] = "plan"
    manifest["state"] = "PLAN_BUILT"
    manifest["copy"] = {
        "token": "",
        "source_token": "",
        "source_revision": None,
        "api_returned_token": "",
        "object_type": "",
        "manifest_verified": False,
        "sheet_manifest": [],
        "revision_planned": None,
        "revision_prewrite": None,
        "revision_postwrite": None,
        "target_sheet_id": "",
        "creator_skill_sheet_id": "",
        "topic_column": "",
    }
    manifest["writes"] = []
    manifest["transactions"] = {}
    manifest["counts"].update(
        {
            "writes_planned": 0,
            "writes_succeeded": 0,
            "writes_failed": 0,
            "writes_skipped": 0,
        }
    )
    document_hash = manifest["report"]["expected_document_sha256"]
    manifest["report"].update(
        {
            "action": "preview",
            "actual_rows": [],
            "actual_document_sha256": document_hash,
            "preview_verified": True,
            "readback_verified": False,
        }
    )
    return manifest


def valid_non_submit_manifest() -> dict:
    manifest = valid_manifest()
    row = manifest["rows"][0]
    row.update(
        {
            "decision": "NEEDS_EVIDENCE",
            "reason_code": "IDENTITY_EVIDENCE_MISSING",
            "brief_fit": True,
            "protection_block": False,
            "evidence_gap": {
                "missing": "教师身份一手证据",
                "needed": "主页简介或本人作品",
                "next_action": "补充可访问的主页证据后复核",
            },
            "fix_condition": "补齐教师身份一手证据",
            "owner_action": "request_identity_evidence",
        }
    )
    manifest["writes"] = [
        write for write in manifest["writes"] if write["target"] == "pool"
    ]
    manifest["counts"].update(
        {
            "submit": 0,
            "needs_evidence": 1,
            "writes_planned": len(manifest["writes"]),
        }
    )
    expected_rows = [guard._report_row(row)]
    manifest["report"]["expected_rows"] = expected_rows
    manifest["report"]["expected_document_sha256"] = guard._sha256(
        {"title": manifest["report"]["title"], "rows": expected_rows}
    )
    refresh_transactions(manifest)
    return manifest


def valid_non_submit_postwrite_manifest() -> dict:
    manifest = valid_non_submit_manifest()
    manifest["stage"] = "postwrite"
    manifest["state"] = "COMPLETE"
    manifest["copy"]["revision_postwrite"] = 4
    manifest["pool"]["revision_postwrite"] = 9
    manifest["pool"]["postwrite_keys"] = [
        "douyin:douyin.com/user/old",
        "douyin:douyin.com/user/abc",
    ]
    manifest["pool"]["postwrite_key_rows"] = {
        "douyin:douyin.com/user/old": 2,
        "douyin:douyin.com/user/abc": 3,
    }
    for write in manifest["writes"]:
        write["succeeded"] = True
        write["readback_matches"] = True
        write["skipped_due_to_prior_failure"] = False
    manifest["counts"]["writes_succeeded"] = len(manifest["writes"])
    manifest["readback"]["copy_addresses"] = []
    manifest["readback"]["pool_addresses"] = sorted(
        guard._write_address(write) for write in manifest["writes"]
    )
    manifest["report"].update(
        {
            "action": "create",
            "title_readback": manifest["report"]["title"],
            "token": "rejection-report-token",
            "revision_postcreate": 2,
            "actual_rows": copy.deepcopy(manifest["report"]["expected_rows"]),
            "actual_document_sha256": manifest["report"]["expected_document_sha256"],
            "preview_verified": False,
            "readback_verified": True,
        }
    )
    refresh_transactions(manifest, postwrite=True)
    return manifest


def structured_partial_manifest() -> dict:
    manifest = valid_postwrite_manifest()
    manifest["state"] = "PARTIAL_NEEDS_REVIEW"
    copy_write = next(write for write in manifest["writes"] if write["target"] == "copy")
    copy_write["succeeded"] = False
    copy_write["readback_matches"] = False
    for write in manifest["writes"]:
        if write["target"] != "pool":
            continue
        write["succeeded"] = None
        write["skipped_due_to_prior_failure"] = True
        write["skipped_unmodified_verified"] = True
        write.pop("readback_matches", None)
    pool_write_count = sum(write["target"] == "pool" for write in manifest["writes"])
    manifest["counts"].update(
        {"writes_succeeded": 0, "writes_failed": 1, "writes_skipped": pool_write_count}
    )
    manifest["pool"]["postwrite_keys"] = ["douyin:douyin.com/user/old"]
    manifest["pool"]["postwrite_key_rows"] = {"douyin:douyin.com/user/old": 2}
    manifest["transactions"]["copy"]["execute"].update({"ok": False, "attempted": True})
    manifest["transactions"]["pool"]["execute"].update({"ok": False, "attempted": False})
    manifest["report"].update(
        {
            "action": "defer",
            "title_readback": "",
            "token": "",
            "revision_postcreate": None,
            "actual_rows": [],
            "actual_document_sha256": "",
            "readback_verified": False,
        }
    )
    return manifest


class PendingTests(unittest.TestCase):
    def test_exact_pending_trims_unicode_edges(self) -> None:
        for value in ("待定", " 待定 ", "　待定　", "\u200b待定\ufeff"):
            self.assertTrue(guard.is_exact_pending(value))

    def test_pending_negative_cases(self) -> None:
        for value in ("暂定", "待定中", "暂待定", "待定（跟进）", "推进中", "", "否"):
            self.assertFalse(guard.is_exact_pending(value))


class ProfileKeyTests(unittest.TestCase):
    def test_douyin_query_fragment_and_subpage_do_not_change_key(self) -> None:
        first = guard.normalize_profile("https://www.douyin.com/user/ABC?share=1#x", "抖音")
        second = guard.normalize_profile("https://douyin.com/user/ABC/video/123", "douyin")
        self.assertEqual(first["key"], second["key"])
        self.assertTrue(first["auto_merge"])

    def test_xiaohongshu_profile_is_stable(self) -> None:
        result = guard.normalize_profile(
            "https://www.xiaohongshu.com/user/profile/5abc?xsec_token=1", "小红书"
        )
        self.assertEqual(result["kind"], "profile_url")
        self.assertIn("xiaohongshu.com/user/profile/5abc", result["key"])

    def test_bilibili_subpages_canonicalize_to_space_root(self) -> None:
        first = guard.normalize_profile("https://space.bilibili.com/123/dynamic", "B站")
        second = guard.normalize_profile("https://space.bilibili.com/123/video", "bilibili")
        self.assertEqual(first["key"], second["key"])
        self.assertTrue(first["key"].endswith("space.bilibili.com/123"))

    def test_short_link_fallback_is_not_cross_date_auto_merge(self) -> None:
        result = guard.normalize_profile("https://v.douyin.com/XYZ", "抖音", "达人甲", "机构乙")
        self.assertEqual(result["kind"], "fallback")
        self.assertFalse(result["auto_merge"])
        self.assertTrue(result["same_batch_dedupe"])

    def test_unknown_host_cannot_masquerade_as_douyin_profile(self) -> None:
        result = guard.normalize_profile("https://evil.example/user/abc", "抖音", "达人甲", "机构乙")
        self.assertEqual(result["kind"], "fallback")
        self.assertFalse(result["auto_merge"])

    def test_name_only_is_ambiguous(self) -> None:
        result = guard.normalize_profile("", "抖音", "达人甲", "")
        self.assertEqual(result["kind"], "ambiguous")
        self.assertFalse(result["auto_merge"])

    def test_content_url_is_not_treated_as_profile(self) -> None:
        result = guard.normalize_profile(
            "https://www.xiaohongshu.com/explore/123", "小红书", "达人甲", "机构乙"
        )
        self.assertEqual(result["kind"], "fallback")

    def test_raw_url_is_preserved(self) -> None:
        raw = "  https://v.douyin.com/ＡＢＣ  "
        result = guard.normalize_profile(raw, "抖音", "达人甲", "机构乙")
        self.assertEqual(result["raw_url"], raw)


class TopicTests(unittest.TestCase):
    def test_valid_four_line_topic(self) -> None:
        result = guard.validate_topic(VALID_TOPIC)
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["lines"]), 4)

    def test_missing_label_fails(self) -> None:
        result = guard.validate_topic(VALID_TOPIC.replace("功能：", "能力："))
        self.assertFalse(result["ok"])
        self.assertTrue(any("TOPIC_LABEL_ORDER" in error for error in result["errors"]))

    def test_extra_line_fails(self) -> None:
        result = guard.validate_topic(VALID_TOPIC + "\n补充：不要出现第五段")
        self.assertFalse(result["ok"])
        self.assertTrue(any("TOPIC_LINE_COUNT" in error for error in result["errors"]))

    def test_over_260_characters_fails(self) -> None:
        result = guard.validate_topic(VALID_TOPIC.replace("版本一多", "资料" * 100 + "版本一多"))
        self.assertFalse(result["ok"])
        self.assertTrue(any("TOPIC_TOO_LONG" in error for error in result["errors"]))

    def test_implementation_must_name_final_output(self) -> None:
        topic = VALID_TOPIC.replace("生成带关键词依据、风险标记和可直接复核的 Listing 文档", "完成处理")
        result = guard.validate_topic(topic)
        self.assertFalse(result["ok"])
        self.assertTrue(any("TOPIC_IMPLEMENTATION_ARTIFACT" in error for error in result["errors"]))

    def test_same_skill_different_task_or_artifact_is_not_same_key(self) -> None:
        first = guard.topic_key("应用生成", "班级签到", "学生名单", "签到网页", "长期")
        second = guard.topic_key("应用生成", "错题复盘", "错题图片", "复盘网页", "长期")
        self.assertNotEqual(first, second)

    def test_switching_skill_does_not_create_new_topic_key(self) -> None:
        first = guard.topic_key("应用生成", "班级签到", "学生名单", "签到网页", "长期")
        second = guard.topic_key("可视化", "班级 签到", "学生 名单", "签到 网页", "长期")
        self.assertEqual(first, second)


class ManifestTests(unittest.TestCase):
    def assert_error(self, manifest: dict, code: str) -> None:
        result = guard.validate_manifest(manifest)
        self.assertFalse(result["ok"], result)
        self.assertTrue(any(code in error for error in result["errors"]), result)

    def test_valid_manifest(self) -> None:
        result = guard.validate_manifest(valid_manifest())
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["safe_to_execute"], result)

    def test_valid_pool_update_manifest(self) -> None:
        manifest = valid_manifest()
        update_pool_candidate(manifest)
        result = guard.validate_manifest(manifest)
        self.assertTrue(result["ok"], result)

    def test_valid_nonpending_creator_row_is_scanned_but_not_synced(self) -> None:
        manifest = valid_manifest()
        candidate = manifest["pool_candidates"][0]
        candidate["raw_status"] = "否"
        candidate["raw_status_prewrite"] = "否"
        candidate["selected"] = False
        candidate["sync_action"] = ""
        candidate["source_snapshot"]["raw_status"] = "否"
        candidate["source_fingerprint"] = guard._source_snapshot_fingerprint(
            candidate["source_snapshot"]
        )
        manifest["writes"] = [write for write in manifest["writes"] if write["target"] == "copy"]
        manifest["counts"].update(
            {"pending_detected": 0, "inserted": 0, "writes_planned": len(manifest["writes"])}
        )
        refresh_transactions(manifest)
        result = guard.validate_manifest(manifest)
        self.assertTrue(result["ok"], result)

    def test_valid_audit_manifest(self) -> None:
        result = guard.validate_manifest(valid_audit_manifest())
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["safe_to_execute"], result)

    def test_empty_audit_cannot_claim_plan_built(self) -> None:
        template = json.loads((SKILL_DIR / "templates/batch-manifest.json").read_text(encoding="utf-8"))
        template["state"] = "PLAN_BUILT"
        self.assert_error(template, "BRIEF_URL_REQUIRED")

    def test_audit_mode_rejects_any_write(self) -> None:
        template = json.loads((SKILL_DIR / "templates/batch-manifest.json").read_text(encoding="utf-8"))
        template["writes"] = [{"target": "copy"}]
        self.assert_error(template, "AUDIT_ZERO_WRITES")

    def test_resource_tokens_must_be_pairwise_distinct(self) -> None:
        manifest = valid_manifest()
        manifest["pool"]["token"] = "copy-token"
        for write in manifest["writes"]:
            if write["target"] == "pool":
                write["token"] = "copy-token"
        self.assert_error(manifest, "RESOURCE_TOKENS_PAIRWISE_DISTINCT")

    def test_source_revision_drift_blocks_stale_plan(self) -> None:
        manifest = valid_manifest()
        manifest["source"]["revision_prewrite"] = 11
        self.assert_error(manifest, "SOURCE_REVISION_STABLE_OR_REPLAN")

    def test_revision_must_be_positive_integer(self) -> None:
        manifest = valid_manifest()
        manifest["copy"]["revision_prewrite"] = "3"
        self.assert_error(manifest, "COPY_REVISION_POSITIVE")

    def test_copy_revision_drift_blocks_write(self) -> None:
        manifest = valid_manifest()
        manifest["copy"]["revision_prewrite"] = 4
        self.assert_error(manifest, "COPY_REVISION_UNCHANGED_PREWRITE")

    def test_full_copy_manifest_is_required(self) -> None:
        manifest = valid_manifest()
        manifest["copy"]["manifest_verified"] = False
        self.assert_error(manifest, "COPY_MANIFEST_VERIFIED")

    def test_header_mapping_must_be_unique_and_bound_to_sheet(self) -> None:
        manifest = valid_manifest()
        manifest["headers"]["creator_skill"]["status"]["match_count"] = 2
        self.assert_error(manifest, "HEADER_MAPPING_EXACT_UNIQUE")

    def test_copy_target_and_creator_sheet_mapping_cannot_be_swapped(self) -> None:
        manifest = valid_manifest()
        manifest["copy"]["target_sheet_id"] = "creator-copy"
        manifest["copy"]["creator_skill_sheet_id"] = "target-copy"
        self.assert_error(manifest, "COPY_TARGET_SHEET_MAPPING_MATCH")

    def test_missing_source_sheet_ids_is_rejected(self) -> None:
        manifest = valid_manifest()
        manifest["source"]["creator_skill_sheet_id"] = ""
        self.assert_error(manifest, "SOURCE_CREATOR_SHEET_REQUIRED")

    def test_fingerprint_mismatch_is_rejected(self) -> None:
        manifest = valid_manifest()
        manifest["writes"][0]["expected_fingerprint"] = "wrong"
        self.assert_error(manifest, "ROW_FINGERPRINT_MATCHES_PREWRITE")

    def test_extra_copy_write_row_is_rejected(self) -> None:
        manifest = valid_manifest()
        manifest["writes"].append(
            {
                "target": "copy",
                "token": "copy-token",
                "sheet_id": "target-copy",
                "row": 999,
                "column": "L",
                "action": "set",
                "value": VALID_TOPIC,
                "expected_fingerprint": "fp-row-999",
                "prewrite_value_hash": "hash:empty",
            }
        )
        manifest["counts"]["writes_planned"] += 1
        self.assert_error(manifest, "COPY_WRITE_ROW_IN_DECISIONS")

    def test_non_submit_row_cannot_receive_topic(self) -> None:
        manifest = valid_manifest()
        manifest["rows"][0]["decision"] = "NEEDS_EVIDENCE"
        manifest["rows"][0]["reason_code"] = "IDENTITY_EVIDENCE_MISSING"
        manifest["counts"].update({"submit": 0, "needs_evidence": 1})
        self.assert_error(manifest, "NON_SUBMIT_HAS_WRITE")

    def test_non_submit_reason_fields_are_required(self) -> None:
        manifest = valid_manifest()
        manifest["rows"][0]["decision"] = "NEEDS_EVIDENCE"
        manifest["rows"][0]["reason_code"] = ""
        manifest["writes"] = [write for write in manifest["writes"] if write["target"] == "pool"]
        manifest["counts"].update(
            {"submit": 0, "needs_evidence": 1, "writes_planned": len(manifest["writes"])}
        )
        self.assert_error(manifest, "ROW_FIELD_REQUIRED")

    def test_empty_pool_allowlist_is_rejected(self) -> None:
        manifest = valid_manifest()
        manifest["pool"]["allowed_columns"] = []
        self.assert_error(manifest, "POOL_COLUMN_ALLOWLIST_EXACT")

    def test_creator_sheet_scan_coverage_is_exact(self) -> None:
        manifest = valid_manifest()
        manifest["source"]["creator_skill_expected_rows"] = [5, 6]
        self.assert_error(manifest, "CREATOR_SHEET_SCAN_COVERAGE")

    def test_selected_must_be_json_boolean(self) -> None:
        manifest = valid_manifest()
        manifest["pool_candidates"][0]["selected"] = "false"
        self.assert_error(manifest, "PENDING_SELECTED_BOOLEAN")

    def test_pending_substring_cannot_be_selected(self) -> None:
        manifest = valid_manifest()
        manifest["pool_candidates"][0]["raw_status_prewrite"] = "待定中"
        self.assert_error(manifest, "PENDING_FILTER_EXACT_ONLY")

    def test_pending_status_written_to_pool_must_remain_pending(self) -> None:
        manifest = valid_manifest()
        candidate = manifest["pool_candidates"][0]
        candidate["values"]["原是否合作"] = "否"
        candidate["values"]["当前状态"] = "已合作"
        for write in manifest["writes"]:
            if write.get("logical_field") in {"原是否合作", "当前状态"}:
                write["value"] = candidate["values"][write["logical_field"]]
        refresh_transactions(manifest)
        self.assert_error(manifest, "POOL_CURRENT_STATUS_PENDING")

    def test_pool_profile_key_must_be_recomputed_from_source_snapshot(self) -> None:
        manifest = valid_manifest()
        candidate = manifest["pool_candidates"][0]
        wrong_key = "douyin:douyin.com/user/wrong"
        candidate["profile_key"] = wrong_key
        candidate["values"]["主页去重键"] = wrong_key
        for write in manifest["writes"]:
            if write["target"] == "pool":
                write["candidate_key"] = wrong_key
                if write.get("logical_field") == "主页去重键":
                    write["value"] = wrong_key
        refresh_transactions(manifest)
        self.assert_error(manifest, "PROFILE_KEY_MATCH_SOURCE")

    def test_pending_status_is_bound_to_creator_sheet_header(self) -> None:
        manifest = valid_manifest()
        snapshot = manifest["pool_candidates"][0]["source_snapshot"]
        snapshot["status_column"] = "E"
        manifest["pool_candidates"][0]["source_fingerprint"] = guard._source_snapshot_fingerprint(
            snapshot
        )
        self.assert_error(manifest, "PENDING_STATUS_COLUMN_BOUND_TO_HEADER")

    def test_profile_key_is_required_for_insert(self) -> None:
        manifest = valid_manifest()
        manifest["pool_candidates"][0]["profile_key"] = ""
        self.assert_error(manifest, "PROFILE_KEY_REQUIRED")

    def test_insert_key_must_not_already_exist(self) -> None:
        manifest = valid_manifest()
        existing = manifest["pool"]["existing_keys"][0]
        candidate = manifest["pool_candidates"][0]
        candidate["profile_key"] = existing
        candidate["values"]["主页去重键"] = existing
        for write in manifest["writes"]:
            if write["target"] == "pool":
                write["candidate_key"] = existing
                if write["logical_field"] == "主页去重键":
                    write["value"] = existing
        self.assert_error(manifest, "POOL_INSERT_KEY_MUST_NOT_EXIST")

    def test_pool_partial_write_is_rejected(self) -> None:
        manifest = valid_manifest()
        manifest["writes"] = [manifest["writes"][0], manifest["writes"][1]]
        manifest["counts"]["writes_planned"] = 2
        self.assert_error(manifest, "POOL_WRITES_MATCH_CHANGED_FIELDS")

    def test_first_seen_fields_are_immutable_on_update(self) -> None:
        manifest = valid_manifest()
        update_pool_candidate(manifest)
        candidate = manifest["pool_candidates"][0]
        candidate["changed_fields"].append("首次收录日期")
        self.assert_error(manifest, "POOL_UPDATE_FIELDS_VALID")

    def test_fallback_cannot_cross_date_update_without_identity_evidence(self) -> None:
        manifest = valid_manifest()
        update_pool_candidate(manifest)
        candidate = manifest["pool_candidates"][0]
        candidate["key_kind"] = "fallback"
        candidate["identity_evidence"] = []
        self.assert_error(manifest, "FALLBACK_CROSS_DATE_MERGE_BLOCKED")

    def test_duplicate_cell_address_is_rejected(self) -> None:
        manifest = valid_manifest()
        manifest["writes"].append(copy.deepcopy(manifest["writes"][1]))
        manifest["counts"]["writes_planned"] += 1
        self.assert_error(manifest, "NO_DUPLICATE_CELL_ADDRESSES")

    def test_decision_coverage_must_match_source_rows(self) -> None:
        manifest = valid_manifest()
        manifest["source"]["expected_source_rows"] = [2, 3]
        self.assert_error(manifest, "DECISION_COVERAGE_EXACT")

    def test_counts_are_mandatory(self) -> None:
        manifest = valid_manifest()
        del manifest["counts"]["pending_detected"]
        self.assert_error(manifest, "COUNTS_COMPLETE")

    def test_transaction_top_level_token_cannot_point_to_source(self) -> None:
        manifest = valid_manifest()
        manifest["transactions"]["copy"]["top_level_token"] = "source-token"
        self.assert_error(manifest, "TRANSACTION_SOURCE_TARGET_FORBIDDEN")

    def test_transaction_hash_detects_changed_write_payload(self) -> None:
        manifest = valid_manifest()
        manifest["writes"][0]["value"] = VALID_TOPIC.replace("跨境电商", "外贸")
        self.assert_error(manifest, "TRANSACTION_PAYLOAD_HASH_MATCH")

    def test_postwrite_requires_execute_receipt(self) -> None:
        manifest = valid_postwrite_manifest()
        manifest["transactions"]["copy"]["execute"] = None
        self.assert_error(manifest, "EXECUTE_RECEIPT_REQUIRED")

    def test_transaction_hash_is_independent_of_write_order(self) -> None:
        manifest = valid_manifest()
        manifest["writes"] = list(reversed(manifest["writes"]))
        result = guard.validate_manifest(manifest)
        self.assertTrue(result["ok"], result)

    def test_derive_plan_evidence_matches_valid_manifest(self) -> None:
        manifest = valid_manifest()
        derived = guard.derive_plan_evidence(manifest)
        self.assertEqual(derived["transactions"], {
            target: {
                **{key: value for key, value in transaction.items() if key not in {"dry_run", "execute"}},
                "dry_run": None,
                "execute": None,
            }
            for target, transaction in manifest["transactions"].items()
        })
        self.assertEqual(
            derived["source_fingerprints"][0]["source_fingerprint"],
            manifest["pool_candidates"][0]["source_fingerprint"],
        )

    def test_partial_prewrite_is_never_executable(self) -> None:
        manifest = valid_manifest()
        manifest["state"] = "PARTIAL_NEEDS_REVIEW"
        result = guard.validate_manifest(manifest)
        self.assertFalse(result["ok"], result)
        self.assertFalse(result["safe_to_execute"], result)
        self.assertTrue(any("PARTIAL_REQUIRES_REVIEW" in item for item in result["errors"]))

    def test_partial_postwrite_stops_pool_and_defers_report(self) -> None:
        result = guard.validate_manifest(structured_partial_manifest())
        self.assertFalse(result["ok"], result)
        self.assertTrue(any("PARTIAL_REQUIRES_REVIEW" in item for item in result["errors"]))
        for forbidden in (
            "POOL_PHASE_SKIPPED_AFTER_COPY_FAILURE",
            "PARTIAL_REPORT_DEFERRED",
            "EXECUTE_RECEIPT_RESULT_MATCH",
            "WRITE_RECEIPT_REQUIRED",
        ):
            self.assertFalse(any(forbidden in item for item in result["errors"]), result)

    def test_submit_cannot_repeat_historical_duplicate_key(self) -> None:
        manifest = valid_manifest()
        duplicate_key = manifest["rows"][0]["duplicate_key"]
        manifest["history"]["duplicate_keys"] = [duplicate_key]
        manifest["rows"][0]["historical_match"] = {
            "status": "exact",
            "matched_duplicate_keys": [duplicate_key],
            "evidence": ["history-row:2"],
        }
        self.assert_error(manifest, "SUBMIT_NOT_HISTORICAL_EXACT_DUPLICATE")

    def test_reason_code_cannot_be_arbitrary(self) -> None:
        manifest = valid_manifest()
        manifest["rows"][0]["reason_code"] = "ARBITRARY"
        self.assert_error(manifest, "REASON_CODE_ALLOWED_FOR_DECISION")

    def test_same_batch_complete_topic_duplicate_is_rejected(self) -> None:
        manifest = valid_manifest()
        second = copy.deepcopy(manifest["rows"][0])
        second.update({"row": 3, "creator": "达人乙", "profile_key": "douyin:douyin.com/user/xyz", "fingerprint": "fp-row-3"})
        manifest["rows"].append(second)
        manifest["source"]["expected_source_rows"] = [2, 3]
        manifest["writes"].append(
            {
                "target": "copy",
                "token": "copy-token",
                "sheet_id": "target-copy",
                "row": 3,
                "column": "L",
                "action": "set",
                "value": VALID_TOPIC,
                "expected_fingerprint": "fp-row-3",
                "prewrite_value_hash": "hash:empty-cell-row-3",
            }
        )
        manifest["counts"].update(
            {"decision_total": 2, "submit": 2, "writes_planned": len(manifest["writes"])}
        )
        refresh_transactions(manifest)
        self.assert_error(manifest, "SUBMIT_TOPIC_DUPLICATE_IN_BATCH")

    def test_valid_postwrite_manifest(self) -> None:
        result = guard.validate_manifest(valid_postwrite_manifest())
        self.assertTrue(result["ok"], result)

    def test_valid_non_submit_report_is_reconciled(self) -> None:
        result = guard.validate_manifest(valid_non_submit_postwrite_manifest())
        self.assertTrue(result["ok"], result)

    def test_rejection_report_cannot_omit_a_non_submit_row(self) -> None:
        manifest = valid_non_submit_postwrite_manifest()
        manifest["report"]["actual_rows"] = []
        self.assert_error(manifest, "REPORT_ACTUAL_ROW_COVERAGE_AND_HASH")

    def test_postwrite_pool_keys_must_equal_expected_full_set(self) -> None:
        manifest = valid_postwrite_manifest()
        manifest["pool"]["postwrite_keys"] = ["unrelated:key"]
        manifest["pool"]["postwrite_key_rows"] = {"unrelated:key": 2}
        self.assert_error(manifest, "POOL_POSTWRITE_KEYS_EXACT")

    def test_postwrite_requires_exact_readback_for_every_write(self) -> None:
        manifest = valid_postwrite_manifest()
        manifest["writes"][0]["readback_matches"] = False
        self.assert_error(manifest, "READBACK_EXACT_FOR_EVERY_OP")

    def test_complete_state_rejects_failed_write(self) -> None:
        manifest = valid_postwrite_manifest()
        manifest["writes"][0]["succeeded"] = False
        manifest["counts"]["writes_succeeded"] -= 1
        manifest["counts"]["writes_failed"] = 1
        self.assert_error(manifest, "COMPLETE_WITH_FAILED_WRITES")


class PackageTests(unittest.TestCase):
    def test_required_files_exist(self) -> None:
        required = [
            "SKILL.md",
            "references/project-config.md",
            "references/policy-gates.md",
            "references/sheet-and-pool-protocol.md",
            "references/research-and-topic-spec.md",
            "templates/batch-manifest.json",
            "templates/row-decision.json",
            "templates/pool-candidate.json",
            "templates/rejection-report.md",
            "templates/execution-report.md",
            "scripts/workflow_guard.py",
        ]
        for relative in required:
            self.assertTrue((SKILL_DIR / relative).is_file(), relative)

    def test_manifest_template_is_valid_and_audit_safe(self) -> None:
        with (SKILL_DIR / "templates/batch-manifest.json").open(encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["schema_version"], "1.1")
        self.assertEqual(payload["state"], "DISCOVERED")
        result = guard.validate_manifest(payload)
        self.assertTrue(result["ok"], result)
        self.assertTrue(any("DRAFT_SCAFFOLD_ONLY" in item for item in result["warnings"]))

    def test_row_decision_template_is_valid_json(self) -> None:
        with (SKILL_DIR / "templates/row-decision.json").open(encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["decision"], "SUBMIT")

    def test_pool_candidate_template_has_complete_values(self) -> None:
        with (SKILL_DIR / "templates/pool-candidate.json").open(encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertTrue(payload["selected"])
        self.assertEqual(set(payload["values"]), set(guard.POOL_FIELDS))
        self.assertEqual(
            set(payload["changed_fields"]),
            {field for field, value in payload["values"].items() if guard.normalize_text(value)},
        )
        self.assertEqual(
            payload["source_fingerprint"],
            guard._source_snapshot_fingerprint(payload["source_snapshot"]),
        )
        normalized = guard.normalize_profile(
            payload["source_snapshot"]["raw_homepage"],
            payload["source_snapshot"]["platform"],
            payload["source_snapshot"]["creator"],
            payload["source_snapshot"]["agency"],
        )
        self.assertEqual(payload["profile_key"], normalized["key"])

    def test_skill_frontmatter_and_latest_policy_are_present(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(content.startswith("---\nname: doubao-creator-topic-submission\n"))
        self.assertIn("题目不完全重复", content)
        self.assertIn("同一个 Skill 或同一能力大类本身不是淘汰理由", content)
        self.assertIn("源表只读", content)
        self.assertIn("audit", content)


if __name__ == "__main__":
    unittest.main()
