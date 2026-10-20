# Contributing

Thanks for helping improve `scientific-toolkit-mcp`. This repository is
the MCP gateway that exposes nine independently released Furox-Art scientific
packages. The upstream packages keep their own source trees, versions, and
licenses; changes to their algorithms or scientific behavior belong in those
repositories.

By participating, you agree to follow the
[Code of Conduct](CODE_OF_CONDUCT.md). Report vulnerabilities through the
private route in [SECURITY.md](SECURITY.md), not in a public issue or pull
request.

## Development setup

The gateway requires Python 3.11 or newer. From a source checkout:

```sh
git clone https://github.com/Furox-Art/scientific-toolkit.git
cd scientific-toolkit
python -m pip install -e '.[oauth]'
python -m pip install "pytest>=8" "pytest-cov>=5" "mcp>=2,<3"
```

`.[oauth]` installs the optional OAuth verification dependency used by the
tests; the gateway's mandatory runtime dependencies remain empty. The three
test packages are the prerequisites CI installs in `tests.yml`.

To run the full end-to-end suite, the nine upstream tools (CLIs and MCP stdio
servers) must also be installed. On Linux or macOS, CI uses:

```sh
bash scripts/render-build.sh
```

That script installs the gateway with the `oauth` extra, the eight standalone
upstream projects (from GitHub source in CI, from PyPI for Render builds), and
the bundled Axiomize variant in an isolated directory. It is a Bash script, and the CI runner is Ubuntu.

## Tests

From the repository root:

```sh
python -m pytest -q -rs tests/
```

CI runs this command after installing the upstream CLIs. `unittest discover`
only collects `unittest.TestCase` classes, so it silently skips the
pytest-style tests; do not use it as a substitute.

`conftest.py` fails the pytest session if any test is skipped, so install the
test prerequisites before using pytest. The end-to-end tests use real upstream
executables and real MCP stdio servers. A missing executable is reported as `NOT_INSTALLED` and fails the
test; it is not replaced by a fabricated result. The official MCP SDK
interoperability test skips if the `mcp` package or its Streamable HTTP client
is unavailable, and the pytest gate treats that skip as a failure.

For a focused change, run the affected test module first, then the full suite
before opening a pull request.

## Linting and type checking

No linter or type checker is configured in `pyproject.toml` or the workflows,
so there is no project lint or type-check command to run. Do not add a new
linting or type-checking stack as part of an unrelated change; propose it
separately with the CI change it needs.

## What a good change preserves

1. **Fail closed.** Missing, failed, timed-out, ambiguous, or `UNKNOWN` upstream
   results must be errors. They must never become success or `PASS`.
2. **No arbitrary execution.** Tool adapters use fixed allowlisted command
   forms and `subprocess` without a shell. Do not accept user-selected paths or
   arbitrary command strings through MCP.
3. **Remote boundary.** `plan_auditor_audit` executes project checks and stays
   local-only. Do not expose it through HTTP, even when
   `SCITOOL_ALLOW_AUDIT_EXECUTION=1`.
4. **No fabricated science.** The gateway reports the upstream program's output
   and exit code. It does not certify scientific correctness.
5. **Small runtime surface.** The gateway declares `dependencies = []`.
   Optional features belong in an extra, as OAuth does.

## Tests and documentation for a change

- Add a regression test for a bug fix; it should fail before the fix and pass
  after it.
- Add or update tests for new adapter arguments, error paths, and HTTP
  authentication or origin behavior.
- Update `README.md` and the relevant file under `docs/` when behavior or
  configuration changes.
- Add a user-visible entry under `Unreleased` in `CHANGELOG.md`.
- Keep the code compatible with Python 3.11. CI tests 3.11, 3.12, and 3.13.

## Packaging changes

If you change `pyproject.toml`, the package layout, or release metadata, also
check the distribution:

```sh
python -m pip install --upgrade build twine
python -m build
python -m twine check dist/*
```

The release workflow builds one sdist and one wheel, validates the metadata,
and imports the installed wheel from outside the checkout. Version numbers are
kept in sync between `pyproject.toml` and
`scientific_toolkit_mcp/__init__.py`; update both together when preparing a
release.

## Submitting a pull request

- Use the issue forms for bugs and feature requests; they ask for the
  reproduction and version details needed to triage a report.
- Use the pull request template and keep the change focused.
- Link the issue it resolves, if one exists.
- Paste the commands you ran and their real results. Do not claim a check you
  did not run.
- Remove bearer tokens, OAuth credentials, private workspace paths, and private
  research data from code, logs, and screenshots.
- Do not include generated files that the repository does not already track.

Security fixes should follow [SECURITY.md](SECURITY.md); coordinate in the
private advisory thread before opening a public pull request when the
vulnerability is not yet fixed.

## License

The gateway is licensed under the Apache License 2.0. Contributions are accepted
under that license.
