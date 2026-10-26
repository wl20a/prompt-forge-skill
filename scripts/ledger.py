#!/usr/bin/env python3
"""Local JSONL ledger for Prompt Forge change and preference signals."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import tempfile
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DECISIONS = ("pending", "accepted", "rejected")
STRENGTHS = ("none", "may", "should", "must", "must-not", "unchanged")
CATEGORIES = (
    "goal",
    "input",
    "scope",
    "constraint",
    "authority",
    "deliverable",
    "acceptance",
    "verification",
    "security",
    "risk",
    "preference",
    "stop",
    "format",
    "other",
)
ACTIONS = ("add", "remove", "clarify", "reorder", "strengthen", "weaken")
CATEGORY_ALIASES = {
    "risk-control": "risk",
    "risk_control": "risk",
    "security-check": "security",
    "security_check": "security",
    "tests": "verification",
    "testing": "verification",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def default_ledger_path() -> Path:
    override = os.environ.get("PROMPT_FORGE_LEDGER")
    if override:
        return Path(override).expanduser()
    codex_home = os.environ.get("CODEX_HOME")
    root = Path(codex_home).expanduser() if codex_home else Path.home() / ".codex"
    return root / "prompt-forge" / "ledger.jsonl"


def ensure_private_parent(path: Path) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass


def read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"invalid JSON on ledger line {line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise SystemExit(f"ledger line {line_number} is not a JSON object")
            rows.append(value)
    return rows


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    ensure_private_parent(path)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.chmod(0o600)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def with_lock(path: Path, mutate):
    ensure_private_parent(path)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            return mutate()
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def clipped(value: str | None, limit: int = 1200) -> str:
    text = value or ""
    return text if len(text) <= limit else text[:limit] + "…"


def normalize_category(value: str) -> str:
    normalized = value.strip().lower()
    normalized = CATEGORY_ALIASES.get(normalized, normalized)
    return normalized if normalized in CATEGORIES else "other"


def command_record(args: argparse.Namespace) -> int:
    path = Path(args.ledger).expanduser()
    now = utc_now()
    record_id = f"pf-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    row: dict[str, Any] = {
        "id": record_id,
        "created_at": now,
        "resolved_at": now if args.decision != "pending" else None,
        "task_id": args.task_id,
        "scope": args.scope,
        "category": args.category,
        "action": args.action,
        "summary": clipped(args.summary),
        "before": clipped(args.before),
        "after": clipped(args.after),
        "strength_before": args.strength_before,
        "strength_after": args.strength_after,
        "provenance": clipped(args.provenance),
        "decision": args.decision,
        "evidence": clipped(args.evidence),
        "preference_key": clipped(args.preference_key),
        "preference_value": clipped(args.preference_value),
    }

    def mutate() -> int:
        rows = read_rows(path)
        rows.append(row)
        write_rows(path, rows)
        return 0

    with_lock(path, mutate)
    print(json.dumps(row, ensure_ascii=False, sort_keys=True))
    return 0


def command_record_many(args: argparse.Namespace) -> int:
    try:
        payload = json.loads(args.json)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid --json: {exc}") from exc
    if not isinstance(payload, list) or not payload:
        raise SystemExit("--json must be a non-empty JSON array")

    path = Path(args.ledger).expanduser()
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise SystemExit(f"record {index} is not a JSON object")
        category = normalize_category(str(item.get("category", "")))
        action = str(item.get("action", ""))
        decision = str(item.get("decision", "pending"))
        strength_before = str(item.get("strength_before", "none"))
        strength_after = str(item.get("strength_after", "none"))
        if category not in CATEGORIES:
            raise SystemExit(f"record {index} has invalid category: {category}")
        if action not in ACTIONS:
            raise SystemExit(f"record {index} has invalid action: {action}")
        if decision not in DECISIONS:
            raise SystemExit(f"record {index} has invalid decision: {decision}")
        if strength_before not in STRENGTHS or strength_after not in STRENGTHS:
            raise SystemExit(f"record {index} has invalid strength")
        task_id = str(item.get("task_id", "")).strip()
        summary = str(item.get("summary", "")).strip()
        provenance = str(item.get("provenance", "")).strip()
        if not task_id or not summary or not provenance:
            raise SystemExit(
                f"record {index} requires task_id, summary, and provenance"
            )
        now = utc_now()
        rows.append(
            {
                "id": (
                    f"pf-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-"
                    f"{uuid.uuid4().hex[:8]}"
                ),
                "created_at": now,
                "resolved_at": now if decision != "pending" else None,
                "task_id": task_id,
                "scope": clipped(str(item.get("scope", "global"))),
                "category": category,
                "action": action,
                "summary": clipped(summary),
                "before": clipped(str(item.get("before", ""))),
                "after": clipped(str(item.get("after", ""))),
                "strength_before": strength_before,
                "strength_after": strength_after,
                "provenance": clipped(provenance),
                "decision": decision,
                "evidence": clipped(str(item.get("evidence", ""))),
                "preference_key": clipped(str(item.get("preference_key", ""))),
                "preference_value": clipped(str(item.get("preference_value", ""))),
            }
        )

    def mutate() -> int:
        existing = read_rows(path)
        existing.extend(rows)
        write_rows(path, existing)
        return 0

    with_lock(path, mutate)
    print(json.dumps({"records": rows}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def command_resolve(args: argparse.Namespace) -> int:
    path = Path(args.ledger).expanduser()

    def mutate() -> int:
        rows = read_rows(path)
        matches = [row for row in rows if row.get("id") == args.id]
        if not matches:
            raise SystemExit(f"record not found: {args.id}")
        if len(matches) > 1:
            raise SystemExit(f"duplicate record id: {args.id}")
        row = matches[0]
        row["decision"] = args.decision
        row["evidence"] = clipped(args.evidence)
        row["resolved_at"] = utc_now()
        write_rows(path, rows)
        print(json.dumps(row, ensure_ascii=False, sort_keys=True))
        return 0

    return with_lock(path, mutate)


def command_list(args: argparse.Namespace) -> int:
    path = Path(args.ledger).expanduser()
    rows = read_rows(path)
    if args.scope:
        rows = [row for row in rows if row.get("scope") == args.scope]
    if args.decision:
        rows = [row for row in rows if row.get("decision") == args.decision]
    rows = rows[-args.limit :]
    print(json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def command_suggest(args: argparse.Namespace) -> int:
    path = Path(args.ledger).expanduser()
    rows = read_rows(path)
    grouped: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "scope": "",
            "key": "",
            "value": "",
            "accepted": 0,
            "rejected": 0,
            "explicit": 0,
            "task_ids": set(),
        }
    )

    for row in rows:
        key = str(row.get("preference_key") or "")
        value = str(row.get("preference_value") or "")
        decision = row.get("decision")
        if not key or not value or decision not in ("accepted", "rejected"):
            continue
        scope = str(row.get("scope") or "global")
        if args.scope and scope not in (args.scope, "global"):
            continue
        bucket = grouped[(scope, key, value)]
        bucket["scope"] = scope
        bucket["key"] = key
        bucket["value"] = value
        bucket[decision] += 1
        bucket["task_ids"].add(str(row.get("task_id") or ""))
        if decision == "accepted" and str(row.get("provenance", "")).startswith("user-explicit"):
            bucket["explicit"] += 1

    suggestions: list[dict[str, Any]] = []
    for bucket in grouped.values():
        accepted = bucket["accepted"]
        rejected = bucket["rejected"]
        explicit = bucket["explicit"]
        distinct_tasks = len({item for item in bucket["task_ids"] if item})
        if accepted <= rejected or accepted == 0:
            continue
        if explicit:
            status = "explicit"
        elif distinct_tasks >= 3:
            status = "stable"
        elif distinct_tasks >= 2:
            status = "tentative"
        else:
            status = "single-observation"
        suggestions.append(
            {
                "scope": bucket["scope"],
                "key": bucket["key"],
                "value": bucket["value"],
                "status": status,
                "distinct_tasks": distinct_tasks,
                "accepted": accepted,
                "rejected": rejected,
            }
        )

    rank = {"explicit": 0, "stable": 1, "tentative": 2, "single-observation": 3}
    suggestions.sort(key=lambda item: (rank[item["status"]], -item["distinct_tasks"]))
    print(json.dumps(suggestions[: args.limit], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def build_profile(rows: list[dict[str, Any]], scope: str | None) -> dict[str, Any]:
    buckets: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "scope": "global",
            "key": "",
            "value": "",
            "accepted": 0,
            "rejected": 0,
            "explicit": 0,
            "explicit_strengths": set(),
            "accepted_tasks": set(),
            "rejected_tasks": set(),
        }
    )
    pending = 0

    for row in rows:
        row_scope = str(row.get("scope") or "global")
        if scope:
            if row_scope not in (scope, "global"):
                continue
        elif row_scope != "global":
            continue

        if row.get("decision") == "pending":
            pending += 1
            continue

        key = str(row.get("preference_key") or "")
        value = str(row.get("preference_value") or "")
        decision = row.get("decision")
        if not key or not value or decision not in ("accepted", "rejected"):
            continue

        bucket = buckets[(row_scope, key, value)]
        bucket["scope"] = row_scope
        bucket["key"] = key
        bucket["value"] = value
        bucket[decision] += 1
        bucket[f"{decision}_tasks"].add(str(row.get("task_id") or ""))
        if decision == "accepted" and str(row.get("provenance", "")).startswith(
            "user-explicit"
        ):
            bucket["explicit"] += 1
            bucket["explicit_strengths"].add(
                str(row.get("strength_after") or "none")
            )

    def candidate(bucket: dict[str, Any], direction: str) -> dict[str, Any]:
        accepted_tasks = len({item for item in bucket["accepted_tasks"] if item})
        rejected_tasks = len({item for item in bucket["rejected_tasks"] if item})
        accepted = bucket["accepted"]
        rejected = bucket["rejected"]
        explicit = bucket["explicit"]
        if direction == "positive":
            distinct = accepted_tasks
            if explicit and accepted > rejected:
                status = "explicit"
            elif distinct >= 3 and accepted > rejected:
                status = "stable"
            elif distinct >= 2 and accepted > rejected:
                status = "tentative"
            elif accepted > rejected:
                status = "single-observation"
            else:
                status = "suppressed"
            strength = "should"
            if status == "explicit":
                explicit_must = bucket["explicit_strengths"] & {"must", "must-not"}
                if explicit_must:
                    strength = sorted(explicit_must)[0]
        else:
            distinct = rejected_tasks
            if distinct >= 3 and rejected > accepted:
                status = "stable"
            elif distinct >= 2 and rejected > accepted:
                status = "tentative"
            else:
                status = "suppressed"
            strength = "should-avoid"
        return {
            "scope": bucket["scope"],
            "key": bucket["key"],
            "value": bucket["value"],
            "status": status,
            "strength": strength,
            "accepted": accepted,
            "rejected": rejected,
            "distinct_tasks": distinct,
        }

    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for bucket in buckets.values():
        positive = candidate(bucket, "positive")
        negative = candidate(bucket, "negative")
        if positive["status"] != "suppressed":
            by_key[positive["key"]].append(positive)
        if negative["status"] != "suppressed":
            by_key[negative["key"]].append(negative)

    rules: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    rank = {
        "explicit": 0,
        "stable": 1,
        "tentative": 2,
        "single-observation": 3,
    }

    for key, candidates in sorted(by_key.items()):
        specific = [item for item in candidates if item["scope"] == scope]
        selected = specific or [item for item in candidates if item["scope"] == "global"]
        selected.sort(key=lambda item: (rank[item["status"]], -item["distinct_tasks"]))
        applicable = [
            item
            for item in selected
            if item["status"] == "explicit"
            or (item["status"] == "stable" and item["strength"] != "should-avoid")
        ]
        stable_avoid = [
            item
            for item in selected
            if item["status"] == "stable" and item["strength"] == "should-avoid"
        ]

        if len(applicable) > 1:
            conflicts.append({"key": key, "candidates": applicable})
            continue
        if applicable:
            rules.append(applicable[0])
            if stable_avoid:
                observations.extend(stable_avoid)
            continue
        if stable_avoid:
            rules.extend(stable_avoid)
            continue
        observations.extend(selected)

    return {
        "scope": scope or "global",
        "rules": rules,
        "conflicts": conflicts,
        "observations": observations,
        "pending": pending,
    }


def render_profile_markdown(profile: dict[str, Any]) -> str:
    lines = [f"# Calibration profile: {profile['scope']}", ""]
    if profile["rules"]:
        lines.extend(["## Apply", ""])
        for rule in profile["rules"]:
            lines.append(
                f"- {rule['strength']}: `{rule['key']}` = `{rule['value']}` "
                f"({rule['status']}, {rule['distinct_tasks']} tasks; "
                f"{rule['accepted']} accept / {rule['rejected']} reject)"
            )
        lines.append("")
    if profile["conflicts"]:
        lines.extend(["## Conflicts: do not auto-apply", ""])
        for conflict in profile["conflicts"]:
            values = ", ".join(
                f"`{item['value']}` ({item['status']})"
                for item in conflict["candidates"]
            )
            lines.append(f"- `{conflict['key']}`: {values}")
        lines.append("")
    if profile["observations"]:
        lines.extend(["## Observations below threshold", ""])
        for item in profile["observations"]:
            lines.append(
                f"- {item['status']}: `{item['key']}` = `{item['value']}` "
                f"({item['distinct_tasks']} tasks)"
            )
        lines.append("")
    lines.append(f"Pending decisions not used: {profile['pending']}")
    return "\n".join(lines).rstrip() + "\n"


def command_profile(args: argparse.Namespace) -> int:
    path = Path(args.ledger).expanduser()
    profile = build_profile(read_rows(path), args.scope)
    if args.format == "markdown":
        print(render_profile_markdown(profile), end="")
    else:
        print(json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default=str(default_ledger_path()))
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser("record", help="append one change record")
    record.add_argument("--task-id", required=True)
    record.add_argument("--scope", default="global")
    record.add_argument("--category", choices=CATEGORIES, required=True)
    record.add_argument("--action", choices=ACTIONS, required=True)
    record.add_argument("--summary", required=True)
    record.add_argument("--before", default="")
    record.add_argument("--after", default="")
    record.add_argument("--strength-before", choices=STRENGTHS, default="none")
    record.add_argument("--strength-after", choices=STRENGTHS, default="none")
    record.add_argument("--provenance", required=True)
    record.add_argument("--decision", choices=DECISIONS, default="pending")
    record.add_argument("--evidence", default="")
    record.add_argument("--preference-key", default="")
    record.add_argument("--preference-value", default="")
    record.set_defaults(func=command_record)

    record_many = subparsers.add_parser(
        "record-many", help="append several change records in one write"
    )
    record_many.add_argument("--json", required=True, help="JSON array of records")
    record_many.set_defaults(func=command_record_many)

    resolve = subparsers.add_parser("resolve", help="record acceptance or rejection")
    resolve.add_argument("--id", required=True)
    resolve.add_argument("--decision", choices=("accepted", "rejected"), required=True)
    resolve.add_argument("--evidence", required=True)
    resolve.set_defaults(func=command_resolve)

    list_rows = subparsers.add_parser("list", help="list recent records")
    list_rows.add_argument("--scope")
    list_rows.add_argument("--decision", choices=DECISIONS)
    list_rows.add_argument("--limit", type=int, default=20)
    list_rows.set_defaults(func=command_list)

    suggest = subparsers.add_parser("suggest", help="return scoped preference suggestions")
    suggest.add_argument("--scope")
    suggest.add_argument("--limit", type=int, default=10)
    suggest.set_defaults(func=command_suggest)

    profile = subparsers.add_parser(
        "profile", help="compile stable rules, conflicts, and pending evidence"
    )
    profile.add_argument("--scope")
    profile.add_argument("--format", choices=("json", "markdown"), default="json")
    profile.set_defaults(func=command_profile)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if getattr(args, "limit", 1) <= 0:
        parser.error("--limit must be positive")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
