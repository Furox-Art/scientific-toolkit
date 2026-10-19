<!--
Thank you for contributing. Keep changes scoped, do not include credentials or
private workspace data, and read CONTRIBUTING.md before opening a pull request.
If this is a security fix, use the private route in SECURITY.md rather than a
public pull request until the maintainer asks otherwise.
-->

## What changes

<!-- One paragraph. What is different after this merges, and for whom. -->

Closes #

## Area

- [ ] MCP tools or upstream adapters (`scientific_toolkit_mcp/tools.py`, `scientific_toolkit_mcp/catalog.py`)
- [ ] Transports or authentication (`scientific_toolkit_mcp/server.py`, `http_server.py`, `oauth.py`)
- [ ] Packaging or release (`pyproject.toml`, `.github/workflows/`)
- [ ] Tests (`tests/`)
- [ ] Documentation (`README.md`, `docs/`, `CHANGELOG.md`)
- [ ] Repository governance (`SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `.github/`)

## Behavior and safety

- [ ] Missing, failed, timed-out, or unknown upstream results still fail closed; none can become success.
- [ ] No new arbitrary shell execution, user-selected paths, or unbounded subprocess timeout.
- [ ] `plan_auditor_audit` remains local-only over HTTP.
- [ ] New environment variables or dependencies are documented.
- [ ] Not applicable; no runtime behavior changed.

## Tests and checks run

Paste the commands and real results. Do not claim a check you did not run.

- [ ] `python -m pytest -q -rs tests/` (CI uses pytest; a skipped test fails the session via `conftest.py`)
- [ ] `python -m build` and `python -m twine check dist/*` (if packaging changed)
- [ ] `python examples/analysis_pipeline.py` (if examples or adapter behavior changed)
- [ ] Not applicable

```text
<paste output here>
```

## Release notes

- [ ] I added a user-visible entry under `Unreleased` in `CHANGELOG.md`.
- [ ] No user-visible change.
- [ ] No version bump in this pull request. Version numbers are updated together in `pyproject.toml` and `scientific_toolkit_mcp/__init__.py` during release.

## Review notes

<!-- Anything the reviewer should check first, or anything you are unsure about. -->
