# PyPI publishing: Furox Scientific Toolkit

This repository builds the Python distribution **`scientific-toolkit-mcp`**. The
importable module is `scientific_toolkit_mcp`, and the installed executable is
`scientific-toolkit-mcp`.

> A GitHub workflow existing is **not** evidence of a published PyPI package.
> Verify the public PyPI project after a successful release before advertising installation.

## Trusted Publisher

The `scientific-toolkit-mcp` project was created on PyPI on 2026-10-20, and
releases up to `0.4.1` are published. Its GitHub Actions Trusted Publisher is
registered with these exact values:

| PyPI field | Value |
| --- | --- |
| PyPI project name | `scientific-toolkit-mcp` |
| GitHub owner | `Furox-Art` |
| Repository | `scientific-toolkit` |
| Workflow filename | `release-pypi.yml` |
| GitHub environment | `pypi` |

Manage the publisher at
https://pypi.org/manage/project/scientific-toolkit-mcp/settings/publishing/.
Any mismatch between these values and the workflow's OIDC claims makes PyPI
reject the exchange with `invalid-publisher`.

The previous project `furox-scientific-toolkit-mcp` was removed from PyPI on
2026-10-20 and has no files; the distribution now lives under the new name.

The workflow is `.github/workflows/release-pypi.yml`. It uses GitHub's OIDC identity
and `pypa/gh-action-pypi-publish`; **do not create a long-lived PyPI API token**.
Protect the `pypi` GitHub environment with reviewers and restricted deployment
branches/tags if the repository's plan supports it.

## Publish a release

1. Update `pyproject.toml`'s `project.version` and
   `scientific_toolkit_mcp/__init__.py`'s `__version__` together.
2. Verify the full test suite and the distribution build in CI.
3. On GitHub, create and **publish a release** with tag `v<version>` (for example,
   `v0.4.1` for version `0.4.1`), targeting the reviewed commit on `main`.
4. The release workflow checks that the tag, distribution name, and package version
   match (the tag `v<version>` against `project.version` and
   `__version__`). It also refuses commits that are not on `main` and skips
   prerelease GitHub releases entirely. It runs the tests, builds sdist and wheel,
   validates the archive metadata, and installs and imports the built wheel from
   outside the repository.
5. Only after the build job succeeds, the publishing job downloads those exact
   distributions, re-checks them with `twine check`, and requests a short-lived PyPI
   publishing token through OIDC.
6. Check the workflow's final status and the actual public release on
   https://pypi.org/project/scientific-toolkit-mcp/.

### Idempotent publishing and automatic verification

The publishing job is safe to re-run and does not need a human to decide whether a
retry is allowed:

- `skip_existing: true` turns PyPI's HTTP **409 "File already exists"** into a warning.
  Re-publishing a release whose distributions are already on PyPI is a no-op, so a
  re-run of a release event never fails just because the files are already published.
- The publish step is attempted twice (`publish`, then `publish-retry`). A rejected
  OIDC token exchange is usually transient on GitHub's or PyPI's side, and the
  second attempt runs on a fresh runner with a freshly pulled action image.
- Both attempts are `continue-on-error`, and the job's real verdict comes from a
  final step that queries `https://pypi.org/pypi/<project>/<version>/json` and asserts
  that the expected sdist **and** wheel are present. The run therefore succeeds when
  the files are live — whether they were uploaded in this run or a previous one — and
  fails with an explicit message when they are not.
- The sha256 digests of the published files are printed and compared with the local
  ones, but a mismatch is reported as advisory only: wheel and sdist bytes are not
  reproducible across builds, so this must never gate the release.
- The workflow prints the OIDC claim set that PyPI receives before publishing, which
  makes `invalid-publisher` failures diagnosable straight from the log.

`cancel-in-progress` is deliberately `false` for this workflow: cancelling a run
between the sdist and the wheel upload would leave a half-published release.

For subsequent versions, update the version in both locations, tag the new
reviewed release, and publish the GitHub release. PyPI disallows replacing a
previously published version's distributions. Do not recycle version numbers.

## Verify the published artifact

After the public PyPI page lists the new version, verify on a fresh environment:

```bash
python -m pip install scientific-toolkit-mcp
python -c "import importlib.metadata as m; import scientific_toolkit_mcp; print(m.version('scientific-toolkit-mcp'))"
```

This installs the **gateway**, not all nine upstream scientific packages.
Install upstream packages separately and use `toolkit_doctor` to report what is
actually available. The default transport is local stdio; use
`python -m scientific_toolkit_mcp` only inside a configured MCP client.

Successful packaging and protocol tests do not establish scientific correctness
of upstream models or successful OAuth login in external AI clients.

## Failure diagnosis

- **Invalid publisher:** exact owner, repo, workflow file, and environment must
  match the settings registered in PyPI. This is a token-exchange failure that
  happens *before* any upload, so retrying will not fix it — the claims printed by
  the publish job are the values to correct in PyPI's publishing settings.
- **Release not published:** a GitHub tag alone does not fire this workflow;
  publish the GitHub release.
- **Version mismatch:** keep `v<version>`, `pyproject.toml`, and `__version__`
  synchronized. The workflow rejects a mismatch.
- **Build/test failures:** fix the regression first; failed artifacts must never
  be uploaded as a PASS.
- **Missing wheel or metadata:** the workflow's distribution checks stop before
  the OIDC publishing job.
- **File already exists (HTTP 409):** expected when a release is re-published;
  `skip_existing` makes it a warning and the verification step still confirms the
  files are live on PyPI.

Trusted Publisher reference:
https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/
