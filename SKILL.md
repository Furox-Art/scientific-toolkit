---
name: scientific-toolkit
description: "Use when a task needs one MCP entry point to nine Furox scientific tools (axiomize, cds, cds2, plan-auditor, quantum-reasoning, axiomize-reason, eq-layer, literature-evidence-mcp, nomosguard), locally over stdio or remotely over authenticated Streamable HTTP. It is an integration gateway, not a new scientific engine. Installed from PyPI as `scientific-toolkit-mcp`."
argument-hint: "<scientific workflow, repository, or upstream tool to invoke>"
metadata:
  version: "0.4.0"
---

# Furox Scientific Toolkit — MCP Gateway

A provider-neutral MCP gateway that exposes nine independent Furox-Art projects
through one server. Upstream packages keep their own names, versions, and release
histories; this repository is an integration hub, not a merged source tree.

## Names

| Surface | Name |
| --- | --- |
| Repository | `scientific-toolkit` |
| PyPI project | `scientific-toolkit-mcp` |
| Import | `scientific_toolkit_mcp` |
| CLI | `scientific-toolkit-mcp` |
| Version | 0.4.0 (published on PyPI) |

`pip install scientific-toolkit-mcp` installs the `scientific-toolkit-mcp`
command. No PyPI project is named `scientific-toolkit`. The former
`furox-scientific-toolkit-mcp` project was removed and is no longer installable.

## When to use this skill

- You want one MCP client configuration for several scientific and verification
  tools instead of installing nine separate servers.
- You need to discover which upstream executables and module servers are installed before running anything.
- You want local stdio by default, or authenticated Streamable HTTP for a trusted
  remote deployment.

## Install

Requires Python 3.11+.

```bash
pip install scientific-toolkit-mcp
# or from a source checkout: pip install -e .

# Install only the upstream packages you need:
pip install axiomize scientific-computing-system
pip install scientific-computing-system-2.0
pip install plan-auditor quantum-reasoning-skill eq-layer
pip install literature-evidence-mcp nomosguard
```

The bundled `axiomize-quantum-skills-2.0` may replace the standalone Axiomize CLI;
install it in a separate environment and point `SCITOOL_REASON_BIN` at that
environment's `axiomize-reason` executable.

## MCP client configuration (stdio)

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

Start with `toolkit_catalog` to list the nine repositories and `toolkit_doctor`
to see which upstream executables and module servers are available. Missing packages return explicit
`NOT_INSTALLED` errors; they never produce fabricated results.

## Upstream tools

| Repository | Role | MCP tools |
|---|---|---|
| axiomize | Scientific models and verification | `axiomize_intake`, `axiomize_model` |
| scientific-computing-system | Pure-Python numerical computation | `cds_stats` |
| scientific-computing-system-2.0 | NumPy/SciPy computation | `cds2_stats` |
| plan-auditor | Independent execution verification | `plan_auditor_inspect`, `plan_auditor_audit` |
| quantum-reasoning-skill | Reasoning protocol/skill inspector | `quantum_skill_validate` |
| axiomize-quantum-skills-2.0 | Bundled modeling and branch scoring | `axiomize_reason_score` |
| eq-layer | Response control and intent routing | `eq_layer_route` |
| literature-evidence-mcp | Literature search and evidence-provenance checks | `literature_evidence_search`, `literature_evidence_verify_quote` |
| nomosguard | Deterministic security reasoning and fail-closed policy gate | `nomosguard_decide` |

Axiomize tools are not registered twice when the bundled quantum package is used.
`quantum-reasoning-skill` is a skill protocol, not a quantum computer, and EQ-Layer
is communication-control infrastructure, not a scientific data validator.

## Executable overrides

Each variable takes an executable path only, never a command with arguments:
`SCITOOL_AXIOMIZE_BIN`, `SCITOOL_CDS_BIN`, `SCITOOL_CDS2_BIN`,
`SCITOOL_AUDITOR_BIN`, `SCITOOL_QUANTUM_BIN`, `SCITOOL_REASON_BIN`,
`SCITOOL_EQ_BIN`, `SCITOOL_LIT_EVIDENCE_BIN`, `SCITOOL_NOMOSGUARD_BIN`.
The NomosGuard override names the interpreter that runs `-m nomosguard.mcp_stdio`.

## Remote HTTP

Run `python -m scientific_toolkit_mcp.http_server` with
`SCITOOL_MCP_BEARER_TOKEN` set to a long random secret stored outside Git.
Optional: `PORT` (default 8000), `SCITOOL_ALLOWED_ORIGINS` (exact origins;
none allowed by default). Use TLS at the reverse proxy and never put the bearer
token in browser JavaScript. Some clients require OAuth discovery and cannot
connect directly to a bearer-only server; that is a client capability limitation,
not a scientific limitation. OAuth issuer/JWKS is not configured in this project.

Remote safeguards: `plan_auditor_audit` can execute project code and is
local-only; `plan_auditor_inspect` is available remotely only after the
administrator sets `SCITOOL_WORKSPACE_DIR` to a trusted project directory.
Thirteen of the fourteen tools are available remotely.

## Working rules

- Treat `NOT_INSTALLED` and `BAD_CONFIGURATION` as real answers; do not retry with
  a fabricated substitute.
- Isolate colliding Axiomize installations; more than one provider on `sys.path`
  fails loudly by design.
- The public Render deployment proves deployment plumbing, not scientific
  correctness or end-to-end client login.
- Report which upstream executable or module and version served each result.

## References

- Repository: https://github.com/Furox-Art/scientific-toolkit
- PyPI: https://pypi.org/project/scientific-toolkit-mcp/
- Website: https://www.furoxscientifictoolkit.lovie.me/
