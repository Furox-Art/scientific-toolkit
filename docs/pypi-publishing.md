# PyPI publishing: Furox Scientific Toolkit

This repository builds the Python distribution **`furox-scientific-toolkit-mcp`**. The
importable module is `scientific_toolkit_mcp`, and the installed executable is
`scientific-toolkit-mcp`.

> A GitHub workflow existing is **not** evidence of a published PyPI package.
> Verify the public PyPI project after a successful release before advertising installation.

## First release: establish a pending Trusted Publisher

If the distribution has not yet been created on PyPI, sign in as its intended
maintainer and visit https://pypi.org/manage/account/publishing/ to add a
**GitHub Actions pending publisher** with these exact values:

| PyPI field | Value |
| --- | --- |
| PyPI project name | `furox-scientific-toolkit-mcp` |
| GitHub owner | `Furox-Art` |
| Repository | `scientific-toolkit` |
| Workflow filename | `release-pypi.yml` |
| GitHub environment | `pypi` |

If the project already exists under the maintainer's account, register the same
GitHub Trusted Publisher under **that project's** Publishing settings instead.
A pending publisher does not reserve a name.

The workflow is `.github/workflows/release-pypi.yml`. It uses GitHub's OIDC identity
and `pypa/gh-action-pypi-publish`; **do not create a long-lived PyPI API token**.
Protect the `pypi` GitHub environment with reviewers and restricted deployment
branches/tags if the repository's plan supports it.

## Publish a release

1. Update `pyproject.toml`'s `project.version` and
   `scientific_toolkit_mcp/__init__.py`'s `__version__` together.
2. Verify the full test suite and the distribution build in CI.
3. On GitHub, create and **publish a release** with tag `v<version>` (for example,
   `v0.1.0` for version `0.1.0`), targeting the reviewed commit on `main`.
4. The release workflow checks that the tag, distribution name, and Python version
   match. It runs the tests, builds sdist and wheel, validates the archive metadata,
   and installs and imports the built wheel from outside the repository.
5. Only after the build job succeeds, the publishing job downloads those exact
   distributions and requests a short-lived PyPI publishing token through OIDC.
6. Check the workflow's final status and the actual public release on
   https://pypi.org/project/furox-scientific-toolkit-mcp/.

For subsequent versions, update the version in both locations, tag the new
reviewed release, and publish the GitHub release. PyPI disallows replacing a
previously published version's distributions. Do not recycle version numbers.

## Verify the published artifact

After the public PyPI page lists the new version, verify on a fresh environment:

```bash
python -m pip install furox-scientific-toolkit-mcp
python -c "import importlib.metadata as m; import scientific_toolkit_mcp; print(m.version('furox-scientific-toolkit-mcp'))"
```

This installs the **gateway**, not all seven upstream scientific packages.
Install upstream packages separately and use `toolkit_doctor` to report what is
actually available. The default transport is local stdio; use
`python -m scientific_toolkit_mcp` only inside a configured MCP client.

Successful packaging and protocol tests do not establish scientific correctness
of upstream models or successful OAuth login in external AI clients.

## Failure diagnosis

- **Invalid publisher:** exact owner, repo, workflow file, and environment must
  match the settings registered in PyPI.
- **Release not published:** a GitHub tag alone does not fire this workflow;
  publish the GitHub release.
- **Version mismatch:** keep `v<version>`, `pyproject.toml`, and `__version__`
  synchronized. The workflow rejects a mismatch.
- **Build/test failures:** fix the regression first; failed artifacts must never
  be uploaded as a PASS.
- **Missing wheel or metadata:** the workflow's distribution checks stop before
  the OIDC publishing job.

Trusted Publisher reference:
https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/
