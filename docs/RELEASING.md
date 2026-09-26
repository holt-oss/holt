# Releasing Holt

This process is for project maintainers. Releases are built by GitHub Actions
and authenticated to PyPI with OpenID Connect; no PyPI token is stored in the
repository.

## One-time PyPI setup

From the PyPI account's publishing settings, add a pending trusted publisher
with these exact values:

| Field | Value |
|---|---|
| PyPI project name | `holt-cli` |
| GitHub owner | `holt-oss` |
| GitHub repository | `holt` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

The pending publisher claims the project when the first trusted release is
published. Do not create or store a long-lived upload token.

## Publish a version

1. Update the version in `pyproject.toml` with `uv version`, update
   `CHANGELOG.md`, and merge the release commit into `main`.
2. Confirm the `tests` workflow is green on that commit.
3. Create a GitHub release targeting that commit with a tag matching the
   package version, such as `v0.1.0`.
4. Publish the GitHub release.

Publishing the release triggers `.github/workflows/publish.yml`. It verifies
the tag, builds both distributions, checks their contents, installs the wheel
in a clean environment, and publishes through the configured trusted
publisher. PyPI versions are immutable; correct mistakes with a new version.
