# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

- No workflow step was removed, no test was dropped, and no version was published.
  Every change either adds a check or removes a failure mode.

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
