# Furox Scientific Toolkit — MCP Gateway

**Provider-neutral Model Context Protocol gateway for seven existing Furox-Art public repositories.**
The upstream packages stay independent, with their original names and version histories.
This repository is an integration hub, not a merge of source trees.

**Status:** local stdio and authenticated stateless Streamable HTTP transports
are implemented. The public Render deployment at
[`https://scientific-toolkit.onrender.com/health`](https://scientific-toolkit.onrender.com/health)
has been verified on 2026-10-08: 7 installed CLI executables and **12/12
authenticated loopback MCP HTTP startup checks passed**, including six safe
scientific CLI adapter calls. This proves deployment plumbing, **not**
scientific correctness or external Claude/ChatGPT client login. OAuth
issuer/JWKS remains **not configured**.

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

**Any compatible local stdio MCP client:** add this server to your MCP
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

## Remote MCP: provider-neutral Streamable HTTP

The 7-repository catalog is available through compatible remote MCP clients using
`POST /mcp` (stateless JSON-RPC), when authenticated. `GET /health` is public.
A Render deployment currently serves `https://scientific-toolkit.onrender.com/mcp`;
use the private credential configured in Render and **never publish that token**.
To run your own instance instead:

```sh
# Generate a long random secret outside the repo and store it as a provider secret.
# Supply SCITOOL_MCP_BEARER_TOKEN through environment configuration.
python -m scientific_toolkit_mcp.http_server
```

Required variable: `SCITOOL_MCP_BEARER_TOKEN` (nonempty, kept outside Git).
Optional variables: `PORT` (default `8000`) and `SCITOOL_ALLOWED_ORIGINS`
(comma-separated exact origin URLs). **No web origin is allowed by default.**
Non-browser clients normally omit `Origin`; browser-origin requests require a
configured allowlist entry and receive restricted CORS headers. Do not put
bearer secrets in browser JavaScript or check them into a Git repository.
Use TLS/HTTPS at the hosting reverse proxy and restrict access to trusted users.

Remote clients must support **MCP Streamable HTTP and an explicit bearer-token
header**. Use the URL `https://YOUR-HOST/mcp` and set
`Authorization: Bearer YOUR_SECRET` in that client's supported configuration.
Some clients require OAuth discovery/registration instead and therefore **cannot
connect directly** to this bearer-only server without an OAuth-compatible proxy.
This is a client capability distinction, not a Claude/ChatGPT/Cursor restriction.

The `toolkit_catalog` covers all seven repositories. Authenticated HTTP clients
may call the **read-only** `plan_auditor_inspect` only after the administrator
configures `SCITOOL_WORKSPACE_DIR` to a trusted existing project directory.
`plan_auditor_audit` can execute arbitrary project verification code and therefore
remains **local-only** (10 remote tools out of 11 local tools). Setting
`SCITOOL_ALLOW_AUDIT_EXECUTION=1` does **not** override this HTTP safeguard. Missing upstream CLI packages return
`NOT_INSTALLED`, never a fabricated PASS. Install the desired upstream packages
in your deployment and use isolated environments for colliding Axiomize CLIs.
No hosting fees are necessary to use the local stdio gateway.

### Portability

- Local: Claude Desktop, Cursor, Codex, and other stdio-capable MCP clients
  (configure each with its own supported launcher settings).
- Remote: any Streamable-HTTP MCP client that accepts a custom bearer header.
- Model-agnostic: the MCP server performs no proprietary LLM calls or inference.
- Cross-application compatibility still requires live client-specific testing.

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
the HTTP gateway requires authentication and never exposes the executable audit tool.
It exposes read-only plan inspection only for a configured trusted workspace.

## Scope, evidence, and limitations

- Axiomize `model` operations require the actual upstream Model IR request; the
  gateway does not invent missing model assumptions or validation outcomes.
- The two numerical packages have independent statistics adapters; their
  outputs and numerical algorithms are not silently conflated.
- Each subprocess response includes exit code and stdout. Nonzero exit codes
  are MCP errors, and `UNKNOWN` is never promoted to a successful verification.
- The bundled reasoning tool's thresholds remain uncalibrated reference defaults.
- Any compatible AI client can serve as an **orchestrator**, not the validator:
  scientific claims still require reproducible numerical and empirical evidence.
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

## Independent integration evidence

Three CI suites provide progressively stronger, but limited, verification:

1. [Protocol/unit tests](https://github.com/Furox-Art/scientific-toolkit/actions/workflows/tests.yml)
   check stdio and authenticated HTTP handling, argument validation, safe defaults,
   and fail-closed errors. Fake CLI tests are plumbing tests, not scientific evidence.
2. [Published upstream package smoke checks](https://github.com/Furox-Art/scientific-toolkit/actions/workflows/real-upstream.yml)
   install all seven distributions separately and invoke their real CLIs through
   the gateway. The Plan Auditor profile checks the installed CLI and refusal
   to audit an unconfigured plan, *not* successful verification of research.
   This workflow also checks the live Render `/health` route and ensures that
   unauthenticated MCP tool calls receive HTTP 401.
3. [Official SDK interoperability](https://github.com/Furox-Art/scientific-toolkit/actions/workflows/sdk-client.yml)
   starts a temporary authenticated HTTP server, connects with the official MCP
   Python client, negotiates a session, enumerates the ten remote-safe tools,
   and calls `toolkit_catalog`. A generated CI-only token is used.

**Deployment scope:** CI tests both isolated packages and all seven installed
in one environment. The live Render service also passed 12/12 authenticated
HTTP tests using its own private bearer credential over loopback; this
includes six tool-execution paths and the seven-CLI availability check.
No external ChatGPT/Claude OAuth sign-in was tested. The optional OAuth
resource verifier is implemented, but a trusted authorization server
must still be connected before OAuth-based clients can log in. Never
publish or transmit the production bearer secret in GitHub or screenshots.

## Deploy all seven upstream packages on Render

The currently published Render service originally installed only the MCP gateway
with `pip install -e .`. This repository now includes a separate installation
script that installs six upstream distributions into the system environment and
the bundled Axiomize variant into an isolated package directory. To apply this to the
**existing** service, set its **Build Command** in Render to:

```sh
bash scripts/render-build.sh
```

Keep its **Start Command** unchanged:

```sh
python -m scientific_toolkit_mcp.http_server
```

Do **not** replace or reveal the existing `SCITOOL_MCP_BEARER_TOKEN`.
Rebuild/redeploy the existing free service after changing the build command.
The [full-stack installation workflow](https://github.com/Furox-Art/scientific-toolkit/actions/workflows/full-stack-install.yml)
checks seven real CLI invocations in one CI environment. That does not prove all
dependencies fit the Render Free 512 MB runtime limit or that production has
installed them: inspect Render build logs and run authenticated calls separately.
If the host runs out of memory, use separate workers or a larger instance rather
than claiming all seven are running.

## Optional OAuth 2.1 resource-server support

The public HTTP gateway supports **opt-in verification** of RS256-signed OAuth
access tokens from an actual independently configured identity provider. It
exposes `/.well-known/oauth-protected-resource/mcp` and includes protected
resource metadata in unauthorized responses **only when configured**.

The OAuth verifier requires `pip install -e '.[oauth]'` (included in the Render
build script) and all of these private Render environment settings:

| Environment variable | Configuration |
| --- | --- |
| `SCITOOL_OAUTH_ISSUER` | Trusted provider's HTTPS issuer URI |
| `SCITOOL_OAUTH_JWKS_URI` | Provider's HTTPS public JWKS endpoint |
| `SCITOOL_OAUTH_RESOURCE_URI` | `https://scientific-toolkit.onrender.com/mcp` |
| `SCITOOL_OAUTH_REQUIRED_SCOPE` | `mcp:tools` (provider must issue it) |

The gateway checks signature, audience, issuer, subject, expiration and scope,
and still recognizes the administrator's original bearer token. The server
does **not** issue tokens, run an OAuth consent screen or register clients.
A production identity provider must separately support proper OAuth 2.1,
PKCE, client registration/metadata and audience-bound access tokens.
An OAuth login via Claude or ChatGPT is **not yet confirmed** and must not
be advertised as active without a real IdP and app-specific authentication test.

## Python package and PyPI publishing

The gateway's Python distribution is named `furox-scientific-toolkit-mcp`
(version `0.1.0` in the repository), with import name `scientific_toolkit_mcp`.
**Do not assume it is already available on PyPI**: publication requires a successful
release and the maintainer's Trusted Publisher registration.

The token-free GitHub Actions release workflow includes tests, sdist/wheel
building, metadata validation, and an installed-wheel smoke test. See
[PyPI publishing setup](docs/pypi-publishing.md) for the exact publisher fields
and release procedure.

Installing the gateway does not install the seven upstream scientific tools:
use `toolkit_doctor` to distinguish available programs from missing ones.

## Repository and license

Project: https://github.com/Furox-Art/scientific-toolkit

The MCP gateway is licensed under **Apache License 2.0**, as recorded in the
repository root `LICENSE`. The seven upstream repositories retain their own
independent licenses, names and version histories. Public Render health and
anonymous access controls have been checked by CI; authorized production calls
against upstream scientific programs have not yet been confirmed.
