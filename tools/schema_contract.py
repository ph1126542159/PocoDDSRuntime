#!/usr/bin/env python3
"""Create immutable, provider-owned Runtime schema contract documents."""

from __future__ import annotations

import json
import re
from pathlib import Path


IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{2,127}$")
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def definition(kind: str) -> dict:
    common = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "additionalProperties": False,
        "required": ["id"],
        "properties": {"id": {"type": "string", "minLength": 1}},
    }
    if kind in {"message", "event", "command"}:
        common["properties"]["timestampMicroseconds"] = {"type": "integer", "minimum": 0}
        common["properties"]["payload"] = {"type": "object"}
    elif kind == "configuration":
        common["properties"]["enabled"] = {"type": "boolean"}
    else:
        common["properties"]["operation"] = {"type": "string", "minLength": 1}
        common["properties"]["request"] = {"type": "object"}
        common["properties"]["response"] = {"type": "object"}
    return common


def scaffold_command(args) -> int:
    if not IDENTIFIER.fullmatch(args.subject):
        raise ValueError(f"invalid schema subject: {args.subject}")
    if not IDENTIFIER.fullmatch(args.owner):
        raise ValueError(f"invalid schema owner: {args.owner}")
    if not SEMVER.fullmatch(args.version):
        raise ValueError(f"schema version must be semantic x.y.z: {args.version}")
    output = Path(args.output).resolve()
    if output.exists() and not args.force:
        raise FileExistsError(f"refusing to overwrite schema contract: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schemaVersion": 1,
        "subject": args.subject,
        "version": args.version,
        "kind": args.kind,
        "format": "json-schema-draft-07",
        "compatibility": args.compatibility,
        "owner": args.owner,
        "definition": definition(args.kind),
    }
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(output)
    print(json.dumps({
        "schemaVersion": 1,
        "operation": "schema-scaffold",
        "subject": args.subject,
        "version": args.version,
        "owner": args.owner,
        "path": str(output),
    }, indent=2))
    return 0

