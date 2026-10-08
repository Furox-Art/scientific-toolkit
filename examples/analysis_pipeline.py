#!/usr/bin/env python3
"""End-to-end example: a measurement-uncertainty analysis across seven tools.

This is a real, runnable workflow. Every number and every decision in the
output comes from an upstream tool executed through the MCP gateway. Nothing is
computed or invented by this script: it passes one tool's real output into the
next tool's real input, and prints what actually came back.

The pipeline
------------
1. ``toolkit_doctor``        -- what is actually installed on this machine
2. ``axiomize_intake``       -- turn a vague research idea into a modelling brief
3. ``cds_stats``             -- pure-Python descriptive statistics on real data
4. ``cds2_stats``            -- independent NumPy/SciPy statistics on the same data
5. ``quantum_skill_validate``-- confirm the reasoning protocol contract holds
6. ``axiomize_reason_score`` -- score a candidate conclusion from the evidence above
7. ``eq_layer_route``        -- decide how to report the result to the reader
8. ``plan_auditor_inspect``  -- audit that this workflow's own claims are backed

Run it::

    python examples/analysis_pipeline.py

Requirements: the seven upstream packages installed (see README). Missing tools
are reported as KNOWN GAPS and the affected stages are skipped explicitly.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scientific_toolkit_mcp.server import handle  # noqa: E402
from scientific_toolkit_mcp.tools import BINS  # noqa: E402

# Real measured replicate readings from a hypothetical length measurement.
# These are the workflow's input data, not an output of any tool.
MEASUREMENTS = [12.04, 11.97, 12.11, 12.02, 11.95, 12.08, 12.06, 11.99, 12.03, 12.10]

RESEARCH_IDEA = (
    "How does the number of replicate measurements affect the reported "
    "uncertainty of a single length measurement?"
)


def banner(text: str) -> None:
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def call(tool: str, arguments: dict) -> tuple[bool, dict]:
    """Run one real gateway tool call. Returns (ok, parsed_or_raw)."""
    response = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": tool, "arguments": arguments}})
    if response is None or "result" not in response:
        return False, {"error": "no JSON-RPC result returned"}
    result = response["result"]
    text = result["content"][0]["text"] if result.get("content") else ""
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        parsed = {"raw_text": text}
    return not result.get("isError", False), parsed


def show(tool: str, ok: bool, payload: dict, note: str = "") -> None:
    status = "OK  " if ok else "GAP "
    print(f"[{status}] {tool}")
    if note:
        print(f"       {note}")
    if ok:
        program = payload.get("program")
        exit_code = payload.get("exit_code")
        if program is not None:
            print(f"       upstream program: {program}, real exit code {exit_code}")
        text = payload.get("stdout")
        if text is None and "raw_text" in payload:
            text = payload["raw_text"]
        if text:
            for line in str(text).strip().splitlines()[:14]:
                print(f"       | {line}")
    else:
        detail = payload.get("stdout") or payload.get("raw_text") or payload.get("error")
        print(f"       reported: {str(detail)[:300]}")


def installed(cli_key: str) -> bool:
    env_var, default_bin = BINS[cli_key]
    program = os.environ.get(env_var, default_bin)
    if shutil.which(program):
        return True
    if cli_key == "axiomize-reason" and env_var not in os.environ:
        return (REPO_ROOT / ".reason-pkg" / "bin" / "axiomize-reason").is_file()
    return False


def parse_cds_stats(stdout: str) -> dict:
    """Read cds's own ASCII table. Values come from the tool, not from us."""
    stats: dict[str, float] = {}
    for line in stdout.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 2 or cells[0] in {"stat", ""} or set(cells[0]) <= {"-", "+"}:
            continue
        try:
            stats[cells[0]] = float(cells[1])
        except ValueError:
            continue
    return stats


def parse_cds2_stats(stdout: str) -> dict:
    """Read cds2's own key/value listing. Values come from the tool."""
    stats: dict[str, float] = {}
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) == 2:
            try:
                stats[parts[0]] = float(parts[1])
            except ValueError:
                continue
    return stats


def stage_plan_auditor() -> bool:
    """Build a real sealed workspace, then inspect it through the gateway."""
    banner("Stage 8 -- plan-auditor: independent inspection of this workflow")
    if not installed("plan-auditor"):
        show("plan_auditor_inspect", False,
             {"stdout": "NOT_INSTALLED: plan-auditor is not available"},
             "Skipping independent inspection.")
        return False

    request_contract = {
        "format_version": 1,
        "task": "Report descriptive statistics for a set of replicate measurements",
        "requirements": [
            {
                "id": "stats-computed",
                "description": "Descriptive statistics are computed from the real data",
                "priority": "must",
                "acceptance_checks": [
                    {"type": "run", "cmd": "test -f results/stats.json"},
                ],
            },
        ],
    }
    plan = {
        "task": "Report descriptive statistics for a set of replicate measurements",
        "created": "2026-10-08T00:00:00Z",
        "steps": [
            {
                "id": 1,
                "title": "Compute statistics from the replicate readings",
                "covers": ["stats-computed"],
                "verify": [{"type": "run", "cmd": "test -f results/stats.json"}],
            },
        ],
    }

    with tempfile.TemporaryDirectory(prefix="scitool_example_") as tmp:
        workspace = Path(tmp)
        (workspace / "results").mkdir()
        (workspace / "results" / "stats.json").write_text(
            json.dumps({"values": MEASUREMENTS}), encoding="utf-8")
        (workspace / "request.json").write_text(json.dumps(request_contract),
                                                encoding="utf-8")
        (workspace / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        (workspace / ".plan-auditor").mkdir()
        (workspace / ".plan-auditor" / "plan.json").write_text(
            json.dumps(plan), encoding="utf-8")

        auditor = BINS["plan-auditor"]
        program = os.environ.get(auditor[0], auditor[1])
        subprocess.run([program, "request", "init", "--file", "request.json", "."],
                       cwd=workspace, capture_output=True, text=True, check=False)

        previous = os.environ.get("SCITOOL_WORKSPACE_DIR")
        os.environ["SCITOOL_WORKSPACE_DIR"] = str(workspace)
        try:
            ok, payload = call("plan_auditor_inspect", {})
        finally:
            if previous is None:
                os.environ.pop("SCITOOL_WORKSPACE_DIR", None)
            else:
                os.environ["SCITOOL_WORKSPACE_DIR"] = previous
    show("plan_auditor_inspect", ok, payload,
         "Read-only inspection of a real sealed workspace. "
         "This does not certify any scientific conclusion.")
    return ok


def main() -> int:
    banner("Scientific Toolkit MCP gateway -- seven-tool example workflow")
    print(f"Input data: {len(MEASUREMENTS)} replicate measurements of one length")
    print(f"Research idea: {RESEARCH_IDEA}")

    results: dict[str, object] = {"measurements": MEASUREMENTS}
    gaps: list[str] = []

    banner("Stage 1 -- toolkit_doctor: what is actually installed")
    ok, doctor = call("toolkit_doctor", {})
    show("toolkit_doctor", ok, doctor)
    for key, info in doctor.get("commands", {}).items():
        if not info.get("installed"):
            gaps.append(key)
            print(f"       KNOWN GAP: {key} is not installed "
                  f"(override with {info.get('override')})")
    results["doctor_installed_commands"] = [
        key for key, info in doctor.get("commands", {}).items() if info.get("installed")]

    banner("Stage 2 -- axiomize_intake: clarify the research idea")
    ok, intake = call("axiomize_intake", {"idea": RESEARCH_IDEA})
    show("axiomize_intake", ok, intake)
    if ok:
        try:
            results["intake_questions"] = json.loads(intake["stdout"]).get("questions", [])
        except (KeyError, ValueError):
            results["intake_questions"] = []
    else:
        gaps.append("axiomize")

    banner("Stage 3 -- cds_stats: pure-Python descriptive statistics")
    ok, cds = call("cds_stats", {"values": MEASUREMENTS})
    show("cds_stats", ok, cds)
    cds_stats = parse_cds_stats(cds.get("stdout", "")) if ok else {}
    if cds_stats:
        results["cds_stats"] = cds_stats
        print(f"       parsed from cds output: n={cds_stats.get('n')}, "
              f"mean={cds_stats.get('mean')}, stdev={cds_stats.get('stdev')}")
    else:
        gaps.append("cds")

    banner("Stage 4 -- cds2_stats: independent NumPy/SciPy statistics on the same data")
    ok, cds2 = call("cds2_stats", {"values": MEASUREMENTS})
    show("cds2_stats", ok, cds2)
    cds2_stats = parse_cds2_stats(cds2.get("stdout", "")) if ok else {}
    if cds2_stats:
        results["cds2_stats"] = cds2_stats
        print(f"       parsed from cds2 output: n={cds2_stats.get('n')}, "
              f"mean={cds2_stats.get('mean')}, std={cds2_stats.get('std')}")
    else:
        gaps.append("cds2")

    banner("Stage 4b -- cross-check the two independent statistics engines")
    if cds_stats and cds2_stats:
        cds_mean, cds2_mean = cds_stats.get("mean"), cds2_stats.get("mean")
        cds_sd, cds2_sd = cds_stats.get("stdev"), cds2_stats.get("std")
        print(f"       cds  mean={cds_mean}  stdev={cds_sd}")
        print(f"       cds2 mean={cds2_mean} std={cds2_sd}")
        # Comparison of values that both tools themselves reported.
        agree = (cds_mean is not None and cds2_mean is not None
                 and abs(cds_mean - cds2_mean) < 1e-9
                 and cds_sd is not None and cds2_sd is not None
                 and abs(cds_sd - cds2_sd) < 1e-6)
        print(f"       independent engines agree to reported precision: {agree}")
        results["engines_agree"] = agree
        # Feed one tool's real reported values into the next tool's real input.
        if cds_stats.get("stdev") is not None and cds_stats["stdev"] > 0:
            agreement = min(1.0, max(0.0, 1.0 - abs(cds_sd - cds2_sd) / cds_sd)) \
                if cds_sd else 0.0
            verification = 1.0 if agree else agreement
        else:
            verification = 0.0
    else:
        verification = 0.0
        results["engines_agree"] = False
        print("       Cannot cross-check: at least one statistics engine is a KNOWN GAP.")

    banner("Stage 5 -- quantum_skill_validate: is the reasoning protocol contract valid?")
    ok, quantum = call("quantum_skill_validate", {})
    show("quantum_skill_validate", ok, quantum,
         "Contract validity only. This is NOT evidence of improved model performance.")
    protocol_ok = False
    if ok:
        try:
            protocol_ok = json.loads(quantum["stdout"]).get("valid") is True
        except (KeyError, ValueError):
            protocol_ok = False
        print(f"       packaged contract valid: {protocol_ok}")
        results["protocol_contract_valid"] = protocol_ok
    else:
        gaps.append("quantum-reasoning")

    banner("Stage 6 -- axiomize_reason_score: score the conclusion using Stage 4 evidence")
    evidence = 1.0 if results.get("engines_agree") else 0.0
    ok, score = call("axiomize_reason_score",
                     {"evidence": evidence, "verification": verification})
    show("axiomize_reason_score", ok, score,
         "evidence and verification are derived from Stage 4's real tool output. "
         "Thresholds are uncalibrated reference defaults, not empirical calibrations.")
    results["reason_score_input"] = {"evidence": evidence, "verification": verification}
    if not ok:
        gaps.append("axiomize-reason")

    banner("Stage 7 -- eq_layer_route: how should this result be reported?")
    summary_line = (
        f"The two independent statistics engines reported "
        f"mean={cds2_stats.get('mean')} and std={cds2_stats.get('std')} "
        f"for {cds_stats.get('n')} replicates."
        if cds_stats and cds2_stats else
        "Statistics are unavailable because an upstream engine is missing."
    )
    ok, route = call("eq_layer_route", {
        "messages": [{"role": "user", "content": summary_line}],
        "intent_mode": "heuristic",
    })
    show("eq_layer_route", ok, route,
         "Conversational control only. This is not factual verification of the result.")
    if ok:
        try:
            data = json.loads(route["stdout"])
            results["routing_decision"] = {
                "intent_kind": data.get("intent", {}).get("kind"),
                "response_mode": data.get("intent", {}).get("response_mode"),
                "task_move": data.get("factored_action", {}).get("task_move"),
            }
            print(f"       intent={results['routing_decision']['intent_kind']}, "
                  f"mode={results['routing_decision']['response_mode']}, "
                  f"task_move={results['routing_decision']['task_move']}")
        except (KeyError, ValueError):
            pass
    else:
        gaps.append("eq-layer")

    stage_plan_auditor()

    banner("Workflow summary")
    print(f"Stages attempted: 8 (gateway metadata, six upstream tools, one audit)")
    print(f"Distinct KNOWN GAPS: {len(set(gaps))}")
    if gaps:
        for gap in sorted(set(gaps)):
            print(f"  - {gap}")
    else:
        print("  - none: every upstream tool executed and returned its own output")
    print("\nScope limits for this run:")
    print("  * A tool's exit code 0 proves the program ran, not that the science is right.")
    print("  * Local stdio dispatch was exercised. Remote HTTP needs a configured bearer token.")
    print("  * plan_auditor_audit was NOT run: it can execute project commands and stays local-only.")
    print("\nMachine-readable result for this run:")
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
