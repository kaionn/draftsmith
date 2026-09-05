#!/usr/bin/env python3
"""Aggregate privacy-minimal token cost per draftsmith role from a session transcript."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1
MAIN_ROLE = "main"
AGENT_ROLES = (
    "designer",
    "auditor",
    "consultant",
    "implementer",
    "reviewer-light",
)
OTHER_ROLE = "other"
ROLES = (MAIN_ROLE,) + AGENT_ROLES + (OTHER_ROLE,)
ROLE_PREFIX = "draftsmith:"
USAGE_FIELDS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)
NUMERIC_FIELDS = (
    "turns",
    "avg_context_tokens",
    "max_context_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "duration_seconds",
    "agents",
)


class CostError(RuntimeError):
    pass


class TranscriptStats:
    """Per-transcript token totals. Holds no prompt text, path or description."""

    def __init__(self) -> None:
        self.turns: int = 0
        self.context_total: int = 0
        self.max_context: int = 0
        self.output_tokens: int = 0
        self.cache_read_tokens: int = 0
        self.cache_creation_tokens: int = 0
        self.duration_seconds: int = 0
        self.first_timestamp: datetime | None = None

    def merge(self, other: "TranscriptStats") -> None:
        self.turns += other.turns
        self.context_total += other.context_total
        self.max_context = max(self.max_context, other.max_context)
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_creation_tokens += other.cache_creation_tokens
        self.duration_seconds += other.duration_seconds

    def as_dict(self, agents: int) -> dict[str, int]:
        avg = self.context_total // self.turns if self.turns else 0
        return {
            "turns": self.turns,
            "avg_context_tokens": avg,
            "max_context_tokens": self.max_context,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "duration_seconds": self.duration_seconds,
            "agents": agents,
        }


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    # Normalize to UTC so a transcript mixing naive and aware rows still compares.
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


def read_records(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise CostError(f"cannot read transcript: {exc}") from exc
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def usage_of(record: dict[str, Any]) -> dict[str, int] | None:
    if record.get("type") != "assistant":
        return None
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    values: dict[str, int] = {}
    for field in USAGE_FIELDS:
        raw = usage.get(field, 0)
        values[field] = raw if isinstance(raw, int) and not isinstance(raw, bool) else 0
    return values


def message_key(record: dict[str, Any]) -> str | None:
    message = record.get("message")
    if isinstance(message, dict):
        identifier = message.get("id")
        if isinstance(identifier, str) and identifier:
            return identifier
    identifier = record.get("uuid")
    if isinstance(identifier, str) and identifier:
        return identifier
    return None


def transcript_stats(records: Iterable[dict[str, Any]]) -> TranscriptStats:
    """Fold streaming chunks that share a message id, taking the max of each usage field."""
    turns: dict[str, dict[str, int]] = {}
    order: list[str] = []
    timestamps: list[datetime] = []
    for record in records:
        moment = parse_timestamp(record.get("timestamp"))
        if moment is not None:
            timestamps.append(moment)
        usage = usage_of(record)
        if usage is None:
            continue
        key = message_key(record)
        if key is None:
            continue
        if key not in turns:
            turns[key] = dict(usage)
            order.append(key)
            continue
        current = turns[key]
        for field in USAGE_FIELDS:
            current[field] = max(current[field], usage[field])
    stats = TranscriptStats()
    for key in order:
        usage = turns[key]
        context = (
            usage["input_tokens"]
            + usage["cache_creation_input_tokens"]
            + usage["cache_read_input_tokens"]
        )
        stats.turns += 1
        stats.context_total += context
        stats.max_context = max(stats.max_context, context)
        stats.output_tokens += usage["output_tokens"]
        stats.cache_read_tokens += usage["cache_read_input_tokens"]
        stats.cache_creation_tokens += usage["cache_creation_input_tokens"]
    if timestamps:
        stats.first_timestamp = min(timestamps)
        stats.duration_seconds = max(
            0, int((max(timestamps) - min(timestamps)).total_seconds())
        )
    return stats


def normalize_role(subagent_type: Any) -> str:
    if not isinstance(subagent_type, str):
        return OTHER_ROLE
    name = subagent_type
    if name.startswith(ROLE_PREFIX):
        name = name[len(ROLE_PREFIX):]
    return name if name in AGENT_ROLES else OTHER_ROLE


def agent_tool_uses(records: Iterable[dict[str, Any]]) -> list[tuple[str, str]]:
    """Ordered (tool_use_id, subagent_type) pairs for Agent launches in the main transcript."""
    launches: list[tuple[str, str]] = []
    for record in records:
        if record.get("type") != "assistant":
            continue
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use" or block.get("name") != "Agent":
                continue
            identifier = block.get("id")
            if not isinstance(identifier, str):
                continue
            payload = block.get("input")
            subagent_type = payload.get("subagent_type") if isinstance(payload, dict) else None
            pair = (identifier, subagent_type if isinstance(subagent_type, str) else "")
            if pair[0] not in {existing[0] for existing in launches}:
                launches.append(pair)
    return launches


def tool_result_agents(records: Iterable[dict[str, Any]]) -> dict[str, str]:
    """agentId -> tool_use_id, joined through the Agent tool_result rows."""
    mapping: dict[str, str] = {}
    for record in records:
        if record.get("type") != "user":
            continue
        result = record.get("toolUseResult")
        if not isinstance(result, dict):
            continue
        agent_id = result.get("agentId")
        if not isinstance(agent_id, str) or not agent_id:
            continue
        message = record.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                tool_use_id = block.get("tool_use_id")
                if isinstance(tool_use_id, str) and tool_use_id:
                    mapping[agent_id] = tool_use_id
                break
    return mapping


def read_meta_role(meta_path: Path) -> str | None:
    if not meta_path.is_file():
        return None
    try:
        value = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    agent_type = value.get("agentType")
    return normalize_role(agent_type) if isinstance(agent_type, str) else None


def subagent_files(transcript: Path) -> list[Path]:
    directory = transcript.with_suffix("") / "subagents"
    if not directory.is_dir():
        return []
    return sorted(directory.glob("agent-*.jsonl"))


def agent_id_of(path: Path) -> str:
    return path.stem[len("agent-"):]


def collect(transcript: Path) -> dict[str, Any]:
    """Aggregate role-level token cost. Emits numbers and role enums only."""
    if not transcript.is_file():
        raise CostError(f"transcript not found: {transcript}")
    main_records = read_records(transcript)
    role_stats: dict[str, TranscriptStats] = {}
    role_agents: dict[str, int] = {}

    def add(role: str, stats: TranscriptStats) -> None:
        role_stats.setdefault(role, TranscriptStats()).merge(stats)
        role_agents[role] = role_agents.get(role, 0) + 1

    main_stats = transcript_stats(main_records)
    add(MAIN_ROLE, main_stats)

    launches = agent_tool_uses(main_records)
    launch_roles = {identifier: subagent_type for identifier, subagent_type in launches}
    agent_to_tool_use = tool_result_agents(main_records)

    files = subagent_files(transcript)
    stats_by_file: dict[Path, TranscriptStats] = {
        path: transcript_stats(read_records(path)) for path in files
    }

    resolved: dict[Path, str] = {}
    used_tool_uses: set[str] = set()
    for path in files:
        agent_id = agent_id_of(path)
        tool_use_id = agent_to_tool_use.get(agent_id)
        if tool_use_id is not None and tool_use_id in launch_roles:
            resolved[path] = normalize_role(launch_roles[tool_use_id])
            used_tool_uses.add(tool_use_id)
    for path in files:
        if path in resolved:
            continue
        role = read_meta_role(path.with_name(f"{path.stem}.meta.json"))
        if role is not None:
            resolved[path] = role

    pending = [path for path in files if path not in resolved]
    spare = [identifier for identifier, _type in launches if identifier not in used_tool_uses]
    if pending and len(pending) == len(spare):
        started: list[tuple[datetime, str, Path]] = []
        undated: list[Path] = []
        for path in pending:
            moment = stats_by_file[path].first_timestamp
            if moment is None:
                undated.append(path)
            else:
                started.append((moment, path.name, path))
        dated = [entry[2] for entry in sorted(started, key=lambda entry: entry[:2])]
        undated.sort()
        for path, identifier in zip(dated + undated, spare):
            resolved[path] = normalize_role(launch_roles[identifier])
        pending = []

    unmapped = 0
    for path in files:
        role = resolved.get(path)
        if role is None:
            role = OTHER_ROLE
            unmapped += 1
        add(role, stats_by_file[path])

    total = TranscriptStats()
    for stats in role_stats.values():
        total.merge(stats)
    return {
        "schema_version": SCHEMA_VERSION,
        "roles": {
            role: role_stats[role].as_dict(role_agents[role])
            for role in ROLES
            if role in role_stats
        },
        "total": total.as_dict(len(files)),
        "unmapped_subagents": unmapped,
    }


def render_table(report: dict[str, Any]) -> str:
    header = ("role",) + NUMERIC_FIELDS
    rows: list[tuple[str, ...]] = [header]
    for role, values in report["roles"].items():
        rows.append((role,) + tuple(str(values[field]) for field in NUMERIC_FIELDS))
    totals = report["total"]
    rows.append(("total",) + tuple(str(totals[field]) for field in NUMERIC_FIELDS))
    widths = [max(len(row[index]) for row in rows) for index in range(len(header))]
    lines = [
        "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)) for row in rows
    ]
    lines.append(f"unmapped_subagents: {report['unmapped_subagents']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        report = collect(Path(args.transcript).expanduser())
    except CostError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, sort_keys=True, indent=2))
    else:
        print(render_table(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
