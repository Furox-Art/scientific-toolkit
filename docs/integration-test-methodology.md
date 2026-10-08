# End-to-end integration test methodology

This document explains how to run the integration suite, what each test proves,
what it deliberately does **not** prove, and the exact environment the committed
results were captured in.

## Running the suite

From the repository root:

```sh
# The full suite: protocol unit tests plus the end-to-end integration tests
python -m unittest discover -s tests -v

# Only the end-to-end integration tests
python -m unittest discover -s tests/e2e -v
```

Both commands need the gateway importable. Either install it
(`python -m pip install -e .`) or run them from the repository root, which the
suite adds to `sys.path` itself.

### Environment the integration suite expects

The integration suite exercises **real installed upstream CLIs**. No upstream
executable is faked in `tests/e2e/`; every subprocess reaches an actual program.

| Tool | CLI executable | Override variable |
| --- | --- | --- |
| axiomize | `axiomize` | `SCITOOL_AXIOMIZE_BIN` |
| scientific-computing-system | `cds` | `SCITOOL_CDS_BIN` |
| scientific-computing-system-2.0 | `cds2` | `SCITOOL_CDS2_BIN` |
| plan-auditor | `plan-auditor` | `SCITOOL_AUDITOR_BIN` |
| quantum-reasoning-skill | `quantum-reasoning` | `SCITOOL_QUANTUM_BIN` |
| axiomize-quantum-skills-2.0 | `axiomize-reason` | `SCITOOL_REASON_BIN` |
| eq-layer | `eq-layer` | `SCITOOL_EQ_BIN` |

A missing tool is reported as a **KNOWN GAP** and the related assertions fail
with an explicit message naming the gap. A missing tool is never silently
skipped and never replaced by a fabricated result.

### The bundled `axiomize-reason` and the Axiomize CLI clash

`axiomize-quantum-skills-2.0` bundles its own Axiomize package and installs an
`axiomize-reason` console script. That bundled package must **not** be placed on
`PYTHONPATH`: doing so shadows the standalone `axiomize` installed in the main
environment, so the `axiomize` CLI would silently import the bundled copy and
report the wrong version.

Two mechanisms keep the two environments apart:

1. Point `SCITOOL_REASON_BIN` at the isolated environment's
   `axiomize-reason` executable.
2. Let that isolated interpreter resolve its own package through a `.pth` file
   in its own `site-packages`, rather than a global `PYTHONPATH`.

`scripts/refresh-availability.sh` follows both rules and deliberately does not
export `PYTHONPATH`. The test
`test_axiomize_model_runs_in_the_gateway_environment` fails if the `axiomize`
CLI on `PATH` ever reports a version that differs from the installed
distribution, which catches this class of shadowing.

## What each test group proves

### `UpstreamAvailabilityTests` — each tool is genuinely installed and usable

Each test performs a **real gateway tool call** and asserts on the actual
subprocess result: the program name, the real exit code, the
`COMMAND_SUCCEEDED` status, and content that could only come from that upstream
CLI. Nothing is mocked.

- `test_doctor_reports_seven_commands`, `test_catalog_lists_seven_distinct_repositories`,
  `test_gateway_exposes_eleven_local_tools` — the gateway advertises seven
  repositories and eleven local tools.
- `test_each_of_seven_repositories_has_installed_executable` — every upstream
  executable resolves on `PATH` (or through its override).
- `test_each_of_seven_repositories_has_installed_distribution` — every upstream
  distribution is importable by the interpreter that actually runs it. A
  distribution installed only in an isolated environment still counts.
- `test_axiomize_intake_runs_real_cli`, `test_cds_stats_runs_real_cli`,
  `test_cds2_stats_runs_real_cli`, `test_quantum_skill_validate_runs_real_cli`,
  `test_axiomize_reason_score_runs_real_cli`, `test_eq_layer_route_runs_real_cli`
  — six of the seven tools run their real CLI through the gateway.
- `test_axiomize_model_runs_real_cli_on_structured_request` — a real Model IR
  request reaches the standalone Axiomize CLI and its own validation verdict is
  `PASS`. The request is wrapped in a `model_ir` key and declares
  `schema_version` 1.0, which is what Axiomize requires; anything else is
  refused before a single check runs.
- `test_axiomize_model_runs_in_the_gateway_environment` — the CLI the gateway
  spawns reports the same version as the installed distribution, proving no
  `PYTHONPATH` shadowing.
- `test_plan_auditor_inspect_runs_real_cli_with_configured_workspace` — a real
  sealed workspace is built and inspected read-only.

### `CrossToolWorkflowTests` — real data flow between tools

One tool's own output becomes the next tool's own input. No value in these tests
is computed by the suite.

- `test_two_independent_engines_agree_on_the_same_data` — `cds` (pure Python)
  and `cds2` (NumPy/SciPy) are independent packages; the values **each reports
  for itself** must agree.
- `test_statistics_output_feeds_reason_scoring_tool` — the agreement of the two
  engines' own reported means becomes the `evidence` argument of
  `axiomize_reason_score`.
- `test_statistics_output_feeds_intent_router` — a sentence built from real
  `cds2` output is routed by `eq_layer_route`, and the router echoes the real
  computed numbers back.
- `test_full_local_stdio_session_across_seven_tools` — a real stdio subprocess
  session: `initialize`, notification, `tools/list`, then four real tool calls,
  verifying the notification correctly receives no response.

### `LocalStdioSecurityTests` — the local transport fails closed

Bad, hostile and malformed input is rejected with a clear error and never
crashes the gateway.

- Unknown tool (`-32602`) and unknown method (`-32601`) are protocol errors.
- Non-object arguments, unexpected keys, non-finite numbers, booleans-as-numbers,
  too-few values, oversized input are all `INVALID_ARGUMENT`.
- The `axiomize_model` action allowlist blocks heavy operations (`repair`, `fit`,
  `export`, `discover`).
- Scores outside the unit interval and boolean scores are rejected.
- `eq_layer_route` requires a user turn, known roles and no extra keys.
- `plan_auditor_audit` stays disabled by default, and the workspace guard is
  checked **before** the opt-in flag, so a misconfigured deployment cannot run
  project commands.
- A missing dependency reports `NOT_INSTALLED`, never a fabricated result. All
  seven binaries are verified to report `NOT_INSTALLED` when absent.
- Invalid JSON-RPC frames never raise; the server returns an error instead.

### `RemoteHttpSecurityTests` — the remote transport is a separate boundary

Run against a real `ThreadingHTTPServer` instance.

- `/health` is public; anonymous and wrong-token posts are `401` with a
  `WWW-Authenticate: Bearer` challenge.
- The authenticated remote inventory exposes **10** tools and hides
  `plan_auditor_audit`; `plan_auditor_inspect` remains available.
- `plan_auditor_audit` is denied remotely **even when** locally enabled — the
  HTTP safeguard is not overridden by `SCITOOL_ALLOW_AUDIT_EXECUTION=1`.
- Real upstream CLIs execute over HTTP (`toolkit_catalog`, `cds_stats`,
  `toolkit_doctor`).
- Unlisted browser origins are `403`; explicitly allowlisted origins pass.
- Wrong `Content-Type` is `415`; a missing MCP `Accept` header is `406`;
  SSE `GET` is `405`; notifications are `202`.
- Malformed JSON is a `400` JSON-RPC parse error **and** the process keeps
  serving subsequent requests.
- The HTTP entrypoint refuses to start without a bearer secret or an OAuth
  provider.

### `SdkClientInteropTests` — a real third-party MCP client

A real official MCP Python SDK client connects to a real authenticated HTTP
server, negotiates a session, enumerates the ten remote-safe tools, and calls
`toolkit_catalog` plus a real `cds_stats` CLI execution.

The suite is written against the current SDK generation and stays compatible
with older ones: the transport context manager yields two streams in current
releases and three in older ones, and the tool-error field was renamed from
`isError` to `is_error`. Both are handled defensively, and authentication uses
the SDK's own `create_mcp_http_client` helper so the gateway itself needs no
extra HTTP dependency.

These tests skip themselves, with a clear reason, if the official MCP SDK is not
installed.

## What this suite does not prove

- **Scientific correctness** of any upstream numerical result. A tool exiting 0
  proves the program ran, not that its answer is right.
- **Compatibility with any specific third-party MCP client** beyond the official
  Python SDK exercised here.
- **Behaviour of the live hosted deployment**, which needs the private bearer
  credential that must never be committed.
- **OAuth 2.1 sign-in** with an external identity provider, since no trusted
  authorization server is configured.
- That all seven dependencies fit a constrained host's memory limit.

## The availability report

`scripts/availability_report.py` writes a committed, machine-readable record of
a real run:

```sh
bash scripts/refresh-availability.sh
# or, equivalently:
python scripts/availability_report.py \
    --output tests/e2e/results/availability.json
```

The report contains, all read back from real subprocess calls:

- the environment (Python version, platform, gateway version, UTC timestamp);
- the gateway inventory (protocol version, server name, eleven tool names);
- the full `toolkit_doctor` output;
- for each of the seven repositories: the installed distribution version, the
  resolved executable path and its override variable, the CLI's own
  self-reported version, and the result of a real gateway capability call;
- six fail-closed checks, each recording the actual refusal and whether the
  expected error marker was present;
- an explicit `not_tested_here` list.

A missing tool is recorded as `KNOWN_GAP`. Nothing is inferred: every field
comes from an executed call.

## The runnable example

`examples/analysis_pipeline.py` is an independent, runnable workflow an
unrelated user can execute end to end:

```sh
python examples/analysis_pipeline.py
```

It runs eight stages through the gateway — availability check, research-idea
intake, two independent statistics engines, their cross-check, protocol
validation, evidence-based reasoning scoring, response routing, and independent
plan inspection — feeding each tool's real output into the next tool's real
input. Missing tools are reported as KNOWN GAPS and the affected stages are
skipped explicitly.

Its real captured output is committed at
[`examples/analysis-pipeline/README.md`](../examples/analysis-pipeline/README.md).
