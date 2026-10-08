# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
