# Furox Scientific Toolkit — MCP Gateway

**One local Model Context Protocol gateway for seven existing Furox-Art public repositories.**
The upstream packages stay independent, with their original names and version histories.
This repository is an integration hub, not a merge of source trees.

**Status:** local MCP stdio implementation + adapter/transport tests. A remotely hosted
HTTPS endpoint, deployment, and end-to-end verification against all live upstream packages
are **not** included or claimed. Upstream packages must be installed separately.

## Seven upstream repositories

| Public repository | Role | MCP tool(s) |
| --- | --- | --- |
| [axiomize](https://github.com/Furox-Art/axiomize) | Scientific models and verification | `axiomize_intake`, `axiomize_model` |
| [scientific-computing-system](https://github.com/Furox-Art/scientific-computing-system) | Pure-Python numerical computation | `cds_stats` |
| [scientific-computing-system-2.0](https://github.com/Furox-Art/scientific-computing-system-2.0) | NumPy/SciPy computation | `cds2_stats` |
| [plan-auditor](https://github.com/Furox-Art/plan-auditor) | Independent execution verification | `plan_auditor_inspect`, `plan_auditor_audit` |
| [quantum-reasoning-skill](https://github.com/Furox-Art/quantum-reasoning-skill) | Reasoning protocol/skill inspector | `quantum_skill_validate` |
| [axiomize-quantum-skills-2.0](https://github.com/Furox-Art/axiomize-quantum-skills-2.0) | Bundled modeling + branch-scoring controller | `axiomize_reason_score` |
| [eq-layer](https://github.com/Furox-Art/eq-layer) | Response-control and intent routing | `eq_layer_route` |

`axiomize-quantum-skills-2.0` already packages Axiomize, so this hub does **not**
register its Axiomize MCP tools a second time. `quantum-reasoning-skill` is a skill
protocol, not a quantum computer or a validated performance improvement. EQ-Layer is
communication-control infrastructure, not a scientific data validator.

## Local installation

Requires **Python 3.10+**. From this repository directory:

```sh
python -m pip install -e .
# Select upstream packages you actually need:
python -m pip install axiomize scientific-computing-system
python -m pip install scientific-computing-system-2.0
python -m pip install plan-auditor quantum-reasoning-skill eq-layer
# The bundled Axiomize/quantum package may replace the standalone
# Axiomize CLI. Install it in a separate environment (below).
python -m scientific_toolkit_mcp
```

To enable the bundled reasoning controller separately, create a dedicated virtual
environment and install `axiomize-quantum-skills-2.0` there. Then set
`SCITOOL_REASON_BIN` to that environment's `axiomize-reason` executable.
This avoids the shared `axiomize` CLI clashing with standalone Axiomize.

The final command starts an **MCP stdio process**. It waits for JSON-RPC requests on
stdin and writes JSON-RPC only to stdout; it is not a text chat or HTTP server.

**Claude Desktop and other local stdio MCP clients:** add this server to your MCP
configuration (adjust `python` or use the absolute path to the correct venv Python):

```json
{
  "mcpServers": {
    "scientific-toolkit": {
      "command": "python",
      "args": ["-m", "scientific_toolkit_mcp"]
    }
  }
}
```

In a running MCP client, call `toolkit_catalog` to see all seven repos, and
`toolkit_doctor` to check which upstream CLIs are installed. Missing packages
produce explicit `NOT_INSTALLED` errors rather than fabricated data.

## Optional executable overrides

For independent virtual environments, set environment variables to **executable
paths only**, not commands with arguments:

| Environment variable | Default executable |
| --- | --- |
| `SCITOOL_AXIOMIZE_BIN` | `axiomize` |
| `SCITOOL_CDS_BIN` | `cds` |
| `SCITOOL_CDS2_BIN` | `cds2` |
| `SCITOOL_AUDITOR_BIN` | `plan-auditor` |
| `SCITOOL_QUANTUM_BIN` | `quantum-reasoning` |
| `SCITOOL_REASON_BIN` | `axiomize-reason` |
| `SCITOOL_EQ_BIN` | `eq-layer` |

### Verification safety

The Plan Auditor `audit` operation executes the plan's configured checks. It is
**disabled by default**. To opt in for a trusted local workspace, configure both:

- `SCITOOL_WORKSPACE_DIR`: an already-existing trusted project directory
- `SCITOOL_ALLOW_AUDIT_EXECUTION=1`: grants the audit tool permission to run those checks

`plan_auditor_inspect` also requires the configured workspace but does not
assert task completion. All executable commands use fixed allowlisted command
forms and `subprocess` **without a shell**. No user-selected paths or arbitrary
command strings are accepted via MCP. Restrict access to the client session:
this gateway is designed for **local stdio**, not untrusted public exposure.

## Scope, evidence, and limitations

- Axiomize `model` operations require the actual upstream Model IR request; the
  gateway does not invent missing model assumptions or validation outcomes.
- The two numerical packages have independent statistics adapters; their
  outputs and numerical algorithms are not silently conflated.
- Each subprocess response includes exit code and stdout. Nonzero exit codes
  are MCP errors, and `UNKNOWN` is never promoted to a successful verification.
- The bundled reasoning tool's thresholds remain uncalibrated reference defaults.
- Claude is an optional **client/orchestrator**, not the validator: scientific
  claims still require reproducible numerical and empirical evidence.
- This repo does not represent an incorporated legal company or promise Claude
  startup program eligibility. No deployment costs have been paid.

## Tests

```sh
python -m unittest discover -s tests -v
```

CI exercises JSON-RPC initialization, list/call, seven-repository catalog,
input validation, fail-closed audit defaults, upstream failures, and fake-CLI
transport. The fake executable tests validate the **integration plumbing**;
actual upstream numerical correctness remains the responsibility of each
repository's own tests and a future cross-package integration suite.

## Repository and license

Project: https://github.com/Furox-Art/scientific-toolkit

The MCP gateway is licensed under **Apache License 2.0**, as recorded in the
repository root `LICENSE`. The seven upstream repositories retain their own
independent licenses, names and version histories. The local MCP service is
**not** a publicly deployed HTTPS endpoint.
