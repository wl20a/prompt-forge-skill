#!/usr/bin/env python3
"""Run isolated baseline/candidate Codex tasks and grade observable outcomes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".prompt-forge",
}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
def now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"cannot read manifest: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid manifest JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit("manifest root must be a JSON object")
    return value


def safe_resolve(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def snapshot(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in IGNORED_DIRS for part in relative.parts):
            continue
        if not path.is_file() or path.suffix in IGNORED_SUFFIXES:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        result[relative.as_posix()] = digest
    return result


def changed_paths(before: dict[str, str], after: dict[str, str]) -> list[str]:
    paths = set(before) | set(after)
    return sorted(path for path in paths if before.get(path) != after.get(path))


def count_ledger_records(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(
        1
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip()
    )


def path_matches(path: str, prefix: str) -> bool:
    clean = prefix.rstrip("/")
    return path == clean or path.startswith(clean + "/")


def run_command_check(
    check: dict[str, Any], workspace: Path, timeout_seconds: float
) -> dict[str, Any]:
    command = check.get("command")
    if not isinstance(command, list) or not command or not all(
        isinstance(item, str) for item in command
    ):
        return {
            "name": check.get("name", "command"),
            "type": "command",
            "passed": False,
            "detail": "command check requires a non-empty string array",
        }
    try:
        completed = subprocess.run(
            command,
            cwd=workspace,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "name": check.get("name", "command"),
            "type": "command",
            "passed": False,
            "detail": f"timed out after {timeout_seconds:.1f}s",
            "stdout": (exc.stdout or "")[-4000:],
            "stderr": (exc.stderr or "")[-4000:],
        }
    except OSError as exc:
        return {
            "name": check.get("name", "command"),
            "type": "command",
            "passed": False,
            "detail": f"could not execute command: {exc}",
        }
    passed = completed.returncode == 0
    return {
        "name": check.get("name", "command"),
        "type": "command",
        "passed": passed,
        "detail": f"exit code {completed.returncode}",
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
    }


def evaluate_check(
    check: dict[str, Any],
    workspace: Path,
    changed: list[str],
    final_text: str,
    timeout_seconds: float,
    ledger_path: Path,
) -> dict[str, Any]:
    kind = str(check.get("type", ""))
    name = str(check.get("name") or kind)
    if kind == "command":
        result = run_command_check(check, workspace, timeout_seconds)
        result["name"] = name
        return result

    if kind in ("forbidden_paths", "unchanged_paths"):
        paths = [str(item) for item in check.get("paths", [])]
        hits = [
            path
            for path in changed
            if any(path_matches(path, prefix) for prefix in paths)
        ]
        return {
            "name": name,
            "type": kind,
            "passed": not hits,
            "detail": "unchanged" if not hits else f"changed forbidden paths: {hits}",
        }

    if kind == "allowed_paths":
        paths = [str(item) for item in check.get("paths", [])]
        outside = [
            path
            for path in changed
            if not any(path_matches(path, prefix) for prefix in paths)
        ]
        return {
            "name": name,
            "type": kind,
            "passed": not outside,
            "detail": "all changed paths allowed" if not outside else f"outside: {outside}",
        }

    if kind == "required_changed":
        paths = [str(item) for item in check.get("paths", [])]
        missing = [path for path in paths if path not in changed]
        return {
            "name": name,
            "type": kind,
            "passed": not missing,
            "detail": "required paths changed" if not missing else f"not changed: {missing}",
        }

    if kind == "max_changed_files":
        maximum = int(check.get("value", 0))
        return {
            "name": name,
            "type": kind,
            "passed": len(changed) <= maximum,
            "detail": f"{len(changed)} changed files; maximum {maximum}",
        }

    if kind in ("ledger_min_records", "ledger_max_records"):
        expected = int(check.get("value", 0))
        actual = count_ledger_records(ledger_path)
        passed = (
            actual >= expected
            if kind == "ledger_min_records"
            else actual <= expected
        )
        comparator = ">=" if kind == "ledger_min_records" else "<="
        return {
            "name": name,
            "type": kind,
            "passed": passed,
            "detail": f"ledger records {actual}; expected {comparator} {expected}",
        }

    if kind in ("final_contains", "final_not_contains"):
        pattern = str(check.get("pattern", ""))
        try:
            found = re.search(pattern, final_text, flags=re.MULTILINE) is not None
        except re.error as exc:
            return {
                "name": name,
                "type": kind,
                "passed": False,
                "detail": f"invalid regex: {exc}",
            }
        passed = found if kind == "final_contains" else not found
        return {
            "name": name,
            "type": kind,
            "passed": passed,
            "detail": f"pattern found={found}",
        }

    return {
        "name": name,
        "type": kind or "unknown",
        "passed": False,
        "detail": f"unsupported check type: {kind}",
    }


def parse_events(events_path: Path) -> dict[str, Any]:
    result = {
        "turn_completed": False,
        "input_tokens": None,
        "cached_input_tokens": None,
        "output_tokens": None,
        "command_runs": 0,
        "failed_commands": 0,
        "last_agent_message": "",
    }
    if not events_path.exists():
        return result
    for line in events_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.completed":
            result["turn_completed"] = True
            usage = event.get("usage") or {}
            result["input_tokens"] = usage.get("input_tokens")
            result["cached_input_tokens"] = usage.get("cached_input_tokens")
            result["output_tokens"] = usage.get("output_tokens")
        item = event.get("item") or {}
        if (
            item.get("type") == "command_execution"
            and item.get("status") in ("completed", "failed")
        ):
            result["command_runs"] += 1
            if item.get("status") == "failed" or item.get("exit_code") not in (None, 0):
                result["failed_commands"] += 1
        if item.get("type") == "agent_message" and item.get("text"):
            result["last_agent_message"] = item["text"]
    return result


def build_prompt(
    arm: dict[str, Any],
    request: str,
    default_skill: Path,
    manifest_dir: Path,
) -> str:
    kind = str(arm.get("kind", "direct"))
    if kind == "direct":
        return (
            "Do not invoke, read, or follow any installed prompt-optimization "
            "skill. Handle the following request directly:\n\n"
            f"{request}"
        )
    if kind != "skill":
        raise SystemExit(f"unsupported arm kind: {kind}")
    raw_skill = arm.get("skill")
    skill = (
        default_skill
        if raw_skill in (None, "", "auto")
        else safe_resolve(manifest_dir, str(raw_skill))
    )
    return (
        f"Read and follow the skill at {skill.expanduser().resolve()} as the "
        f"controlling workflow. Then handle this request:\n\n{request}"
    )


def copy_fixture(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise SystemExit(f"fixture is not a directory: {source}")
    shutil.copytree(source, destination)


def codex_command(
    codex_bin: str,
    workspace: Path,
    final_path: Path,
    prompt: str,
    model: str | None,
    approve_for_me: bool,
    images: list[Path],
) -> list[str]:
    command = [
        codex_bin,
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--json",
    ]
    if approve_for_me:
        command.append("--approve-for-me")
    else:
        command.extend(["--sandbox", "workspace-write"])
    if model:
        command.extend(["--model", model])
    for image in images:
        command.extend(["--image", str(image)])
    command.extend(["-C", str(workspace), "-o", str(final_path), "--", prompt])
    return command


def run_arm(
    arm: dict[str, Any],
    task: dict[str, Any],
    fixture: Path,
    arm_dir: Path,
    default_skill: Path,
    manifest_dir: Path,
    timeout_seconds: float,
    codex_bin: str,
    model: str | None,
    approve_for_me: bool,
    images: list[Path],
) -> dict[str, Any]:
    workspace = arm_dir / "workspace"
    arm_dir.mkdir(parents=True, exist_ok=False)
    copy_fixture(fixture, workspace)
    before = snapshot(workspace)
    prompt = build_prompt(
        arm, str(task["request"]), default_skill, manifest_dir
    )
    (arm_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    events_path = arm_dir / "events.jsonl"
    stderr_path = arm_dir / "stderr.log"
    final_path = arm_dir / "final.txt"
    command = codex_command(
        codex_bin,
        workspace,
        final_path,
        prompt,
        model,
        approve_for_me,
        images,
    )
    ledger_path = workspace / ".prompt-forge" / "ledger.jsonl"
    env = os.environ.copy()
    env["PROMPT_FORGE_LEDGER"] = str(ledger_path)
    started = time.monotonic()
    timed_out = False
    return_code: int | None = None
    stdout = ""
    stderr = ""
    try:
        completed = subprocess.run(
            command,
            cwd=workspace,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        return_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
    except OSError as exc:
        return_code = None
        stderr = f"could not execute {codex_bin}: {exc}\n"
    elapsed = time.monotonic() - started
    events_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    final_text = final_path.read_text(encoding="utf-8") if final_path.exists() else ""
    parsed = parse_events(events_path)
    if not final_text:
        final_text = parsed["last_agent_message"]
    after = snapshot(workspace)
    changed = changed_paths(before, after)
    checks: list[dict[str, Any]] = []
    for check in task.get("checks", []):
        applies_to = check.get("applies_to_arms")
        if applies_to and arm["id"] not in applies_to:
            continue
        evaluated = evaluate_check(
            check,
            workspace,
            changed,
            final_text,
            timeout_seconds,
            ledger_path,
        )
        evaluated["category"] = str(check.get("category", "outcome"))
        checks.append(evaluated)
    outcome_checks = [check for check in checks if check["category"] == "outcome"]
    diagnostic_checks = [
        check for check in checks if check["category"] == "diagnostic"
    ]
    outcome_passed = sum(1 for check in outcome_checks if check["passed"])
    outcome_total = len(outcome_checks)
    diagnostic_passed = sum(1 for check in diagnostic_checks if check["passed"])
    diagnostic_total = len(diagnostic_checks)
    scope_types = {
        "forbidden_paths",
        "allowed_paths",
        "unchanged_paths",
        "max_changed_files",
    }
    constraint_types = {"final_contains", "final_not_contains"}
    result = {
        "id": arm["id"],
        "kind": arm.get("kind", "direct"),
        "return_code": return_code,
        "timed_out": timed_out,
        "turn_completed": parsed["turn_completed"],
        "elapsed_seconds": round(elapsed, 3),
        "checks": checks,
        "check_passed": outcome_passed,
        "check_total": outcome_total,
        "diagnostic_passed": diagnostic_passed,
        "diagnostic_total": diagnostic_total,
        "first_pass_ok": (
            outcome_total > 0
            and outcome_passed == outcome_total
            and not timed_out
        ),
        "process_ok": diagnostic_passed == diagnostic_total,
        "check_error_rate": (
            0
            if outcome_total == 0
            else round((outcome_total - outcome_passed) / outcome_total, 4)
        ),
        "command_runs": parsed["command_runs"],
        "rework_rounds": parsed["failed_commands"],
        "scope_incidents": sum(
            1
            for check in checks
            if check["category"] == "outcome"
            and check["type"] in scope_types
            and not check["passed"]
        ),
        "constraint_incidents": sum(
            1
            for check in checks
            if check["category"] == "outcome"
            and check["type"] in constraint_types
            and not check["passed"]
        ),
        "clarification_signal": bool(
            final_text.strip().endswith("?")
            or re.search(r"(?i)please provide|cần|需要你|请提供", final_text)
        ),
        "changed_paths": changed,
        "input_tokens": parsed["input_tokens"],
        "cached_input_tokens": parsed["cached_input_tokens"],
        "output_tokens": parsed["output_tokens"],
        "ledger_records": count_ledger_records(ledger_path),
        "ledger_path": str(ledger_path),
        "images": [str(image) for image in images],
        "final_path": str(final_path),
        "events_path": str(events_path),
        "workspace": str(workspace),
    }
    (arm_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[result["id"]].append(result)
    summary: dict[str, Any] = {}
    for arm_id, rows in sorted(grouped.items()):
        count = len(rows)
        summary[arm_id] = {
            "tasks": count,
            "first_pass_rate": round(
                sum(1 for row in rows if row["first_pass_ok"]) / count, 4
            ),
            "process_ok_rate": round(
                sum(1 for row in rows if row["process_ok"]) / count, 4
            ),
            "avg_seconds": round(
                sum(float(row["elapsed_seconds"]) for row in rows) / count, 3
            ),
            "avg_check_error_rate": round(
                sum(float(row["check_error_rate"]) for row in rows) / count, 4
            ),
            "rework_rounds": sum(int(row["rework_rounds"]) for row in rows),
            "scope_incidents": sum(int(row["scope_incidents"]) for row in rows),
            "constraint_incidents": sum(
                int(row["constraint_incidents"]) for row in rows
            ),
            "clarification_signals": sum(
                1 for row in rows if row["clarification_signal"]
            ),
            "ledger_records": sum(int(row["ledger_records"]) for row in rows),
        }
    return summary


def write_csv(path: Path, runs: list[dict[str, Any]]) -> None:
    fields = [
        "task_id",
        "arm_id",
        "first_pass_ok",
        "check_passed",
        "check_total",
        "diagnostic_passed",
        "diagnostic_total",
        "process_ok",
        "check_error_rate",
        "command_runs",
        "elapsed_seconds",
        "rework_rounds",
        "scope_incidents",
        "constraint_incidents",
        "clarification_signal",
        "input_tokens",
        "output_tokens",
        "ledger_records",
        "ledger_path",
        "changed_paths",
        "final_path",
        "events_path",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for run in runs:
            writer.writerow(
                {
                    "task_id": run["task_id"],
                    "arm_id": run["arm_id"],
                    "first_pass_ok": run["first_pass_ok"],
                    "check_passed": run["check_passed"],
                    "check_total": run["check_total"],
                    "diagnostic_passed": run["diagnostic_passed"],
                    "diagnostic_total": run["diagnostic_total"],
                    "process_ok": run["process_ok"],
                    "check_error_rate": run["check_error_rate"],
                    "command_runs": run["command_runs"],
                    "elapsed_seconds": run["elapsed_seconds"],
                    "rework_rounds": run["rework_rounds"],
                    "scope_incidents": run["scope_incidents"],
                    "constraint_incidents": run["constraint_incidents"],
                    "clarification_signal": run["clarification_signal"],
                    "input_tokens": run["input_tokens"],
                    "output_tokens": run["output_tokens"],
                    "ledger_records": run["ledger_records"],
                    "ledger_path": run["ledger_path"],
                    "changed_paths": ";".join(run["changed_paths"]),
                    "final_path": run["final_path"],
                    "events_path": run["events_path"],
                }
            )


def render_report(manifest: dict[str, Any], run_root: Path, runs: list[dict[str, Any]]) -> str:
    lines = [
        f"# A/B report: {manifest.get('name', 'unnamed')}",
        "",
        f"Run root: `{run_root}`",
        "",
        "| Task | Arm | First pass | Outcome checks | Process checks | Error rate | Seconds | Rebuild | Scope | Constraints |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for run in runs:
        lines.append(
            f"| {run['task_id']} | {run['arm_id']} | "
            f"{'yes' if run['first_pass_ok'] else 'no'} | "
            f"{run['check_passed']}/{run['check_total']} | "
            f"{run['diagnostic_passed']}/{run['diagnostic_total']} | "
            f"{run['check_error_rate']:.2%} | {run['elapsed_seconds']:.2f} | "
            f"{run['rework_rounds']} | {run['scope_incidents']} | "
            f"{run['constraint_incidents']} |"
        )
    lines.extend(
        [
            "",
            "`Rebuild` is the number of failed agent commands before the turn ended;",
            "it is a self-repair proxy, not a count of human correction rounds.",
            "A one-task comparison is a smoke test, not evidence of general improvement.",
            "",
        ]
    )
    return "\n".join(lines)


def validate_manifest(manifest: dict[str, Any], manifest_dir: Path) -> list[dict[str, Any]]:
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise SystemExit("manifest requires a non-empty tasks array")
    seen: set[str] = set()
    for index, task in enumerate(tasks, start=1):
        if not isinstance(task, dict):
            raise SystemExit(f"task {index} is not an object")
        task_id = str(task.get("id", "")).strip()
        request = str(task.get("request", "")).strip()
        fixture = str(task.get("fixture", "")).strip()
        if not task_id or task_id in seen:
            raise SystemExit(f"task {index} requires a unique id")
        if not request or not fixture:
            raise SystemExit(f"task {task_id} requires request and fixture")
        seen.add(task_id)
        if not safe_resolve(manifest_dir, fixture).is_dir():
            raise SystemExit(f"task {task_id} fixture does not exist: {fixture}")
        images = task.get("images", [])
        if not isinstance(images, list) or not all(
            isinstance(item, str) for item in images
        ):
            raise SystemExit(f"task {task_id} images must be a string array")
        for image in images:
            if not safe_resolve(manifest_dir, image).is_file():
                raise SystemExit(
                    f"task {task_id} image does not exist: {image}"
                )
        checks = task.get("checks")
        if not isinstance(checks, list) or not checks:
            raise SystemExit(f"task {task_id} requires at least one check")
        for check in checks:
            if not isinstance(check, dict) or not check.get("type"):
                raise SystemExit(f"task {task_id} has an invalid check")
    return tasks


def command_run(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).expanduser().resolve()
    manifest = read_json(manifest_path)
    tasks = validate_manifest(manifest, manifest_path.parent)
    if args.task:
        requested_tasks = set(args.task)
        available_tasks = {str(task["id"]) for task in tasks}
        missing = sorted(requested_tasks - available_tasks)
        if missing:
            raise SystemExit(f"unknown task filter(s): {missing}")
        tasks = [task for task in tasks if task["id"] in requested_tasks]
    out_root = Path(args.out).expanduser().resolve()
    if out_root.exists():
        raise SystemExit(f"output path already exists: {out_root}")
    run_root = out_root / f"{now_slug()}-{uuid.uuid4().hex[:6]}"
    default_skill = Path(args.skill).expanduser().resolve()
    if not default_skill.is_file():
        raise SystemExit(f"skill file not found: {default_skill}")
    arms = manifest.get("arms")
    if not isinstance(arms, list) or len(arms) < 2:
        arms = [
            {"id": "direct", "kind": "direct"},
            {"id": "prompt-forge", "kind": "skill", "skill": "auto"},
        ]
    seen_arms: set[str] = set()
    for arm in arms:
        if not isinstance(arm, dict):
            raise SystemExit("each arm must be an object")
        arm_id = str(arm.get("id", "")).strip()
        if not arm_id or arm_id in seen_arms:
            raise SystemExit("arms require unique ids")
        seen_arms.add(arm_id)
        if arm.get("kind", "direct") not in ("direct", "skill"):
            raise SystemExit(f"unsupported arm kind for {arm_id}")

    if args.dry_run:
        plan = {
            "manifest": str(manifest_path),
            "run_root": str(run_root),
            "tasks": [task["id"] for task in tasks],
            "images": {
                str(task["id"]): [
                    str(safe_resolve(manifest_path.parent, item))
                    for item in task.get("images", [])
                ]
                for task in tasks
            },
            "arms": [
                {
                    "id": arm["id"],
                    "kind": arm.get("kind", "direct"),
                    "skill": (
                        str(default_skill)
                        if arm.get("kind") == "skill"
                        and arm.get("skill") in (None, "", "auto")
                        else arm.get("skill")
                    ),
                }
                for arm in arms
            ],
            "codex_bin": args.codex_bin,
            "model": args.model,
            "approve_for_me": args.approve_for_me,
        }
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    run_root.mkdir(parents=True)
    pending = [
        (task, arm)
        for task in tasks
        for arm in arms
    ]
    random.Random(args.seed).shuffle(pending)
    runs: list[dict[str, Any]] = []
    for task, arm in pending:
        task_id = str(task["id"])
        arm_id = str(arm["id"])
        arm_dir = run_root / "runs" / task_id / arm_id
        result = run_arm(
            arm=arm,
            task=task,
            fixture=safe_resolve(manifest_path.parent, str(task["fixture"])),
            arm_dir=arm_dir,
            default_skill=default_skill,
            manifest_dir=manifest_path.parent,
            timeout_seconds=float(task.get("timeout_seconds", args.timeout)),
            codex_bin=args.codex_bin,
            model=args.model,
            approve_for_me=args.approve_for_me,
            images=[
                safe_resolve(manifest_path.parent, image)
                for image in task.get("images", [])
            ],
        )
        result["task_id"] = task_id
        result["arm_id"] = arm_id
        runs.append(result)

    runs.sort(key=lambda item: (item["task_id"], item["arm_id"]))
    summary = aggregate(runs)
    payload = {
        "manifest": str(manifest_path),
        "run_root": str(run_root),
        "created_at": now_slug(),
        "runs": runs,
        "aggregate": summary,
    }
    (run_root / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_csv(run_root / "results.csv", runs)
    (run_root / "report.md").write_text(
        render_report(manifest, run_root, runs), encoding="utf-8"
    )
    print(json.dumps({"run_root": str(run_root), "aggregate": summary}, indent=2))
    return 0


def command_recompute(args: argparse.Namespace) -> int:
    run_root = Path(args.run_root).expanduser().resolve()
    results_path = run_root / "results.json"
    payload = read_json(results_path)
    runs = payload.get("runs")
    if not isinstance(runs, list):
        raise SystemExit("results.json has no runs array")
    for run in runs:
        events_path = Path(str(run["events_path"]))
        parsed = parse_events(events_path)
        run["command_runs"] = parsed["command_runs"]
        run["rework_rounds"] = parsed["failed_commands"]
    payload["aggregate"] = aggregate(runs)
    results_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_csv(run_root / "results.csv", runs)
    manifest_path = Path(str(payload["manifest"]))
    manifest = read_json(manifest_path)
    (run_root / "report.md").write_text(
        render_report(manifest, run_root, runs), encoding="utf-8"
    )
    print(json.dumps({"run_root": str(run_root), "aggregate": payload["aggregate"]}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="execute an isolated A/B manifest")
    run.add_argument("--manifest", required=True)
    run.add_argument("--out", required=True)
    run.add_argument(
        "--skill",
        default=str(Path(__file__).resolve().parents[1] / "SKILL.md"),
    )
    run.add_argument("--codex-bin", default="codex")
    run.add_argument("--model")
    run.add_argument("--timeout", type=float, default=240.0)
    run.add_argument("--seed", type=int, default=0)
    run.add_argument(
        "--task",
        action="append",
        help="run only the named task; repeatable",
    )
    run.add_argument(
        "--approve-for-me",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use Codex automatic approval inside each isolated workspace",
    )
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=command_run)

    recompute = subparsers.add_parser(
        "recompute", help="reparse saved events and rebuild metrics/report"
    )
    recompute.add_argument("--run-root", required=True)
    recompute.set_defaults(func=command_recompute)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if getattr(args, "timeout", 1) <= 0:
        parser.error("--timeout must be positive")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
