"""Real published upstream CLI smoke checks through MCP, one isolated CI job per package."""
import argparse
import json
import os
import shutil
import subprocess
from scientific_toolkit_mcp.server import handle
from scientific_toolkit_mcp.tools import BINS

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
                  "intent_mode":"heuristic"})
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
    assert payload.get("stdout"), f"{tool}: empty CLI output"
    return payload

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("profile", choices=sorted(CASES))
    profile = parser.parse_args().profile
    binary, tool, args = CASES[profile]
    envvar, default = BINS[binary]
    executable = shutil.which(os.environ.get(envvar, default))
    assert executable, f"{profile}: missing published CLI {default}"
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
