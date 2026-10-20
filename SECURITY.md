# Security Policy

`scientific-toolkit-mcp` is an MCP gateway. It exposes a local stdio
transport and an authenticated HTTP transport, and it invokes separately
installed upstream scientific CLIs. This policy covers the gateway code and
packaging in this repository, not the seven upstream projects.

## Supported versions

| Version | Supported |
| --- | --- |
| `0.2.x` | Yes |
| `< 0.2` | No |

Security fixes target the `0.2.x` release line. Reproduce a report against the
latest `0.2.x` release before submitting it. The upstream packages have their
own release and security policies.

## Reporting a vulnerability

Use GitHub private vulnerability reporting:

<https://github.com/Furox-Art/scientific-toolkit/security/advisories/new>

Do not open a public issue for a suspected vulnerability. If private reporting
is unavailable to you, open a regular issue that asks for a private channel and
contains no exploit details.

Please include, when available:

- the gateway version (`scientific_toolkit_mcp.__version__` or the PyPI
  distribution version) and whether it was installed from PyPI or an editable
  checkout;
- the Python version, operating system, and transport (stdio or HTTP);
- whether the HTTP service used a bearer token, OAuth, or both;
- a minimal reproduction using sanitized JSON-RPC or HTTP requests;
- the impact, including what an attacker gains and what access they need;
- any relevant upstream CLI name and version.

Do not include a live bearer token, OAuth credential, private workspace path, or
private research data. Replace secrets with placeholders.

## What to expect

Reports are handled in the private advisory thread. No response-time or
fix-time SLA is offered. Please allow time for review and avoid public
disclosure until a fix or mitigation has been agreed. The maintainer will
coordinate disclosure and credit with the reporter.

## Security model

- The gateway is not a sandbox. Upstream executables run with the permissions
  of the gateway's operating-system user.
- `plan_auditor_audit` executes project-authored checks and is disabled by
  default. It is available only through the local stdio transport; the HTTP
  transport keeps it unavailable even when `SCITOOL_ALLOW_AUDIT_EXECUTION=1`.
- The HTTP server authenticates requests but does not terminate TLS. Deploy it
  behind an HTTPS reverse proxy, keep the bearer token outside Git, and set
  `SCITOOL_ALLOWED_ORIGINS` only for origins you trust. No browser origin is
  allowed by default.
- The gateway reports upstream exit codes and output. A successful exit code is
  not proof that a scientific result is correct.

## In scope

- Authentication or authorization bypass in the bearer-token or optional OAuth
  resource-server path, including signature, issuer, audience, expiry, or scope
  checks.
- Origin-allowlist bypass, CORS credential exposure, ambiguous or conflicting
  `Host`, `Authorization`, `Content-Type`, or `Content-Length` handling, and
  request-smuggling issues in the HTTP transport.
- Any way for an MCP client to execute `plan_auditor_audit`, run arbitrary
  commands, or read or write outside the configured workspace through gateway
  input.
- Argument or executable injection through tool arguments or `SCITOOL_*_BIN`
  overrides, including shell interpretation or unbounded subprocess execution.
- A failed, missing, timed-out, or ambiguous upstream result being reported as
  success, or an `UNKNOWN` result being promoted to `PASS`.
- Disclosure of the bearer token, OAuth credentials, or private workspace data
  through logs, errors, or responses.
- A bypass of the pinned Axiomize distribution that causes a different installed
  distribution to run.
- Denial of service that bypasses the request-size, body-read timeout,
  concurrency, or rate-limit guards.

## Out of scope

- Scientific correctness, statistical validity, or model quality of upstream
  results. Report defects in an upstream package to that package's repository.
- Vulnerabilities in the seven upstream distributions themselves, unless the
  gateway makes the impact worse.
- The documented execution model of `plan_auditor_audit` when it is explicitly
  enabled for a trusted workspace. It runs project-authored checks and is not a
  sandbox.
- Operator choices such as disabling TLS, publishing the bearer token, allowing
  an untrusted origin, pointing `SCITOOL_WORKSPACE_DIR` at an untrusted tree, or
  installing untrusted executables on `PATH`.
- Findings that require control of the local OS account, the Python environment,
  or the installed upstream packages.
- Behavior of an external OAuth provider or a third-party MCP client.
