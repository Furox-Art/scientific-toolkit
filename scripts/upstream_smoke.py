"""Real upstream adapter smoke checks through MCP, one isolated CI job per package."""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from scientific_toolkit_mcp.server import handle
from scientific_toolkit_mcp.tools import BINS, MODULE_SERVERS

CASES = {
    "axiomize": ("axiomize", "axiomize_intake", {"idea":"How does sample size affect uncertainty?"}),
    "scientific-computing-system": ("cds", "cds_stats", {"values":[1,2,3,4,5]}),
    "scientific-computing-system-2.0": ("cds2", "cds2_stats", {"values":[1,2,3,4,5]}),
    "plan-auditor": ("plan-auditor", None, None),
    "quantum-reasoning-skill": ("quantum-reasoning", "quantum_skill_validate", {}),
    "axiomize-quantum-skills-2.0": ("axiomize-reason", "axiomize_reason_score",
                                  {"evidence":0.75,"verification":0.8}),
    "eq-layer": ("eq-layer", "eq_layer_route",
                 {"messages":[{"role":"user","content":"What does this result mean?"}],
                  "intent_mode":"heuristic"}),
    "literature-evidence-mcp": ("literature-evidence", "literature_evidence_verify_quote",
                                {"quote": "sample size affects uncertainty",
                                 "source_text": "In this study, sample size affects uncertainty.",
                                 "source_id": "smoke-doc"}),
}

MODULE_CASES = {
    "nomosguard": ("nomosguard", "nomosguard_decide",
                   {"claims": [{"kind": "exposure", "payload": {"service": "api"},
                                "evidence": "smoke evidence"}]}),
}

def request(tool, args):
    response = handle({"jsonrpc":"2.0","id":1,"method":"tools/call",
                       "params":{"name":tool,"arguments":args}})
    assert response and "result" in response, response
    result = response["result"]
    assert not result["isError"], result
    payload = json.loads(result["content"][0]["text"])
    assert payload["status"] == "COMMAND_SUCCEEDED", payload
    assert payload["exit_code"] == 0, payload
    assert payload.get("stdout") or payload.get("calls"), f"{tool}: empty adapter output"
    return payload

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("profile", choices=sorted(CASES | MODULE_CASES))
    profile = parser.parse_args().profile
    if profile in MODULE_CASES:
        binary, tool, args = MODULE_CASES[profile]
        envvar, module, import_name = MODULE_SERVERS[binary]
        executable = shutil.which(os.environ.get(envvar, sys.executable))
        assert executable, f"{profile}: missing interpreter"
        if envvar not in os.environ:
            assert importlib.util.find_spec(import_name), f"{profile}: missing module {import_name}"
        output = request(tool, args)
        print(f"PASS: {profile}, {tool}, real MCP stdio session exit {output['exit_code']}, "
              f"{len(output['calls'])} tool replies")
        print("Smoke pass is not proof of scientific validity or full client compatibility.")
        return
    binary, tool, args = CASES[profile]
    envvar, default = BINS[binary]
    executable = shutil.which(os.environ.get(envvar, default))
    assert executable, f"{profile}: missing CLI {default}"
    if profile == "plan-auditor":
        out = subprocess.run([executable, "--help"], text=True,
                             capture_output=True, check=True, timeout=30)
        assert "audit" in out.stdout
        r = handle({"jsonrpc":"2.0","id":2,"method":"tools/call",
                    "params":{"name":"plan_auditor_audit","arguments":{}}})
        assert r and r["result"]["isError"] and "DISABLED" in r["result"]["content"][0]["text"]
        print("PASS: plan-auditor installed; CLI responds; unauthorised audit fails closed.")
        print("No sealed scientific plan or completion verdict was tested.")
    else:
        output = request(tool, args)
        print(f"PASS: {profile}, {tool}, real process exit {output['exit_code']}, "
              f"output chars {len(output['stdout'])}")
    print("Smoke pass is not proof of scientific validity or full client compatibility.")

if __name__ == "__main__":
    main()
