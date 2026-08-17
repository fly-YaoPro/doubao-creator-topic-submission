#!/usr/bin/env python3
"""Deterministic guards for the creator-topic submission workflow.

This module deliberately does not access Feishu or the network. It validates
local plans before cloud writes and normalizes only fields whose behavior must
not depend on model judgment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit


TOPIC_LABELS = (
    "身份：",
    "功能：",
    "痛点 / 场景：",
    "具体实现与步骤：",
)

DECISIONS = {
    "SUBMIT",
    "BUSINESS_BLOCK",
    "NEEDS_EVIDENCE",
    "RETOPIC",
    "ANOMALY",
}

REASON_CODES = {
    "SUBMIT": {"BRIEF_FIT_UNIQUE_TOPIC"},
    "BUSINESS_BLOCK": {
        "CURRENT_STATUS_NO",
        "HISTORICAL_STATUS_NO",
        "BLACKLISTED",
        "ALREADY_COOPERATED",
        "DUPLICATE_PROFILE_SAME_BATCH",
        "HARD_INDUSTRY_BLOCK",
        "LIVE_BRIEF_EXCLUSION",
        "CAPABILITY_UNAVAILABLE",
        "USER_CONFIRMED_BLOCK",
    },
    "NEEDS_EVIDENCE": {
        "PROFILE_UNAVAILABLE",
        "IDENTITY_EVIDENCE_MISSING",
        "HUMAN_APPEARANCE_UNVERIFIED",
        "LOGIN_OR_RISK_CONTROL_BLOCKED",
        "SKILL_PERMISSION_UNVERIFIED",
        "HISTORY_IDENTITY_CONFLICT",
    },
    "RETOPIC": {
        "BRIEF_MISMATCH",
        "PC_FIT_INSUFFICIENT",
        "FINAL_ARTIFACT_INSUFFICIENT",
        "DATA_UNAVAILABLE",
        "TIME_WINDOW_INVALID",
        "CAPABILITY_LIFECYCLE_MISMATCH",
        "EXACT_TOPIC_DUPLICATE",
        "RETOPIC_ATTEMPTS_EXHAUSTED",
    },
    "ANOMALY": {
        "SHEET_STRUCTURE_ANOMALY",
        "DUPLICATE_POOL_KEY",
        "REVISION_DRIFT",
        "TOOL_FAILURE",
        "IDENTITY_KEY_AMBIGUOUS",
    },
}

HISTORICAL_MATCH_STATUSES = {"none", "similar", "exact"}

POOL_ACTIONS = {"insert", "update", "noop", "anomaly"}
STAGES = {"plan", "prewrite", "postwrite"}
STATES = {
    "DISCOVERED",
    "SOURCE_SNAPSHOTTED",
    "COPY_CREATED",
    "COPY_VERIFIED",
    "PLAN_BUILT",
    "PREWRITE_REVALIDATED",
    "COPY_WRITTEN_VERIFIED",
    "POOL_SYNCED_VERIFIED",
    "REPORT_VERIFIED",
    "PARTIAL_NEEDS_REVIEW",
    "COMPLETE",
}

POOL_FIELDS = (
    "达人名称",
    "主页链接",
    "主页去重键",
    "平台",
    "标签",
    "一级行业",
    "二级行业",
    "合作形式",
    "粉丝量（万）",
    "达人量级",
    "机构名",
    "原是否合作",
    "当前状态",
    "首次收录日期",
    "最近同步日期",
    "首次来源工作表",
    "最近来源工作表",
    "首次源行号",
    "最近源行号",
    "提报时间",
    "预定发布日期",
    "原选题",
    "源表链接",
)

POOL_CORE_FIELDS = {
    "达人名称",
    "主页去重键",
    "平台",
    "原是否合作",
    "当前状态",
    "首次收录日期",
    "最近同步日期",
    "首次来源工作表",
    "最近来源工作表",
    "首次源行号",
    "最近源行号",
    "源表链接",
}

POOL_FIRST_SEEN_FIELDS = {"首次收录日期", "首次来源工作表", "首次源行号"}
ZERO_WIDTH_EDGE = {"\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"}

HOST_ALIASES = {
    "www.douyin.com": "douyin.com",
    "m.douyin.com": "douyin.com",
    "www.xiaohongshu.com": "xiaohongshu.com",
    "m.xiaohongshu.com": "xiaohongshu.com",
    "www.bilibili.com": "bilibili.com",
    "m.bilibili.com": "bilibili.com",
    "www.youtube.com": "youtube.com",
    "m.youtube.com": "youtube.com",
    "www.zhihu.com": "zhihu.com",
}

SHORT_LINK_HOSTS = {
    "v.douyin.com",
    "xhslink.com",
    "b23.tv",
    "t.cn",
    "dwz.cn",
    "bit.ly",
    "tinyurl.com",
}

CONTENT_SEGMENTS = {
    "video",
    "videos",
    "explore",
    "note",
    "notes",
    "discovery",
    "item",
    "watch",
    "shorts",
    "post",
    "posts",
}

PROFILE_MARKERS = {"user", "profile", "people", "author", "channel", "space", "u", "c"}

PLATFORM_HOSTS = {
    "douyin": {"douyin.com"},
    "xiaohongshu": {"xiaohongshu.com"},
    "bilibili": {"bilibili.com", "space.bilibili.com"},
    "youtube": {"youtube.com"},
    "zhihu": {"zhihu.com"},
    "weibo": {"weibo.com"},
    "kuaishou": {"kuaishou.com"},
}


def strip_text_edges(value: Any, *, nfkc: bool = True) -> str:
    """Trim Unicode/zero-width edge whitespace, optionally applying NFKC."""

    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)) if nfkc else str(value)
    start = 0
    end = len(text)
    while start < end and (text[start].isspace() or text[start] in ZERO_WIDTH_EDGE):
        start += 1
    while end > start and (text[end - 1].isspace() or text[end - 1] in ZERO_WIDTH_EDGE):
        end -= 1
    return text[start:end]


def normalize_text(value: Any) -> str:
    """NFKC-normalize and trim Unicode/zero-width edge whitespace."""

    return strip_text_edges(value, nfkc=True)


def compact_key_part(value: Any) -> str:
    text = normalize_text(value).lower()
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", text)


def is_exact_pending(value: Any) -> bool:
    return normalize_text(value) == "待定"


def infer_platform(explicit: Any, host: str = "") -> str:
    raw = normalize_text(explicit).lower()
    compact = compact_key_part(raw)
    aliases = (
        (("抖音", "douyin"), "douyin"),
        (("小红书", "xiaohongshu", "xhs", "rednote"), "xiaohongshu"),
        (("哔哩哔哩", "bilibili", "b站"), "bilibili"),
        (("youtube", "油管"), "youtube"),
        (("知乎", "zhihu"), "zhihu"),
        (("微博", "weibo"), "weibo"),
        (("快手", "kuaishou"), "kuaishou"),
    )
    for names, canonical in aliases:
        if any(compact_key_part(name) in compact for name in names):
            return canonical

    host_lower = host.lower()
    for needle, canonical in (
        ("douyin.com", "douyin"),
        ("xiaohongshu.com", "xiaohongshu"),
        ("bilibili.com", "bilibili"),
        ("youtube.com", "youtube"),
        ("youtu.be", "youtube"),
        ("zhihu.com", "zhihu"),
        ("weibo.com", "weibo"),
        ("kuaishou.com", "kuaishou"),
    ):
        if needle in host_lower:
            return canonical

    return compact or compact_key_part(host_lower) or "unknown"


def _prepare_url(raw_url: Any) -> tuple[str, str, str] | None:
    original = "" if raw_url is None else str(raw_url)
    raw = normalize_text(raw_url)
    if not raw:
        return None
    candidate = raw if "://" in raw else f"https://{raw}"
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return None
    host = HOST_ALIASES.get(host, host)
    path = re.sub(r"/{2,}", "/", unquote(parsed.path or "/"))
    if path != "/":
        path = path.rstrip("/")
    return host, path, original


def _stable_profile_path(host: str, path: str) -> tuple[bool, str]:
    if host in SHORT_LINK_HOSTS:
        return False, "share_short_link"

    segments = [segment for segment in path.split("/") if segment]
    lower = [segment.lower() for segment in segments]
    if not segments:
        return False, "missing_profile_path"

    if host == "space.bilibili.com" and compact_key_part(segments[0]):
        return True, "bilibili_space"
    if host == "douyin.com":
        return (len(lower) >= 2 and lower[0] == "user", "douyin_user_path")
    if host == "xiaohongshu.com":
        return (len(lower) >= 3 and lower[:2] == ["user", "profile"], "xiaohongshu_profile_path")
    if host == "zhihu.com":
        return (len(lower) >= 2 and lower[0] in {"people", "org"}, "zhihu_profile_path")
    if host == "youtube.com":
        if segments[0].startswith("@") and len(segments[0]) > 1:
            return True, "youtube_handle"
        return (len(lower) >= 2 and lower[0] in {"channel", "user", "c"}, "youtube_profile_path")

    if lower[0] in CONTENT_SEGMENTS:
        return False, "content_url_not_profile"
    if any(segment in CONTENT_SEGMENTS for segment in lower[:2]) and not any(
        marker in PROFILE_MARKERS for marker in lower[:2]
    ):
        return False, "content_url_not_profile"
    if any(marker in PROFILE_MARKERS for marker in lower[:2]) and len(segments) >= 2:
        return True, "generic_profile_path"
    return False, "unrecognized_profile_path"


def normalize_profile(
    raw_url: Any = "",
    platform: Any = "",
    creator_name: Any = "",
    agency: Any = "",
) -> dict[str, Any]:
    """Return a namespaced stable/fallback/ambiguous creator key."""

    prepared = _prepare_url(raw_url)
    url_reason = "missing_url"
    if prepared:
        host, path, original = prepared
        stable, url_reason = _stable_profile_path(host, path)
        platform_key = infer_platform(platform, host)
        allowed_hosts = PLATFORM_HOSTS.get(platform_key)
        if stable and allowed_hosts and host not in allowed_hosts:
            stable = False
            url_reason = "platform_host_mismatch"
        if stable and platform_key == "unknown":
            stable = False
            url_reason = "unknown_platform_not_auto_merge"
        if stable:
            segments = [segment for segment in path.split("/") if segment]
            if host == "space.bilibili.com":
                canonical_path = f"/{segments[0]}"
            elif host == "douyin.com":
                canonical_path = "/" + "/".join(segments[:2])
            elif host == "xiaohongshu.com":
                canonical_path = "/" + "/".join(segments[:3])
            elif host == "zhihu.com":
                canonical_path = "/" + "/".join(segments[:2])
            elif host == "youtube.com" and segments[0].startswith("@"):
                canonical_path = f"/{segments[0]}"
            elif host == "youtube.com":
                canonical_path = "/" + "/".join(segments[:2])
            else:
                canonical_path = path if path != "/" else ""
            canonical = f"{host}{canonical_path}"
            return {
                "key": f"{platform_key}:{canonical}",
                "kind": "profile_url",
                "platform": platform_key,
                "canonical_url": f"https://{canonical}",
                "raw_url": original,
                "auto_merge": True,
                "same_batch_dedupe": True,
                "reason": url_reason,
            }

    platform_key = infer_platform(platform, prepared[0] if prepared else "")
    name_key = compact_key_part(creator_name)
    agency_key = compact_key_part(agency)
    if name_key and agency_key:
        return {
            "key": f"fallback:{platform_key}:{name_key}:{agency_key}",
            "kind": "fallback",
            "platform": platform_key,
            "canonical_url": "",
            "raw_url": "" if raw_url is None else str(raw_url),
            "auto_merge": False,
            "same_batch_dedupe": True,
            "reason": url_reason,
        }
    if name_key:
        return {
            "key": f"ambiguous:{platform_key}:{name_key}",
            "kind": "ambiguous",
            "platform": platform_key,
            "canonical_url": "",
            "raw_url": "" if raw_url is None else str(raw_url),
            "auto_merge": False,
            "same_batch_dedupe": False,
            "reason": f"{url_reason}; agency_missing",
        }
    raise ValueError("cannot build profile key: no stable profile URL or creator name")


def validate_topic(text: Any, soft_limit: int = 220, hard_limit: int = 260) -> dict[str, Any]:
    # Preserve full-width Chinese punctuation: NFKC would turn the required
    # label colon `：` into `:` and make a visually correct topic fail.
    normalized = strip_text_edges(text, nfkc=False).replace("\r\n", "\n").replace("\r", "\n")
    lines = [
        strip_text_edges(line, nfkc=False)
        for line in normalized.split("\n")
        if strip_text_edges(line, nfkc=False)
    ]
    errors: list[str] = []
    warnings: list[str] = []

    if len(lines) != 4:
        errors.append(f"TOPIC_LINE_COUNT: expected 4 non-empty lines, got {len(lines)}")

    fields: dict[str, str] = {}
    for index, label in enumerate(TOPIC_LABELS):
        if index >= len(lines):
            errors.append(f"TOPIC_LABEL_MISSING: {label}")
            continue
        line = lines[index]
        if not line.startswith(label):
            errors.append(f"TOPIC_LABEL_ORDER: line {index + 1} must start with {label}")
            continue
        value = strip_text_edges(line[len(label) :], nfkc=False)
        fields[label[:-1]] = value
        if not value:
            errors.append(f"TOPIC_FIELD_EMPTY: {label}")
        sentence_marks = len(re.findall(r"[。！？!?]", value))
        if sentence_marks > 1:
            warnings.append(f"TOPIC_FIELD_MULTI_SENTENCE: {label} contains {sentence_marks} sentences")

    char_count = len("".join(lines))
    if char_count > hard_limit:
        errors.append(f"TOPIC_TOO_LONG: {char_count} characters exceeds hard limit {hard_limit}")
    elif char_count > soft_limit:
        warnings.append(f"TOPIC_LONG: {char_count} characters exceeds preferred limit {soft_limit}")

    if any(term in normalized for term in ("请帮我", "麻烦帮我")):
        warnings.append("TOPIC_POLITE_PROMPT: remove prompt-style polite wording")

    implementation = fields.get("具体实现与步骤", "")
    if implementation and "豆包" not in implementation and "AI" not in implementation.upper():
        errors.append("TOPIC_IMPLEMENTATION_AGENT: implementation must say what 豆包/AI does")
    if implementation and not any(
        term in implementation
        for term in ("上传", "导入", "录入", "提供", "选择", "连接", "克隆", "读取", "粘贴", "同步")
    ):
        warnings.append("TOPIC_IMPLEMENTATION_INPUT: make the input action explicit")
    if implementation and not any(
        term in implementation
        for term in ("生成", "输出", "得到", "形成", "产出", "交付", "搭建", "制作")
    ):
        errors.append("TOPIC_IMPLEMENTATION_ARTIFACT: implementation must name the final output")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "char_count": char_count,
        "lines": lines,
        "fields": fields,
    }


def topic_key(
    main_skill: Any,
    core_task: Any,
    key_input: Any,
    final_artifact: Any,
    lifecycle: Any = "",
) -> str:
    # main_skill is intentionally recorded but excluded from the duplicate
    # identity. Switching tools does not turn the same job/input/output into a
    # genuinely new topic.
    compact = [compact_key_part(part) for part in (core_task, key_input, final_artifact, lifecycle)]
    if not all(compact[:3]):
        raise ValueError("core_task, key_input and final_artifact are required")
    return "|".join(compact)


def _duplicates(values: Iterable[str]) -> set[str]:
    counts = Counter(value for value in values if value)
    return {value for value, count in counts.items() if count > 1}


def _int_set(values: Any, field_name: str, errors: list[str]) -> set[int]:
    if not isinstance(values, list):
        errors.append(f"{field_name}: expected a list")
        return set()
    result: set[int] = set()
    for value in values:
        if not isinstance(value, int) or value < 1:
            errors.append(f"{field_name}: invalid row {value!r}")
            continue
        if value in result:
            errors.append(f"{field_name}: duplicate row {value}")
        result.add(value)
    return result


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _write_address(write: dict[str, Any]) -> str:
    return "|".join(
        (
            normalize_text(write.get("target")),
            normalize_text(write.get("token")),
            normalize_text(write.get("sheet_id")),
            str(write.get("row", "")),
            normalize_text(write.get("column")).upper(),
        )
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _source_snapshot_fingerprint(snapshot: dict[str, Any]) -> str:
    fields = (
        "creator",
        "raw_homepage",
        "platform",
        "agency",
        "raw_status",
        "source_sheet_id",
        "source_sheet_title",
        "source_row",
        "source_revision",
        "source_url",
        "status_header",
        "status_column",
    )
    canonical = {field: snapshot.get(field) for field in fields}
    return _sha256(canonical)


def _transaction_envelope(target: str, token: str, writes: list[dict[str, Any]]) -> dict[str, Any]:
    operations = [
        {
            "sheet_id": normalize_text(write.get("sheet_id")),
            "row": write.get("row"),
            "column": normalize_text(write.get("column")).upper(),
            "action": normalize_text(write.get("action")),
            "value": write.get("value"),
        }
        for write in writes
    ]
    operations.sort(key=lambda item: (item["sheet_id"], item["row"], item["column"]))
    return {"target": target, "top_level_token": token, "operations": operations}


def _report_row(row: dict[str, Any]) -> dict[str, str]:
    row_number = row.get("row")
    profile_key = normalize_text(row.get("profile_key"))
    decision = normalize_text(row.get("decision"))
    evidence = sorted(
        normalize_text(item) for item in row.get("evidence", []) if normalize_text(item)
    )
    content = {
        "row": row_number,
        "creator": normalize_text(row.get("creator")),
        "profile_key": profile_key,
        "decision": decision,
        "reason_code": normalize_text(row.get("reason_code")),
        "evidence": evidence,
        "fix_condition": normalize_text(row.get("fix_condition")),
        "owner_action": normalize_text(row.get("owner_action")),
    }
    return {
        "row_key": f"decision:{row_number}:{profile_key}",
        "section": decision,
        "content_sha256": _sha256(content),
    }


def _validate_transactions(
    transactions: Any,
    writes: list[dict[str, Any]],
    *,
    stage: str,
    state: str,
    source_token: str,
    copy_token: str,
    pool_token: str,
    errors: list[str],
) -> None:
    if not isinstance(transactions, dict):
        errors.append("TRANSACTIONS_OBJECT_REQUIRED")
        return

    required_targets = {
        normalize_text(write.get("target"))
        for write in writes
        if normalize_text(write.get("target")) in {"copy", "pool"}
    }
    if set(transactions) != required_targets:
        errors.append("TRANSACTION_TARGET_COVERAGE")

    expected_tokens = {"copy": copy_token, "pool": pool_token}
    for target in sorted(required_targets):
        transaction = transactions.get(target)
        if not isinstance(transaction, dict):
            errors.append(f"TRANSACTION_OBJECT_REQUIRED: {target}")
            continue
        token = normalize_text(transaction.get("top_level_token"))
        expected_token = expected_tokens[target]
        if token != expected_token:
            errors.append(f"TRANSACTION_TOP_LEVEL_TOKEN_MATCH: {target}")
        if not token or token == source_token:
            errors.append(f"TRANSACTION_SOURCE_TARGET_FORBIDDEN: {target}")

        target_writes = [
            write for write in writes if normalize_text(write.get("target")) == target
        ]
        envelope = _transaction_envelope(target, token, target_writes)
        expected_hash = _sha256(envelope)
        operation_count = len(target_writes)
        if normalize_text(transaction.get("payload_sha256")) != expected_hash:
            errors.append(f"TRANSACTION_PAYLOAD_HASH_MATCH: {target}")
        if transaction.get("operation_count") != operation_count:
            errors.append(f"TRANSACTION_OPERATION_COUNT_MATCH: {target}")

        dry_run = transaction.get("dry_run")
        if not isinstance(dry_run, dict) or dry_run.get("ok") is not True:
            errors.append(f"DRY_RUN_RECEIPT_REQUIRED: {target}")
        else:
            if (
                normalize_text(dry_run.get("top_level_token")) != token
                or normalize_text(dry_run.get("payload_sha256")) != expected_hash
                or dry_run.get("operation_count") != operation_count
            ):
                errors.append(f"DRY_RUN_RECEIPT_MATCH: {target}")

        execute_receipt = transaction.get("execute")
        if stage == "prewrite":
            if execute_receipt not in (None, {}):
                errors.append(f"PREWRITE_EXECUTE_RECEIPT_EMPTY: {target}")
        elif stage == "postwrite":
            if not isinstance(execute_receipt, dict) or not isinstance(
                execute_receipt.get("ok"), bool
            ) or not isinstance(execute_receipt.get("attempted"), bool):
                errors.append(f"EXECUTE_RECEIPT_REQUIRED: {target}")
            else:
                if (
                    normalize_text(execute_receipt.get("top_level_token")) != token
                    or normalize_text(execute_receipt.get("payload_sha256")) != expected_hash
                    or execute_receipt.get("operation_count") != operation_count
                ):
                    errors.append(f"EXECUTE_REUSED_DRY_RUN_PAYLOAD: {target}")
                if state == "COMPLETE" and execute_receipt.get("ok") is not True:
                    errors.append(f"COMPLETE_TRANSACTION_FAILED: {target}")
                attempted_writes = [
                    write
                    for write in target_writes
                    if write.get("skipped_due_to_prior_failure") is not True
                ]
                all_succeeded = bool(target_writes) and all(
                    write.get("succeeded") is True for write in target_writes
                )
                if execute_receipt.get("attempted") is not bool(attempted_writes):
                    errors.append(f"EXECUTE_RECEIPT_ATTEMPT_MATCH: {target}")
                if execute_receipt.get("ok") is not all_succeeded:
                    errors.append(f"EXECUTE_RECEIPT_RESULT_MATCH: {target}")


def _validate_header_mapping(
    mapping: Any,
    *,
    required_fields: tuple[str, ...],
    expected_sheet_id: str,
    label: str,
    errors: list[str],
) -> dict[str, str]:
    if not isinstance(mapping, dict) or set(mapping) != set(required_fields):
        errors.append(f"HEADER_MAPPING_FIELDS_EXACT: {label}")
        return {}
    columns: dict[str, str] = {}
    for field in required_fields:
        entry = mapping.get(field)
        if not isinstance(entry, dict):
            errors.append(f"HEADER_MAPPING_ENTRY_REQUIRED: {label}.{field}")
            continue
        header_text = normalize_text(entry.get("header"))
        column = normalize_text(entry.get("column")).upper()
        if (
            not header_text
            or not re.fullmatch(r"[A-Z]{1,3}", column)
            or entry.get("match_count") != 1
            or normalize_text(entry.get("sheet_id")) != expected_sheet_id
        ):
            errors.append(f"HEADER_MAPPING_EXACT_UNIQUE: {label}.{field}")
        columns[field] = column
    if len(columns.values()) != len(set(columns.values())):
        errors.append(f"HEADER_COLUMNS_UNIQUE: {label}")
    return columns


def _canonical_sheet_manifest(
    entries: Any, field_name: str, errors: list[str], *, required: bool
) -> list[tuple[Any, ...]]:
    if not isinstance(entries, list) or (required and not entries):
        errors.append(f"{field_name}: non-empty list required")
        return []
    canonical: list[tuple[Any, ...]] = []
    seen_ids: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"{field_name}[{index}]: object required")
            continue
        sheet_id = normalize_text(entry.get("sheet_id"))
        title = normalize_text(entry.get("title"))
        position = entry.get("position")
        hidden = entry.get("hidden")
        row_count = entry.get("row_count")
        column_count = entry.get("column_count")
        used_range = normalize_text(entry.get("used_range"))
        used_hash = normalize_text(entry.get("used_range_hash"))
        if not sheet_id or sheet_id in seen_ids:
            errors.append(f"{field_name}[{index}]: unique sheet_id required")
        seen_ids.add(sheet_id)
        if not title or not isinstance(position, int) or isinstance(position, bool) or position < 0:
            errors.append(f"{field_name}[{index}]: title and non-negative position required")
        if not isinstance(hidden, bool):
            errors.append(f"{field_name}[{index}]: hidden must be boolean")
        if not _is_positive_int(row_count) or not _is_positive_int(column_count):
            errors.append(f"{field_name}[{index}]: positive dimensions required")
        if not used_range or not used_hash:
            errors.append(f"{field_name}[{index}]: used_range and used_range_hash required")
        canonical.append((position, title, hidden, row_count, column_count, used_range, used_hash))
    return canonical


def validate_manifest(manifest: Any) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(manifest, dict):
        return {"ok": False, "errors": ["MANIFEST_TYPE: expected object"], "warnings": []}

    if manifest.get("schema_version") != "1.1":
        errors.append("SCHEMA_VERSION_UNSUPPORTED: expected 1.1")
    mode = manifest.get("mode")
    stage = manifest.get("stage")
    state = manifest.get("state")
    if mode not in {"audit", "execute"}:
        errors.append("MODE_INVALID: mode must be audit or execute")
    if stage not in STAGES:
        errors.append("STAGE_INVALID: stage must be plan, prewrite or postwrite")
    if state not in STATES:
        errors.append("STATE_INVALID")

    brief = manifest.get("brief") if isinstance(manifest.get("brief"), dict) else {}
    batch = manifest.get("batch") if isinstance(manifest.get("batch"), dict) else {}
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    copy_section = manifest.get("copy") if isinstance(manifest.get("copy"), dict) else {}
    pool = manifest.get("pool") if isinstance(manifest.get("pool"), dict) else {}
    headers = manifest.get("headers") if isinstance(manifest.get("headers"), dict) else {}
    history = manifest.get("history") if isinstance(manifest.get("history"), dict) else {}
    transactions = manifest.get("transactions")
    report = manifest.get("report") if isinstance(manifest.get("report"), dict) else {}
    readback = manifest.get("readback") if isinstance(manifest.get("readback"), dict) else {}
    rows = manifest.get("rows") if isinstance(manifest.get("rows"), list) else []
    writes = manifest.get("writes") if isinstance(manifest.get("writes"), list) else []
    pool_candidates = (
        manifest.get("pool_candidates") if isinstance(manifest.get("pool_candidates"), list) else []
    )

    source_token = normalize_text(source.get("token"))
    copy_token = normalize_text(copy_section.get("token"))
    pool_token = normalize_text(pool.get("token"))
    copy_sheet = normalize_text(copy_section.get("target_sheet_id"))
    copy_creator_sheet = normalize_text(copy_section.get("creator_skill_sheet_id"))
    copy_topic_column = normalize_text(copy_section.get("topic_column")).upper()
    pool_sheet = normalize_text(pool.get("sheet_id"))

    if source.get("writes") not in ([], None):
        errors.append("SOURCE_WRITESET_EMPTY: source.writes must be empty")

    audit_built = mode == "audit" and state in {"PLAN_BUILT", "PARTIAL_NEEDS_REVIEW"}
    evidence_required = mode == "execute" or audit_built
    target_header_columns: dict[str, str] = {}
    creator_header_columns: dict[str, str] = {}

    if mode == "audit":
        if writes:
            errors.append("AUDIT_ZERO_WRITES: audit mode requires writes=[]")
        if transactions not in ({}, None):
            errors.append("AUDIT_ZERO_TRANSACTIONS")
        if copy_token or normalize_text(copy_section.get("api_returned_token")):
            errors.append("AUDIT_NO_COPY: audit mode cannot create or reference an execution copy")
        if report.get("action") != "preview" or normalize_text(report.get("token")):
            errors.append("AUDIT_REPORT_PREVIEW_ONLY")
        if stage != "plan" or state not in {
            "DISCOVERED",
            "PLAN_BUILT",
            "PARTIAL_NEEDS_REVIEW",
        }:
            errors.append("AUDIT_STATE_INVALID")
        if state == "DISCOVERED":
            warnings.append("DRAFT_SCAFFOLD_ONLY: fill evidence before treating this as an audit result")

    if evidence_required:
        for name, value in (
            ("BRIEF_URL_REQUIRED", normalize_text(brief.get("url"))),
            ("BRIEF_TITLE_REQUIRED", normalize_text(brief.get("title"))),
            ("SOURCE_URL_REQUIRED", normalize_text(source.get("url"))),
            ("SOURCE_TOKEN_REQUIRED", source_token),
            ("SOURCE_TARGET_SHEET_REQUIRED", normalize_text(source.get("target_sheet_id"))),
            ("SOURCE_CREATOR_SHEET_REQUIRED", normalize_text(source.get("creator_skill_sheet_id"))),
            ("POOL_URL_REQUIRED", normalize_text(pool.get("url"))),
            ("POOL_TOKEN_REQUIRED", pool_token),
            ("POOL_SHEET_REQUIRED", pool_sheet),
        ):
            if not value:
                errors.append(name)
        if not _is_positive_int(brief.get("revision")):
            errors.append("BRIEF_REVISION_REQUIRED")
        if normalize_text(source.get("object_type")) != "sheet":
            errors.append("SOURCE_OBJECT_IS_SPREADSHEET")
        batch_date = normalize_text(batch.get("date"))
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", batch_date):
            errors.append("BATCH_DATE_REQUIRED")
        if normalize_text(batch.get("timezone")) != "Asia/Shanghai":
            errors.append("BATCH_TIMEZONE_ASIA_SHANGHAI")

        target_header_columns = _validate_header_mapping(
            headers.get("target"),
            required_fields=("creator", "homepage", "agency", "status", "topic", "feedback"),
            expected_sheet_id=normalize_text(source.get("target_sheet_id")),
            label="target",
            errors=errors,
        )
        creator_header_columns = _validate_header_mapping(
            headers.get("creator_skill"),
            required_fields=("creator", "homepage", "agency", "status"),
            expected_sheet_id=normalize_text(source.get("creator_skill_sheet_id")),
            label="creator_skill",
            errors=errors,
        )
        if history.get("snapshot_complete") is not True:
            errors.append("HISTORY_SNAPSHOT_COMPLETE")
        history_sources = history.get("sources")
        if not isinstance(history_sources, list) or not history_sources:
            errors.append("HISTORY_SOURCES_REQUIRED")
        else:
            for index, item in enumerate(history_sources):
                if not isinstance(item, dict) or not normalize_text(item.get("url")):
                    errors.append(f"HISTORY_SOURCE_COMPLETE: {index}")
                    continue
                if not _is_positive_int(item.get("revision")):
                    errors.append(f"HISTORY_SOURCE_COMPLETE: {index}")
                if (
                    not isinstance(item.get("rows_scanned"), int)
                    or isinstance(item.get("rows_scanned"), bool)
                    or item.get("rows_scanned") < 0
                    or not re.fullmatch(
                        r"sha256:[0-9a-f]{64}", normalize_text(item.get("content_sha256"))
                    )
                ):
                    errors.append(f"HISTORY_SOURCE_COMPLETE: {index}")

    historical_keys_raw = history.get("duplicate_keys")
    historical_keys = (
        [normalize_text(value) for value in historical_keys_raw]
        if isinstance(historical_keys_raw, list)
        else []
    )
    if evidence_required and (
        not isinstance(historical_keys_raw, list)
        or any(not value for value in historical_keys)
        or len(historical_keys) != len(set(historical_keys))
    ):
        errors.append("HISTORY_DUPLICATE_KEYS_VALID")
    historical_key_set = set(historical_keys)

    if mode == "execute":
        if stage not in {"prewrite", "postwrite"}:
            errors.append("EXECUTE_STAGE_INVALID: execute manifests must be prewrite or postwrite")
        if stage == "prewrite" and state != "PREWRITE_REVALIDATED":
            errors.append("EXECUTE_STATE_INVALID: prewrite must be PREWRITE_REVALIDATED")
        if stage == "postwrite" and state not in {"COMPLETE", "PARTIAL_NEEDS_REVIEW"}:
            errors.append("EXECUTE_STATE_INVALID: postwrite must be COMPLETE or PARTIAL_NEEDS_REVIEW")
        for name, value in (
            ("COPY_TOKEN_REQUIRED", copy_token),
            ("COPY_SHEET_REQUIRED", copy_sheet),
            ("COPY_CREATOR_SHEET_REQUIRED", copy_creator_sheet),
            ("COPY_TOPIC_COLUMN_REQUIRED", copy_topic_column),
        ):
            if not value:
                errors.append(name)
        if normalize_text(copy_section.get("object_type")) != "sheet":
            errors.append("COPY_OBJECT_IS_SPREADSHEET")
        if copy_topic_column != target_header_columns.get("topic"):
            errors.append("COPY_TOPIC_COLUMN_MATCH_HEADER_MAPPING")

    tokens = [token for token in (source_token, copy_token, pool_token) if token]
    if len(tokens) != len(set(tokens)):
        errors.append("RESOURCE_TOKENS_PAIRWISE_DISTINCT")

    # Revision safety and evidence that a native full-workbook copy was used.
    if mode == "execute":
        revision_names = (
            "initial_revision",
            "revision_read",
            "revision_before_copy",
            "revision_after_copy",
            "revision_prewrite",
        )
        for name in revision_names:
            if not _is_positive_int(source.get(name)):
                errors.append(f"SOURCE_REVISION_POSITIVE: {name}")
        latest_revisions = [
            source.get("revision_read"),
            source.get("revision_before_copy"),
            source.get("revision_after_copy"),
            source.get("revision_prewrite"),
        ]
        if len(set(latest_revisions)) != 1:
            errors.append("SOURCE_REVISION_STABLE_OR_REPLAN")
        if source.get("initial_revision") != source.get("revision_read"):
            if not _is_positive_int(source.get("replan_generation")):
                errors.append("REPLAN_GENERATION_REQUIRED")
            if source.get("old_copy_invalidated") is not True:
                errors.append("OLD_COPY_INVALIDATED_REQUIRED")
            remap_rows = _int_set(source.get("remap_evidence", []), "REMAP_EVIDENCE", errors)
            expected_for_remap = _int_set(
                source.get("expected_source_rows", []), "EXPECTED_SOURCE_ROWS_REMAP", errors
            )
            if remap_rows != expected_for_remap:
                errors.append("REMAP_EVIDENCE_COVERAGE")
        if normalize_text(copy_section.get("source_token")) != source_token:
            errors.append("COPY_SOURCE_TOKEN_MATCH")
        if normalize_text(copy_section.get("api_returned_token")) != copy_token:
            errors.append("COPY_RETURNED_ID_USED_DIRECTLY")
        if copy_section.get("source_revision") != source.get("revision_after_copy"):
            errors.append("COPY_SOURCE_REVISION_MATCH")
        if copy_section.get("manifest_verified") is not True:
            errors.append("COPY_MANIFEST_VERIFIED")
    elif audit_built and not _is_positive_int(source.get("revision_read")):
        errors.append("SOURCE_REVISION_READ_REQUIRED")

    source_manifest = _canonical_sheet_manifest(
        source.get("sheet_manifest", []),
        "SOURCE_SHEET_MANIFEST",
        errors,
        required=evidence_required,
    )
    copy_manifest = _canonical_sheet_manifest(
        copy_section.get("sheet_manifest", []),
        "COPY_SHEET_MANIFEST",
        errors,
        required=mode == "execute",
    )
    if mode == "execute" and source_manifest != copy_manifest:
        errors.append("COPY_SHEET_MANIFEST_EQUAL")
    if evidence_required:
        source_items = [item for item in source.get("sheet_manifest", []) if isinstance(item, dict)]
        source_by_id = {normalize_text(item.get("sheet_id")): item for item in source_items}
        source_target_id = normalize_text(source.get("target_sheet_id"))
        source_creator_id = normalize_text(source.get("creator_skill_sheet_id"))
        if source_target_id not in source_by_id:
            errors.append("SOURCE_TARGET_SHEET_IN_MANIFEST")
        if source_creator_id not in source_by_id:
            errors.append("SOURCE_CREATOR_SHEET_IN_MANIFEST")
        if source_target_id == source_creator_id:
            errors.append("TARGET_AND_CREATOR_SHEETS_DISTINCT")

    if mode == "execute":
        source_items = [item for item in source.get("sheet_manifest", []) if isinstance(item, dict)]
        copy_items = [item for item in copy_section.get("sheet_manifest", []) if isinstance(item, dict)]
        source_by_id = {normalize_text(item.get("sheet_id")): item for item in source_items}
        copy_by_id = {normalize_text(item.get("sheet_id")): item for item in copy_items}
        source_target_id = normalize_text(source.get("target_sheet_id"))
        source_creator_id = normalize_text(source.get("creator_skill_sheet_id"))
        if copy_sheet == copy_creator_sheet:
            errors.append("TARGET_AND_CREATOR_SHEETS_DISTINCT")
        if copy_sheet not in copy_by_id or copy_creator_sheet not in copy_by_id:
            errors.append("COPY_TARGET_SHEETS_UNIQUE_AND_PRESENT")
        elif source_target_id in source_by_id and source_creator_id in source_by_id:
            source_target_position = source_by_id[source_target_id].get("position")
            source_creator_position = source_by_id[source_creator_id].get("position")
            copy_target_position = copy_by_id[copy_sheet].get("position")
            copy_creator_position = copy_by_id[copy_creator_sheet].get("position")
            if source_target_position != copy_target_position:
                errors.append("COPY_TARGET_SHEET_MAPPING_MATCH")
            if source_creator_position != copy_creator_position:
                errors.append("COPY_CREATOR_SHEET_MAPPING_MATCH")

    for prefix, section in (("COPY", copy_section), ("POOL", pool)):
        planned = section.get("revision_planned")
        prewrite = section.get("revision_prewrite")
        if mode == "execute":
            if not _is_positive_int(planned) or not _is_positive_int(prewrite):
                errors.append(f"{prefix}_REVISION_POSITIVE")
            if planned != prewrite:
                errors.append(f"{prefix}_REVISION_UNCHANGED_PREWRITE")

    expected_rows = _int_set(source.get("expected_source_rows", []), "EXPECTED_SOURCE_ROWS", errors)
    expected_creator_rows = _int_set(
        source.get("creator_skill_expected_rows", []), "CREATOR_SKILL_EXPECTED_ROWS", errors
    )
    if evidence_required and source.get("creator_skill_scan_complete") is not True:
        errors.append("CREATOR_SHEET_SCAN_COMPLETE")

    actual_rows: set[int] = set()
    row_by_number: dict[int, dict[str, Any]] = {}
    decision_counts = Counter()
    submit_profile_keys: list[str] = []
    submit_duplicate_keys: list[str] = []
    required_reason_fields = ("creator", "profile_key", "fingerprint", "reason_code", "fix_condition", "owner_action")

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"ROW_TYPE: rows[{index}] must be an object")
            continue
        row_number = row.get("row")
        if not _is_positive_int(row_number):
            errors.append(f"ROW_COORDINATE_FROM_ANNOTATION: rows[{index}] has invalid row")
            continue
        if row_number in actual_rows:
            errors.append(f"DECISION_ROW_DUPLICATE: row {row_number}")
        actual_rows.add(row_number)
        row_by_number[row_number] = row
        for field in required_reason_fields:
            if not normalize_text(row.get(field)):
                errors.append(f"ROW_FIELD_REQUIRED: row {row_number} field {field}")
        evidence = row.get("evidence")
        if not isinstance(evidence, list) or not any(normalize_text(item) for item in evidence):
            errors.append(f"ROW_EVIDENCE_REQUIRED: row {row_number}")

        decision = normalize_text(row.get("decision"))
        if decision not in DECISIONS:
            errors.append(f"DECISION_INVALID: row {row_number} has {decision!r}")
            continue
        decision_counts[decision] += 1
        reason_code = normalize_text(row.get("reason_code"))
        if reason_code not in REASON_CODES.get(decision, set()):
            errors.append(f"REASON_CODE_ALLOWED_FOR_DECISION: row {row_number}")
        if not isinstance(row.get("brief_fit"), bool):
            errors.append(f"BRIEF_FIT_BOOLEAN_REQUIRED: row {row_number}")
        if not isinstance(row.get("protection_block"), bool):
            errors.append(f"PROTECTION_BLOCK_BOOLEAN_REQUIRED: row {row_number}")

        historical_match = (
            row.get("historical_match") if isinstance(row.get("historical_match"), dict) else {}
        )
        match_status = normalize_text(historical_match.get("status"))
        matched_keys_raw = historical_match.get("matched_duplicate_keys")
        matched_keys = (
            [normalize_text(value) for value in matched_keys_raw]
            if isinstance(matched_keys_raw, list)
            else []
        )
        if match_status not in HISTORICAL_MATCH_STATUSES:
            errors.append(f"HISTORICAL_MATCH_STATUS_REQUIRED: row {row_number}")
        if (
            not isinstance(matched_keys_raw, list)
            or any(not value for value in matched_keys)
            or not set(matched_keys).issubset(historical_key_set)
        ):
            errors.append(f"HISTORICAL_MATCH_KEYS_VALID: row {row_number}")

        if decision == "SUBMIT":
            pc_hits = row.get("pc_hits")
            if not isinstance(pc_hits, list) or len(set(pc_hits) & {"PC-1", "PC-2", "PC-3"}) < 2:
                errors.append(f"PC_HITS_AT_LEAST_TWO: row {row_number}")
            for field in ("main_skill", "core_task", "key_input", "final_artifact", "lifecycle"):
                if not normalize_text(row.get(field)):
                    errors.append(f"SUBMIT_FIELD_REQUIRED: row {row_number} field {field}")
            try:
                expected_duplicate_key = topic_key(
                    row.get("main_skill"),
                    row.get("core_task"),
                    row.get("key_input"),
                    row.get("final_artifact"),
                    row.get("lifecycle"),
                )
                if normalize_text(row.get("duplicate_key")) != expected_duplicate_key:
                    errors.append(f"DUPLICATE_KEY_MATCH: row {row_number}")
                if expected_duplicate_key in historical_key_set or match_status == "exact":
                    errors.append(f"SUBMIT_NOT_HISTORICAL_EXACT_DUPLICATE: row {row_number}")
                submit_duplicate_keys.append(expected_duplicate_key)
            except ValueError as error:
                errors.append(f"row {row_number}: {error}")
            topic_result = validate_topic(row.get("topic", ""))
            errors.extend(f"row {row_number}: {error}" for error in topic_result["errors"])
            warnings.extend(f"row {row_number}: {warning}" for warning in topic_result["warnings"])
            submit_profile_keys.append(normalize_text(row.get("profile_key")))
            if row.get("brief_fit") is not True or row.get("protection_block") is not False:
                errors.append(f"SUBMIT_POLICY_GATES_PASS: row {row_number}")
        elif decision == "BUSINESS_BLOCK":
            block_evidence = (
                row.get("block_evidence") if isinstance(row.get("block_evidence"), dict) else {}
            )
            if row.get("protection_block") is not True or not all(
                normalize_text(block_evidence.get(field)) for field in ("source", "value")
            ):
                errors.append(f"BUSINESS_BLOCK_EVIDENCE_REQUIRED: row {row_number}")
            if reason_code == "CURRENT_STATUS_NO" and normalize_text(
                block_evidence.get("value")
            ) != "否":
                errors.append(f"BUSINESS_BLOCK_STATUS_EXACT: row {row_number}")
        elif decision == "NEEDS_EVIDENCE":
            evidence_gap = (
                row.get("evidence_gap") if isinstance(row.get("evidence_gap"), dict) else {}
            )
            if row.get("protection_block") is not False or not all(
                normalize_text(evidence_gap.get(field))
                for field in ("missing", "needed", "next_action")
            ):
                errors.append(f"NEEDS_EVIDENCE_GAP_REQUIRED: row {row_number}")
        elif decision == "RETOPIC":
            attempts = row.get("retopic_attempts")
            if row.get("protection_block") is not False or not isinstance(attempts, list) or not attempts:
                errors.append(f"RETOPIC_ATTEMPT_REQUIRED: row {row_number}")
            elif any(
                not isinstance(attempt, dict)
                or not all(
                    normalize_text(attempt.get(field))
                    for field in ("core_task", "final_artifact", "failure_reason")
                )
                for attempt in attempts
            ):
                errors.append(f"RETOPIC_ATTEMPT_COMPLETE: row {row_number}")
            if reason_code == "EXACT_TOPIC_DUPLICATE" and match_status != "exact":
                errors.append(f"RETOPIC_EXACT_DUPLICATE_EVIDENCE: row {row_number}")
        elif decision == "ANOMALY":
            anomaly_detail = (
                row.get("anomaly_detail") if isinstance(row.get("anomaly_detail"), dict) else {}
            )
            if not all(
                normalize_text(anomaly_detail.get(field)) for field in ("observed", "next_action")
            ):
                errors.append(f"ANOMALY_DETAIL_REQUIRED: row {row_number}")

    if expected_rows != actual_rows:
        errors.append(
            f"DECISION_COVERAGE_EXACT: missing={sorted(expected_rows - actual_rows)}, "
            f"extra={sorted(actual_rows - expected_rows)}"
        )
    for duplicate in sorted(_duplicates(submit_profile_keys)):
        errors.append(f"SUBMIT_PROFILE_DUPLICATE: {duplicate}")
    for duplicate in sorted(_duplicates(submit_duplicate_keys)):
        errors.append(f"SUBMIT_TOPIC_DUPLICATE_IN_BATCH: {duplicate}")

    expected_report_rows = sorted(
        (
            _report_row(row)
            for row in row_by_number.values()
            if normalize_text(row.get("decision")) in DECISIONS - {"SUBMIT"}
        ),
        key=lambda item: item["row_key"],
    )
    raw_report_expected = report.get("expected_rows")
    report_expected = (
        sorted(raw_report_expected, key=lambda item: normalize_text(item.get("row_key")))
        if isinstance(raw_report_expected, list)
        and all(isinstance(item, dict) for item in raw_report_expected)
        else []
    )
    if evidence_required and report_expected != expected_report_rows:
        errors.append("REPORT_EXPECTED_ROW_COVERAGE_AND_HASH")
    if evidence_required and not normalize_text(report.get("title")):
        errors.append("REPORT_TITLE_REQUIRED")

    raw_report_actual = report.get("actual_rows")
    report_actual = (
        sorted(raw_report_actual, key=lambda item: normalize_text(item.get("row_key")))
        if isinstance(raw_report_actual, list)
        and all(isinstance(item, dict) for item in raw_report_actual)
        else []
    )
    actual_row_keys = [normalize_text(item.get("row_key")) for item in report_actual]
    if any(not key for key in actual_row_keys) or _duplicates(actual_row_keys):
        errors.append("REPORT_ACTUAL_ROW_KEYS_UNIQUE")
    if audit_built:
        if report_actual != expected_report_rows:
            errors.append("AUDIT_PREVIEW_ROW_COVERAGE")
        if report.get("preview_verified") is not True:
            errors.append("AUDIT_PREVIEW_VERIFIED")
        if normalize_text(report.get("actual_document_sha256")) != normalize_text(
            report.get("expected_document_sha256")
        ) or not normalize_text(report.get("expected_document_sha256")):
            errors.append("AUDIT_PREVIEW_DOCUMENT_HASH_MATCH")

    # Pool header mapping and prewrite snapshot must be complete.
    field_columns_raw = pool.get("field_columns")
    field_columns = field_columns_raw if isinstance(field_columns_raw, dict) else {}
    pool_field_raw_by_normalized = {normalize_text(field): field for field in POOL_FIELDS}
    pool_fields_normalized = set(pool_field_raw_by_normalized)
    first_seen_normalized = {normalize_text(field) for field in POOL_FIRST_SEEN_FIELDS}
    normalized_field_columns = {
        normalize_text(field): normalize_text(column).upper()
        for field, column in field_columns.items()
        if normalize_text(field)
    }
    allowed_pool_columns = {
        normalize_text(value).upper() for value in pool.get("allowed_columns", []) if normalize_text(value)
    }
    if evidence_required:
        if set(normalized_field_columns) != pool_fields_normalized:
            errors.append("POOL_FIELD_MAPPING_COMPLETE")
        mapped_columns = list(normalized_field_columns.values())
        if any(not column for column in mapped_columns) or len(mapped_columns) != len(set(mapped_columns)):
            errors.append("POOL_FIELD_COLUMNS_UNIQUE")
        if allowed_pool_columns != set(mapped_columns) or not allowed_pool_columns:
            errors.append("POOL_COLUMN_ALLOWLIST_EXACT")
        if pool.get("snapshot_complete") is not True:
            errors.append("POOL_SNAPSHOT_COMPLETE")
        if audit_built and not _is_positive_int(pool.get("revision_planned")):
            errors.append("POOL_REVISION_READ_REQUIRED")

    snapshot_rows = pool.get("snapshot_rows") if isinstance(pool.get("snapshot_rows"), list) else []
    snapshot_by_key: dict[str, dict[str, Any]] = {}
    snapshot_row_numbers: set[int] = set()
    for index, snapshot in enumerate(snapshot_rows):
        if not isinstance(snapshot, dict):
            errors.append(f"POOL_SNAPSHOT_ROW_TYPE: {index}")
            continue
        key = normalize_text(snapshot.get("profile_key"))
        row_number = snapshot.get("row")
        fingerprint = normalize_text(snapshot.get("fingerprint"))
        first_seen = snapshot.get("first_seen")
        if not key or key in snapshot_by_key:
            errors.append(f"POOL_KEYS_UNIQUE_PREWRITE: {key!r}")
        if not _is_positive_int(row_number) or row_number <= 1 or row_number in snapshot_row_numbers:
            errors.append(f"POOL_SNAPSHOT_ROW_UNIQUE: {row_number!r}")
        if not fingerprint:
            errors.append(f"POOL_SNAPSHOT_FINGERPRINT_REQUIRED: {key!r}")
        if not isinstance(first_seen, dict) or any(
            field not in first_seen for field in POOL_FIRST_SEEN_FIELDS
        ):
            errors.append(f"POOL_SNAPSHOT_FIRST_SEEN_REQUIRED: {key!r}")
        snapshot_by_key[key] = snapshot
        if isinstance(row_number, int):
            snapshot_row_numbers.add(row_number)

    existing_keys = [normalize_text(value) for value in pool.get("existing_keys", [])]
    if set(existing_keys) != set(snapshot_by_key) or len(existing_keys) != len(set(existing_keys)):
        errors.append("POOL_EXISTING_KEYS_MATCH_SNAPSHOT")

    # Validate writes first, then bind them to rows/candidates below.
    seen_addresses: set[str] = set()
    copy_writes_by_row: dict[int, list[dict[str, Any]]] = {}
    pool_writes_by_key: dict[str, list[dict[str, Any]]] = {}
    for index, write in enumerate(writes):
        if not isinstance(write, dict):
            errors.append(f"WRITE_TYPE: writes[{index}] must be an object")
            continue
        target = normalize_text(write.get("target"))
        token = normalize_text(write.get("token"))
        sheet_id = normalize_text(write.get("sheet_id"))
        row_number = write.get("row")
        column = normalize_text(write.get("column")).upper()
        action = normalize_text(write.get("action"))
        if target not in {"copy", "pool"}:
            errors.append(f"WRITE_TARGET_INVALID: writes[{index}] target={target!r}")
        if not _is_positive_int(row_number) or not column:
            errors.append(f"WRITE_ADDRESS_INVALID: writes[{index}]")
            continue
        if action != "set" or write.get("value") in (None, ""):
            errors.append(f"STANDARD_WORKFLOW_SET_ONLY: writes[{index}]")
        address = _write_address(write)
        if address in seen_addresses:
            errors.append(f"NO_DUPLICATE_CELL_ADDRESSES: {address}")
        seen_addresses.add(address)

        if target == "copy":
            if token != copy_token or sheet_id != copy_sheet or column != copy_topic_column:
                errors.append(f"WRITESET_SHEET_COLUMN_ALLOWLIST: copy write {index}")
            if row_number not in row_by_number:
                errors.append(f"COPY_WRITE_ROW_IN_DECISIONS: row {row_number}")
            else:
                expected = normalize_text(row_by_number[row_number].get("fingerprint"))
                if normalize_text(write.get("expected_fingerprint")) != expected:
                    errors.append(f"ROW_FINGERPRINT_MATCHES_PREWRITE: row {row_number}")
            if not normalize_text(write.get("prewrite_value_hash")):
                errors.append(f"PREWRITE_VALUE_HASH_REQUIRED: copy write {index}")
            copy_writes_by_row.setdefault(row_number, []).append(write)
        elif target == "pool":
            logical_field = normalize_text(write.get("logical_field"))
            candidate_key = normalize_text(write.get("candidate_key"))
            if token != pool_token or sheet_id != pool_sheet or row_number <= 1:
                errors.append(f"WRITESET_SHEET_COLUMN_ALLOWLIST: pool write {index}")
            if logical_field not in normalized_field_columns:
                errors.append(f"POOL_LOGICAL_FIELD_REQUIRED: pool write {index}")
            elif normalized_field_columns[logical_field] != column:
                errors.append(f"POOL_COLUMN_MAPPING_MATCH: pool write {index}")
            if column not in allowed_pool_columns:
                errors.append(f"POOL_COLUMN_ALLOWLIST: pool write {index} column {column}")
            if not candidate_key:
                errors.append(f"POOL_CANDIDATE_KEY_REQUIRED: pool write {index}")
            if not normalize_text(write.get("expected_fingerprint")):
                errors.append(f"POOL_WRITE_FINGERPRINT_REQUIRED: pool write {index}")
            pool_writes_by_key.setdefault(candidate_key, []).append(write)

    if mode == "execute":
        _validate_transactions(
            transactions,
            writes,
            stage=stage,
            state=state,
            source_token=source_token,
            copy_token=copy_token,
            pool_token=pool_token,
            errors=errors,
        )

    for row_number, row in row_by_number.items():
        row_writes = copy_writes_by_row.get(row_number, [])
        if mode == "execute" and normalize_text(row.get("decision")) == "SUBMIT":
            if len(row_writes) != 1:
                errors.append(f"SUBMIT_WRITE_EXACTLY_ONE: row {row_number}")
            elif normalize_text(row_writes[0].get("value")) != normalize_text(row.get("topic")):
                errors.append(f"SUBMIT_WRITE_VALUE_MATCH: row {row_number}")
        elif mode == "execute" and row_writes:
            errors.append(f"NON_SUBMIT_HAS_WRITE: row {row_number}")

    # Full creator-sheet scan and candidate-to-pool-writes bijection.
    candidate_source_rows: set[int] = set()
    action_candidate_keys: list[str] = []
    pool_action_counts = Counter()
    pending_detected = 0
    candidate_by_key: dict[str, dict[str, Any]] = {}
    max_snapshot_row = max(snapshot_row_numbers, default=1)
    candidate_source_revision = (
        source.get("revision_prewrite") if mode == "execute" else source.get("revision_read")
    )
    source_creator_sheet_id = normalize_text(source.get("creator_skill_sheet_id"))
    source_url = normalize_text(source.get("url"))

    for index, candidate in enumerate(pool_candidates):
        if not isinstance(candidate, dict):
            errors.append(f"POOL_CANDIDATE_TYPE: pool_candidates[{index}]")
            continue
        source_row = candidate.get("source_row")
        if not _is_positive_int(source_row) or source_row in candidate_source_rows:
            errors.append(f"POOL_SOURCE_ROW_UNIQUE: pool candidate {index}")
        if isinstance(source_row, int):
            candidate_source_rows.add(source_row)

        source_snapshot = (
            candidate.get("source_snapshot")
            if isinstance(candidate.get("source_snapshot"), dict)
            else {}
        )
        if evidence_required:
            required_snapshot_fields = (
                "creator",
                "raw_homepage",
                "platform",
                "agency",
                "raw_status",
                "source_sheet_id",
                "source_sheet_title",
                "source_row",
                "source_revision",
                "source_url",
                "status_header",
                "status_column",
            )
            if any(field not in source_snapshot for field in required_snapshot_fields):
                errors.append(f"POOL_SOURCE_SNAPSHOT_COMPLETE: pool candidate {index}")
            if source_snapshot.get("source_row") != source_row:
                errors.append(f"POOL_SOURCE_ROW_MATCH_SNAPSHOT: pool candidate {index}")
            if normalize_text(source_snapshot.get("source_sheet_id")) != source_creator_sheet_id:
                errors.append(f"POOL_SOURCE_SHEET_MATCH: pool candidate {index}")
            if source_snapshot.get("source_revision") != candidate_source_revision:
                errors.append(f"POOL_SOURCE_REVISION_MATCH: pool candidate {index}")
            if normalize_text(source_snapshot.get("source_url")) != source_url:
                errors.append(f"POOL_SOURCE_URL_MATCH: pool candidate {index}")
            creator_status_entry = (
                headers.get("creator_skill", {}).get("status", {})
                if isinstance(headers.get("creator_skill"), dict)
                else {}
            )
            if (
                normalize_text(source_snapshot.get("status_header"))
                != normalize_text(creator_status_entry.get("header"))
                or normalize_text(source_snapshot.get("status_column")).upper()
                != creator_header_columns.get("status")
            ):
                errors.append(f"PENDING_STATUS_COLUMN_BOUND_TO_HEADER: pool candidate {index}")
            if normalize_text(candidate.get("source_fingerprint")) != _source_snapshot_fingerprint(
                source_snapshot
            ):
                errors.append(f"POOL_SOURCE_FINGERPRINT_MATCH: pool candidate {index}")
        if not isinstance(candidate.get("selected"), bool):
            errors.append(f"PENDING_SELECTED_BOOLEAN: pool candidate {index}")
            selected = False
        else:
            selected = candidate["selected"]
        if evidence_required and "raw_status_prewrite" not in candidate:
            errors.append(f"PENDING_PREWRITE_STATUS_REQUIRED: pool candidate {index}")
        raw_status = candidate.get("raw_status_prewrite", candidate.get("raw_status"))
        if raw_status is not None and not isinstance(raw_status, str):
            errors.append(f"PENDING_RAW_STATUS_TYPE: pool candidate {index}")
        if evidence_required and normalize_text(raw_status) != normalize_text(
            source_snapshot.get("raw_status")
        ):
            errors.append(f"PENDING_STATUS_MATCH_SOURCE_SNAPSHOT: pool candidate {index}")
        exact = is_exact_pending(raw_status)
        if selected != exact:
            errors.append(f"PENDING_FILTER_EXACT_ONLY: pool candidate {index}")
        action = normalize_text(candidate.get("sync_action"))
        if selected:
            pending_detected += 1
            if action not in POOL_ACTIONS:
                errors.append(f"PENDING_ACTION_EXACTLY_ONE: pool candidate {index}")
            else:
                pool_action_counts[action] += 1
        elif action:
            errors.append(f"NON_PENDING_HAS_ACTION: pool candidate {index}")
            continue
        if not selected:
            continue

        key = normalize_text(candidate.get("profile_key"))
        key_kind = normalize_text(candidate.get("key_kind"))
        if evidence_required and source_snapshot:
            try:
                normalized_identity = normalize_profile(
                    source_snapshot.get("raw_homepage"),
                    source_snapshot.get("platform"),
                    source_snapshot.get("creator"),
                    source_snapshot.get("agency"),
                )
                if key != normalize_text(normalized_identity.get("key")):
                    errors.append(f"PROFILE_KEY_MATCH_SOURCE: pool candidate {index}")
                if key_kind != normalize_text(normalized_identity.get("kind")):
                    errors.append(f"PROFILE_KIND_MATCH_SOURCE: pool candidate {index}")
                if candidate.get("auto_merge") is not normalized_identity.get("auto_merge"):
                    errors.append(f"PROFILE_AUTO_MERGE_MATCH_SOURCE: pool candidate {index}")
                if candidate.get("same_batch_dedupe") is not normalized_identity.get(
                    "same_batch_dedupe"
                ):
                    errors.append(f"PROFILE_SAME_BATCH_MATCH_SOURCE: pool candidate {index}")
            except ValueError:
                errors.append(f"PROFILE_KEY_DERIVABLE_FROM_SOURCE: pool candidate {index}")
        if action in {"insert", "update", "noop"} and not key:
            errors.append(f"PROFILE_KEY_REQUIRED: pool candidate {index}")
        if key_kind not in {"profile_url", "fallback", "ambiguous"}:
            errors.append(f"PROFILE_KEY_KIND_REQUIRED: pool candidate {index}")
        if action in {"insert", "update", "noop"}:
            action_candidate_keys.append(key)
            candidate_by_key[key] = candidate
        if key_kind == "ambiguous" and action != "anomaly":
            errors.append(f"AMBIGUOUS_KEY_MUST_BE_ANOMALY: pool candidate {index}")
        if key_kind == "fallback" and action in {"update", "noop"}:
            identity_evidence = candidate.get("identity_evidence")
            valid_identity_evidence = False
            if isinstance(identity_evidence, list):
                for item in identity_evidence:
                    if not isinstance(item, dict):
                        continue
                    evidence_type = normalize_text(item.get("type"))
                    if evidence_type == "manual_identity_confirmation" and all(
                        normalize_text(item.get(field))
                        for field in ("confirmed_by", "evidence_url", "note")
                    ):
                        valid_identity_evidence = True
                    if evidence_type == "same_source_record":
                        pool_snapshot = snapshot_by_key.get(key, {})
                        latest_source = (
                            pool_snapshot.get("latest_source")
                            if isinstance(pool_snapshot.get("latest_source"), dict)
                            else {}
                        )
                        valid_identity_evidence = valid_identity_evidence or (
                            normalize_text(item.get("source_url")) == source_url
                            and normalize_text(item.get("source_sheet_id"))
                            == source_creator_sheet_id
                            and item.get("source_row") == source_row
                            and normalize_text(latest_source.get("source_url")) == source_url
                            and normalize_text(latest_source.get("source_sheet_id"))
                            == source_creator_sheet_id
                            and latest_source.get("source_row") == source_row
                        )
            if not valid_identity_evidence:
                errors.append(f"FALLBACK_CROSS_DATE_MERGE_BLOCKED: pool candidate {index}")

        target_row = candidate.get("target_row")
        expected_fingerprint = normalize_text(candidate.get("expected_fingerprint"))
        values = candidate.get("values") if isinstance(candidate.get("values"), dict) else {}
        changed_fields_raw = candidate.get("changed_fields")
        changed_fields = (
            [normalize_text(field) for field in changed_fields_raw]
            if isinstance(changed_fields_raw, list)
            else []
        )
        if action in {"insert", "update", "noop"}:
            if set(values) != set(POOL_FIELDS):
                errors.append(f"POOL_VALUES_COMPLETE: pool candidate {index}")
            if any(not normalize_text(values.get(field)) for field in POOL_CORE_FIELDS):
                errors.append(f"POOL_CORE_VALUES_NONEMPTY: pool candidate {index}")
            if normalize_text(values.get("主页去重键")) != key:
                errors.append(f"POOL_VALUE_PROFILE_KEY_MATCH: pool candidate {index}")
            if evidence_required:
                source_value_pairs = (
                    ("达人名称", "creator"),
                    ("主页链接", "raw_homepage"),
                    ("平台", "platform"),
                    ("机构名", "agency"),
                    ("原是否合作", "raw_status"),
                    ("源表链接", "source_url"),
                )
                for pool_field, source_field in source_value_pairs:
                    if normalize_text(values.get(pool_field)) != normalize_text(
                        source_snapshot.get(source_field)
                    ):
                        errors.append(
                            f"POOL_VALUE_MATCH_SOURCE: pool candidate {index} field {pool_field}"
                        )
                if normalize_text(values.get("当前状态")) != "待定":
                    errors.append(f"POOL_CURRENT_STATUS_PENDING: pool candidate {index}")
                if normalize_text(values.get("最近源行号")) != str(source_row):
                    errors.append(f"POOL_LATEST_SOURCE_ROW_MATCH: pool candidate {index}")
                if normalize_text(values.get("最近来源工作表")) != normalize_text(
                    source_snapshot.get("source_sheet_title")
                ):
                    errors.append(f"POOL_LATEST_SOURCE_SHEET_MATCH: pool candidate {index}")
                if normalize_text(values.get("最近同步日期")) != normalize_text(
                    batch.get("date")
                ):
                    errors.append(f"POOL_LATEST_SYNC_DATE_MATCH: pool candidate {index}")
            if len(changed_fields) != len(set(changed_fields)) or any(
                field not in pool_fields_normalized for field in changed_fields
            ):
                errors.append(f"POOL_CHANGED_FIELDS_VALID: pool candidate {index}")

        if action == "insert":
            if key in snapshot_by_key:
                errors.append(f"POOL_INSERT_KEY_MUST_NOT_EXIST: {key}")
            if not _is_positive_int(target_row) or target_row <= max_snapshot_row:
                errors.append(f"POOL_INSERT_APPEND_ROW: pool candidate {index}")
            if expected_fingerprint != f"EMPTY_ROW:{target_row}":
                errors.append(f"POOL_INSERT_EMPTY_FINGERPRINT: pool candidate {index}")
            expected_changed = {
                normalize_text(field) for field, value in values.items() if normalize_text(value)
            }
            if set(changed_fields) != expected_changed:
                errors.append(f"POOL_INSERT_ALL_NONEMPTY_FIELDS: pool candidate {index}")
            if (
                normalize_text(values.get("首次来源工作表"))
                != normalize_text(source_snapshot.get("source_sheet_title"))
                or normalize_text(values.get("首次源行号")) != str(source_row)
                or normalize_text(values.get("首次收录日期"))
                != normalize_text(batch.get("date"))
            ):
                errors.append(f"POOL_INSERT_FIRST_SOURCE_MATCH: pool candidate {index}")
        elif action in {"update", "noop"}:
            snapshot = snapshot_by_key.get(key)
            if snapshot is None:
                errors.append(f"POOL_EXISTING_ACTION_KEY_MUST_EXIST: {key}")
            else:
                if target_row != snapshot.get("row"):
                    errors.append(f"POOL_TARGET_ROW_MATCH: {key}")
                if expected_fingerprint != normalize_text(snapshot.get("fingerprint")):
                    errors.append(f"POOL_FINGERPRINT_MATCH: {key}")
                existing_values = (
                    candidate.get("existing_values")
                    if isinstance(candidate.get("existing_values"), dict)
                    else {}
                )
                for field in POOL_FIRST_SEEN_FIELDS:
                    if field not in existing_values or normalize_text(existing_values.get(field)) != normalize_text(
                        values.get(field)
                    ):
                        errors.append(f"FIRST_SEEN_FIELDS_IMMUTABLE: {key} field {field}")
            if action == "update":
                if not changed_fields or set(changed_fields) & first_seen_normalized:
                    errors.append(f"POOL_UPDATE_FIELDS_VALID: {key}")
            elif changed_fields:
                errors.append(f"POOL_NOOP_HAS_CHANGED_FIELDS: {key}")
        elif action == "anomaly":
            if pool_writes_by_key.get(key):
                errors.append(f"POOL_ANOMALY_HAS_WRITE: {key}")

        if mode == "execute" and action in {"insert", "update"}:
            actual_pool_writes = pool_writes_by_key.get(key, [])
            actual_fields = {normalize_text(write.get("logical_field")) for write in actual_pool_writes}
            if actual_fields != set(changed_fields) or len(actual_pool_writes) != len(changed_fields):
                errors.append(f"POOL_WRITES_MATCH_CHANGED_FIELDS: {key}")
            for write in actual_pool_writes:
                field = normalize_text(write.get("logical_field"))
                if write.get("row") != target_row:
                    errors.append(f"POOL_WRITE_TARGET_ROW_MATCH: {key} field {field}")
                if normalize_text(write.get("expected_fingerprint")) != expected_fingerprint:
                    errors.append(f"POOL_WRITE_FINGERPRINT_MATCH: {key} field {field}")
                raw_field = pool_field_raw_by_normalized.get(field, field)
                if normalize_text(write.get("value")) != normalize_text(values.get(raw_field)):
                    errors.append(f"POOL_WRITE_VALUE_MATCH: {key} field {field}")
        if mode == "execute" and action in {"noop", "anomaly"} and pool_writes_by_key.get(key):
            errors.append(f"POOL_NOOP_OR_ANOMALY_ZERO_WRITES: {key}")

    if expected_creator_rows != candidate_source_rows:
        errors.append(
            f"CREATOR_SHEET_SCAN_COVERAGE: missing={sorted(expected_creator_rows - candidate_source_rows)}, "
            f"extra={sorted(candidate_source_rows - expected_creator_rows)}"
        )
    for duplicate in sorted(_duplicates(action_candidate_keys)):
        errors.append(f"POOL_CANDIDATE_KEYS_UNIQUE: {duplicate}")
    for orphan_key in sorted(set(pool_writes_by_key) - set(candidate_by_key)):
        errors.append(f"POOL_WRITE_HAS_NO_CANDIDATE: {orphan_key}")

    required_count_names = (
        "decision_total",
        "submit",
        "business_block",
        "needs_evidence",
        "retopic",
        "anomaly",
        "pending_detected",
        "inserted",
        "updated",
        "noop_existing",
        "rejected_anomaly",
        "writes_planned",
        "writes_succeeded",
        "writes_failed",
        "writes_skipped",
    )
    counts = manifest.get("counts") if isinstance(manifest.get("counts"), dict) else {}
    if set(required_count_names) - set(counts):
        errors.append(
            f"COUNTS_COMPLETE: missing={sorted(set(required_count_names) - set(counts))}"
        )
    succeeded = sum(write.get("succeeded") is True for write in writes)
    failed = sum(
        write.get("succeeded") is False
        and write.get("skipped_due_to_prior_failure") is not True
        for write in writes
    )
    skipped = sum(write.get("skipped_due_to_prior_failure") is True for write in writes)
    expected_count_values = {
        "decision_total": len(rows),
        "submit": decision_counts["SUBMIT"],
        "business_block": decision_counts["BUSINESS_BLOCK"],
        "needs_evidence": decision_counts["NEEDS_EVIDENCE"],
        "retopic": decision_counts["RETOPIC"],
        "anomaly": decision_counts["ANOMALY"],
        "pending_detected": pending_detected,
        "inserted": pool_action_counts["insert"],
        "updated": pool_action_counts["update"],
        "noop_existing": pool_action_counts["noop"],
        "rejected_anomaly": pool_action_counts["anomaly"],
        "writes_planned": len(writes),
        "writes_succeeded": succeeded if stage == "postwrite" else 0,
        "writes_failed": failed if stage == "postwrite" else 0,
        "writes_skipped": skipped if stage == "postwrite" else 0,
    }
    for name, expected in expected_count_values.items():
        if counts.get(name) != expected:
            errors.append(
                f"ACCOUNTING_EQUATIONS_BALANCED: {name}={counts.get(name)!r}, expected {expected}"
            )

    if stage == "postwrite" and mode == "execute":
        for prefix, section in (("COPY", copy_section), ("POOL", pool)):
            if not _is_positive_int(section.get("revision_postwrite")):
                errors.append(f"{prefix}_POSTWRITE_REVISION_REQUIRED")
        for index, write in enumerate(writes):
            skipped_write = write.get("skipped_due_to_prior_failure") is True
            if skipped_write:
                if write.get("succeeded") is not None:
                    errors.append(f"WRITE_RECEIPT_STATE_EXCLUSIVE: {index}")
                if write.get("skipped_unmodified_verified") is not True:
                    errors.append(f"SKIPPED_WRITE_UNMODIFIED_VERIFIED: {index}")
            else:
                if not isinstance(write.get("succeeded"), bool):
                    errors.append(f"WRITE_RECEIPT_REQUIRED: {index}")
                if write.get("succeeded") is True and write.get("readback_matches") is not True:
                    errors.append(f"READBACK_EXACT_FOR_EVERY_OP: {index}")
                if write.get("succeeded") is False and write.get("readback_matches") is not False:
                    errors.append(f"FAILED_WRITE_READBACK_RECORDED: {index}")

        copy_phase_failed = any(
            normalize_text(write.get("target")) == "copy"
            and (
                write.get("succeeded") is False
                or write.get("skipped_due_to_prior_failure") is True
            )
            for write in writes
        )
        if copy_phase_failed and any(
            normalize_text(write.get("target")) == "pool"
            and write.get("skipped_due_to_prior_failure") is not True
            for write in writes
        ):
            errors.append("POOL_PHASE_SKIPPED_AFTER_COPY_FAILURE")
        if (failed or skipped) and state != "PARTIAL_NEEDS_REVIEW":
            errors.append("FAILED_OR_SKIPPED_WRITES_REQUIRE_PARTIAL_STATE")
        if not failed and not skipped and state != "COMPLETE":
            errors.append("ALL_WRITES_VERIFIED_REQUIRE_COMPLETE_STATE")
        copy_addresses = readback.get("copy_addresses")
        pool_addresses = readback.get("pool_addresses")
        expected_copy_addresses = sorted(
            _write_address(write) for write in writes if normalize_text(write.get("target")) == "copy"
        )
        expected_pool_addresses = sorted(
            _write_address(write) for write in writes if normalize_text(write.get("target")) == "pool"
        )
        if sorted(copy_addresses or []) != expected_copy_addresses:
            errors.append("COPY_READBACK_ADDRESS_COVERAGE")
        if sorted(pool_addresses or []) != expected_pool_addresses:
            errors.append("POOL_READBACK_ADDRESS_COVERAGE")
        postwrite_keys = [normalize_text(value) for value in pool.get("postwrite_keys", [])]
        if any(not value for value in postwrite_keys) or _duplicates(postwrite_keys):
            errors.append("POOL_KEYS_UNIQUE_POSTWRITE")
        expected_postwrite_rows = {
            key: snapshot.get("row") for key, snapshot in snapshot_by_key.items()
        }
        for key, candidate in candidate_by_key.items():
            if normalize_text(candidate.get("sync_action")) != "insert":
                continue
            candidate_writes = pool_writes_by_key.get(key, [])
            if candidate_writes and all(write.get("succeeded") is True for write in candidate_writes):
                expected_postwrite_rows[key] = candidate.get("target_row")
        if set(postwrite_keys) != set(expected_postwrite_rows):
            errors.append("POOL_POSTWRITE_KEYS_EXACT")
        raw_postwrite_rows = pool.get("postwrite_key_rows")
        postwrite_rows = raw_postwrite_rows if isinstance(raw_postwrite_rows, dict) else {}
        normalized_postwrite_rows = {
            normalize_text(key): row for key, row in postwrite_rows.items() if normalize_text(key)
        }
        if normalized_postwrite_rows != expected_postwrite_rows:
            errors.append("POOL_POSTWRITE_KEY_ROWS_EXACT")
        if state == "COMPLETE":
            if report.get("action") != "create" or not normalize_text(report.get("token")):
                errors.append("REPORT_CREATED")
            if not _is_positive_int(report.get("revision_postcreate")):
                errors.append("REPORT_POSTCREATE_REVISION_REQUIRED")
            if normalize_text(report.get("title_readback")) != normalize_text(
                report.get("title")
            ):
                errors.append("REPORT_TITLE_READBACK_MATCH")
            if report_actual != expected_report_rows:
                errors.append("REPORT_ACTUAL_ROW_COVERAGE_AND_HASH")
            expected_document_hash = normalize_text(report.get("expected_document_sha256"))
            if (
                not expected_document_hash
                or normalize_text(report.get("actual_document_sha256"))
                != expected_document_hash
            ):
                errors.append("REPORT_DOCUMENT_HASH_MATCH")
            if report.get("readback_verified") is not True:
                errors.append("REPORT_READBACK_VERIFIED")
            if failed:
                errors.append("COMPLETE_WITH_FAILED_WRITES")
        else:
            if (
                report.get("action") != "defer"
                or normalize_text(report.get("token"))
                or report.get("revision_postcreate") is not None
                or report_actual
                or report.get("readback_verified") is not False
            ):
                errors.append("PARTIAL_REPORT_DEFERRED")
    elif mode == "execute":
        if (
            report.get("action") != "create"
            or normalize_text(report.get("token"))
            or report.get("revision_postcreate") is not None
            or report_actual
            or report.get("readback_verified") is not False
            or not normalize_text(report.get("expected_document_sha256"))
        ):
            errors.append("PREWRITE_REPORT_INTENT")

    if state == "PARTIAL_NEEDS_REVIEW":
        errors.append("PARTIAL_REQUIRES_REVIEW: never treat a partial manifest as executable or complete")

    return {
        "ok": not errors,
        "safe_to_execute": (
            mode == "execute"
            and stage == "prewrite"
            and state == "PREWRITE_REVALIDATED"
            and not errors
        ),
        "complete": mode == "execute" and stage == "postwrite" and state == "COMPLETE" and not errors,
        "errors": errors,
        "warnings": warnings,
        "computed_counts": expected_count_values,
    }


def _load_json(path: str) -> Any:
    with Path(path).expanduser().open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_text(path: str) -> str:
    return Path(path).expanduser().read_text(encoding="utf-8")


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def derive_plan_evidence(manifest: Any) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")
    source_fingerprints = []
    for candidate in manifest.get("pool_candidates", []):
        if not isinstance(candidate, dict) or not isinstance(candidate.get("source_snapshot"), dict):
            continue
        source_fingerprints.append(
            {
                "source_row": candidate.get("source_row"),
                "source_fingerprint": _source_snapshot_fingerprint(candidate["source_snapshot"]),
            }
        )

    writes = manifest.get("writes") if isinstance(manifest.get("writes"), list) else []
    token_by_target = {
        "copy": normalize_text(manifest.get("copy", {}).get("token")),
        "pool": normalize_text(manifest.get("pool", {}).get("token")),
    }
    transactions = {}
    for target in ("copy", "pool"):
        target_writes = [
            write for write in writes if normalize_text(write.get("target")) == target
        ]
        if not target_writes:
            continue
        token = token_by_target[target]
        envelope = _transaction_envelope(target, token, target_writes)
        transactions[target] = {
            "top_level_token": token,
            "payload_sha256": _sha256(envelope),
            "operation_count": len(target_writes),
            "dry_run": None,
            "execute": None,
        }

    report_rows = sorted(
        (
            _report_row(row)
            for row in manifest.get("rows", [])
            if isinstance(row, dict)
            and normalize_text(row.get("decision")) in DECISIONS - {"SUBMIT"}
        ),
        key=lambda item: item["row_key"],
    )
    return {
        "source_fingerprints": source_fingerprints,
        "transactions": transactions,
        "report_expected_rows": report_rows,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    pending_parser = subparsers.add_parser("is-pending", help="exact-match the pending status")
    pending_parser.add_argument("--value", required=True)

    profile_parser = subparsers.add_parser("normalize-profile", help="build a creator dedupe key")
    profile_parser.add_argument("--url", default="")
    profile_parser.add_argument("--platform", default="")
    profile_parser.add_argument("--name", default="")
    profile_parser.add_argument("--agency", default="")

    topic_parser = subparsers.add_parser("validate-topic", help="validate the exact four-line topic format")
    topic_input = topic_parser.add_mutually_exclusive_group(required=True)
    topic_input.add_argument("--text")
    topic_input.add_argument("--file")
    topic_parser.add_argument("--soft-limit", type=int, default=220)
    topic_parser.add_argument("--hard-limit", type=int, default=260)

    key_parser = subparsers.add_parser("topic-key", help="build a structured exact-duplicate key")
    key_parser.add_argument("--main-skill", required=True)
    key_parser.add_argument("--core-task", required=True)
    key_parser.add_argument("--key-input", required=True)
    key_parser.add_argument("--final-artifact", required=True)
    key_parser.add_argument("--lifecycle", default="")

    manifest_parser = subparsers.add_parser("validate-manifest", help="validate a batch write plan")
    manifest_parser.add_argument("--file", required=True)

    derive_parser = subparsers.add_parser(
        "derive-plan-evidence", help="derive source fingerprints, transaction hashes and report rows"
    )
    derive_parser.add_argument("--file", required=True)

    hash_parser = subparsers.add_parser("hash-text", help="hash normalized expected/readback text")
    hash_parser.add_argument("--file", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "is-pending":
            _print_json({"normalized": normalize_text(args.value), "is_pending": is_exact_pending(args.value)})
            return 0
        if args.command == "normalize-profile":
            _print_json(normalize_profile(args.url, args.platform, args.name, args.agency))
            return 0
        if args.command == "validate-topic":
            text = args.text if args.text is not None else _load_text(args.file)
            result = validate_topic(text, args.soft_limit, args.hard_limit)
            _print_json(result)
            return 0 if result["ok"] else 1
        if args.command == "topic-key":
            _print_json(
                {
                    "topic_key": topic_key(
                        args.main_skill,
                        args.core_task,
                        args.key_input,
                        args.final_artifact,
                        args.lifecycle,
                    )
                }
            )
            return 0
        if args.command == "validate-manifest":
            result = validate_manifest(_load_json(args.file))
            _print_json(result)
            return 0 if result["ok"] else 1
        if args.command == "derive-plan-evidence":
            _print_json(derive_plan_evidence(_load_json(args.file)))
            return 0
        if args.command == "hash-text":
            normalized = strip_text_edges(_load_text(args.file), nfkc=False).replace(
                "\r\n", "\n"
            ).replace("\r", "\n")
            _print_json({"content_sha256": _sha256({"text": normalized})})
            return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        _print_json({"ok": False, "errors": [str(error)], "warnings": []})
        return 2
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
