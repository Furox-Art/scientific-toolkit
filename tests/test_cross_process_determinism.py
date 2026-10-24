"""Cross-process determinism: the static catalog and tool specs must be stable.

The toolkit performs no scientific computation itself, so its determinism
surface is the registry it routes with: the repository catalog, the MCP tool
specifications and the routing table. Those are dumped in two fresh
interpreters with different ``PYTHONHASHSEED`` values and must be
byte-identical.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from functools import cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

CHILD = r"""
import json
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
sys.path.insert(0, str(repo_root))

from scientific_toolkit_mcp.catalog import catalog
from scientific_toolkit_mcp.server import TOOLS
from scientific_toolkit_mcp.tools import TOOL_ROUTES

payload = {
    "catalog": catalog(),
    "tools": TOOLS,
    "routes": list(TOOL_ROUTES),
}
print(json.dumps(payload, ensure_ascii=False))
"""


@cache
def _run_with_hash_seed(seed: str) -> str:
    env = {
        **os.environ,
        "PYTHONHASHSEED": seed,
        "PYTHONIOENCODING": "utf-8",
    }
    completed = subprocess.run(
        [sys.executable, "-c", CHILD, str(REPO_ROOT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def test_registry_is_byte_identical_across_hash_seeds() -> None:
    first = _run_with_hash_seed("0")
    second = _run_with_hash_seed("12345")
    assert first.strip()
    assert first.strip() == second.strip()


def test_workload_covers_the_whole_registry() -> None:
    payload = json.loads(_run_with_hash_seed("0"))
    assert len(payload["catalog"]) == 9
    assert len(payload["tools"]) == len(payload["routes"])
    names = [tool["name"] for tool in payload["tools"]]
    assert sorted(names) == sorted(payload["routes"])
    assert "toolkit_catalog" in names
    assert "nomosguard_decide" in names
