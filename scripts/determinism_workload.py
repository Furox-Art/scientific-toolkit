"""Deterministic catalog/tool-routing workload sampled by the determinism matrix."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))

    from scientific_toolkit_mcp.catalog import catalog
    from scientific_toolkit_mcp.server import TOOLS
    from scientific_toolkit_mcp.tools import TOOL_ROUTES

    payload: dict[str, Any] = {
        "catalog": catalog(),
        "tools": TOOLS,
        "routes": {
            name: {
                "tools": sorted(entry[0]),
                "handler": getattr(entry[1], "__name__", type(entry[1]).__name__),
            }
            for name, entry in TOOL_ROUTES.items()
        },
    }
    if not payload["catalog"] or not payload["tools"] or not payload["routes"]:
        raise SystemExit("workload produced an empty registry; it is vacuous")
    artifact_dir = os.environ.get("DETERMINISM_ARTIFACT_DIR")
    if artifact_dir:
        Path(artifact_dir, "payload.json").write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
            newline="\n",
        )
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
