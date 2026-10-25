# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.1] - 2026-10-25

### Fixed

- `catalog()` now returns deep copies, so mutating a returned entry (including
  its nested `tools` list) can no longer change later responses or the shared
  repository inventory. The previous shallow `dict()` shared those lists.

## [0.4.0] - 2026-10-24

### Added

- `literature-evidence-mcp` and `nomosguard` join the gateway catalog, taking
  the inventory to nine upstream repositories and fourteen tools.
- `literature_evidence_search` and `literature_evidence_verify_quote` drive the
  literature-evidence MCP stdio server; `nomosguard_decide` asserts evidenced
  claims, derives paths, and runs the deterministic fail-closed policy gate.
- A bounded stdlib MCP stdio client that keeps stdin open until every expected
  response arrives, so a server that stops reading at EOF cannot drop replies.
- `toolkit_doctor` reports module-based servers and their import names.
- `toolkit_doctor` reports, for every pinned distribution, the resolved
  version, the configured `SCITOOL_PIN_*` value, and each `sys.path` provider
  that could shadow it.

### Changed

- The gateway now requires Python 3.11 or newer; `literature-evidence-mcp`
  declares the same floor.

### Fixed

- `cds_stats` forwards the caller's numbers without the `.12g` rounding that
  silently changed the sample before the upstream statistics ran on it.
- Upstream CLIs run with stdin connected to `os.devnull`, so they cannot
  consume the gateway's input or block waiting for data.
- Pinned-distribution lookup treats an empty `sys.path` entry as the working
  directory instead of skipping it, which is where the interpreter would
  import from.

### Security

- HTTP rate limiting can key on the real client address behind a reverse
  proxy when `SCITOOL_TRUST_PROXY=1`. Only a single `X-Forwarded-For` header
  is accepted and its rightmost valid address is used, so a client cannot
  choose its own bucket and reset the quota. Without the switch the socket
  peer is used, as before.

## [0.3.0] - 2026-10-20

### Changed

- The PyPI distribution is now `scientific-toolkit-mcp`; the previous
  `furox-scientific-toolkit-mcp` project was removed from PyPI. The import
  module and the `scientific-toolkit-mcp` console script are unchanged.

## [0.2.3] - 2026-10-13

### Fixed

- Release verification expects only the built distributions, not attestation
  sidecars.

## [0.2.2] - 2026-10-12
### Housekeeping — audit hardening

- Closes the findings of the full-repository audit: patched the concrete
  defects (correctness, fail-closed behaviour, platform independence),
  wired every standalone guard into CI, removed dead or duplicated code
  paths, and pinned every doc claim to a test so it cannot silently
  drift again. Regression tests fail without the corresponding fix.

### Fixed

- OAuth bearer verification no longer crashes on non-ASCII credentials.
  `hmac.compare_digest` raises `TypeError` for non-ASCII `str` operands, so a
  hostile non-ASCII `Authorization` header (or a non-ASCII bearer secret) used
  to kill the HTTP handler and drop the connection instead of returning a clean
  401. Credentials are now compared as RFC 7235 latin-1 header bytes; a
  credential that cannot be represented as a header value is malformed and
  rejected fail-closed. It can neither raise nor fail open.
- Tool dispatch is consolidated onto a single routing table
  (`scientific_toolkit_mcp.tools.TOOL_ROUTES`): every tool's allowed argument
  keys and its handler live in one place, validated by one router, with a test
  asserting the table and the MCP tool specs in `server.py` cannot drift. No
  behavior or error message changed.
- Every upstream subprocess call has an explicit, bounded timeout
  (`MIN_CALL_TIMEOUT=1`, `DEFAULT_CALL_TIMEOUT=30`, `MAX_CALL_TIMEOUT=600`); an
  out-of-range per-call timeout is a clean `INVALID_ARGUMENT` failure.
- Namespace-collision hardening for the Axiomize CLI: `axiomize` is a pinned
  distribution, and an `axiomize` module provided by more than one `sys.path`
  entry (an isolated install directory exported through `PYTHONPATH`, for
  example) fails the call with `BAD_CONFIGURATION` instead of silently running a
  different distribution than the pinned one. `SCITOOL_PIN_AXIOMIZE` pins the
  exact expected version.
- The availability report no longer relies on a global `PYTHONPATH` export:
  `scripts/refresh-availability.sh` drops it (it contradicted the documented
  isolation rule and let the bundled `axiomize` package silently replace the
  standalone one for every probe), and `scripts/availability_report.py` scopes
  the isolated package directory to the single version-probe subprocess that
  needs it.

### Changed

- The availability report now records a **listing** and a **verification** as
  two separate booleans per repository (`listed` from package metadata,
  `verified` from a real executed CLI call); `installed` remains as a deprecated
  compatibility alias of `listed`. The report also marks itself as a generated
  artifact (`regenerate_command`, `generated_artifact_note`) and records the
  `sys.path` providers of each pinned distribution module.

## [0.2.1] - 2026-10-12

### Changed

- The PyPI release workflow is now idempotent and self-verifying: `skip_existing`
  turns HTTP 409 "File already exists" into a warning, the publish step is retried
  once on failure, and a final step confirms the sdist and wheel are actually
  published instead of trusting the publish step's exit code. Re-running a
  published release no longer fails.
- The publish job dumps the OIDC claim set PyPI receives, so a trusted-publisher
  configuration mismatch is diagnosable from the log.
- CI hardening across all workflows: explicit `concurrency` groups, missing
  `timeout-minutes`, `fail-fast: false` on the test matrix, `persist-credentials:
  false`, and current action major versions (`checkout@v7`, `setup-python@v7`,
  `upload-artifact@v7`, `download-artifact@v8`).
- `tests.yml` no longer runs the full suite on `gh-pages` pushes.
- The release build and `package-artifacts` job now audit that exactly one
  correctly named sdist and one wheel were produced before publishing.

### Not changed

- No workflow step was removed, no test was dropped. Every change either adds a
  check or removes a failure mode.

## [0.2.0] - 2026-10-09

### Added

- End-to-end integration test suite for the seven-tool MCP gateway: 109 tests, 1 skip
  (`SdkClientInteropTests` skips when the official MCP SDK is not installed, as in CI).
- Availability report (`scripts/availability_report.py`) capturing the real installed
  versions of all seven tools.
- Runnable example workflow (`examples/analysis_pipeline.py`): 8 stages, 0 known gaps,
  real cross-tool data flow.

### Fixed

- CI now installs the seven tool CLIs before the suite; previously all cross-tool
  tests failed with `NOT_INSTALLED`.
- Bundled-distribution detection: the bundled `axiomize-reason` resolves its own
  package through the `.reason-pkg` `PYTHONPATH`, and interpreter resolution is robust.
- The release workflow installs the seven tool CLIs and points
  `SCITOOL_REASON_BIN` at `.reason-env/bin/axiomize-reason` before its test gate,
  so the release build runs the same suite as `tests.yml` (it previously ran the
  suite with no upstream CLIs installed and failed with `NOT_INSTALLED`).

### Not proven

- The remote MCP transport is tested against a local loopback server only; the live
  hosted deployment is not exercised here.
- Scientific correctness of upstream results is out of scope: a tool exiting 0 proves
  the program ran, not that its answer is right.

## [0.1.0] - 2026-10-08

### Added

- Initial release of the `furox-scientific-toolkit-mcp` gateway: provider-neutral
  local and remote MCP hub for seven Furox-Art public research tools.
- Local stdio transport, remote HTTP transport with OAuth 2.1 bearer support, and the
  MCP tool inventory.
- Trusted-Publisher PyPI release workflow with build, metadata and installed-wheel
  gates.
