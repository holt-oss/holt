# OSS launch checklist

This checklist separates changes that belong in Git from organization and
publishing settings that must be made by an account owner. Do not create a
second copy of the repository: transfer the existing repository so its history
and redirects stay intact.

## Before transfer

- [ ] Confirm the Micro1/HackerEarth challenge terms permit releasing the full
  submission under Apache-2.0.
- [ ] Review the committed fixtures and full Git history for credentials,
  private data, and third-party material that needs attribution or removal.
- [ ] Review and merge the OSS preparation changes on the personal repository.
- [ ] Confirm `holt-oss` has at least two owners with two-factor authentication
  and recovery access.
- [ ] Add a second trusted Code of Conduct contact so a report involving the
  lead maintainer does not have to be sent only to that maintainer.
- [ ] Confirm there is no repository named `holt` or fork in the target
  organization.
- [ ] Reserve or verify control of the `holt-cli` name on the intended package
  index before advertising an install command.
- [ ] Decide whether the first public package will support replay mode. The Git
  clone includes the large evidence fixtures; the current wheel deliberately
  does not.

## Transfer

1. In `aahil-khan/holt`, open **Settings → General → Danger Zone → Transfer**.
2. Select `holt-oss` as the new owner and keep the repository name `holt`.
3. After GitHub completes the transfer, update local clones:

   ```sh
   git remote set-url origin https://github.com/holt-oss/holt.git
   git remote -v
   ```

4. Verify the old web URL and a Git fetch both redirect to the organization.
5. Do not recreate `aahil-khan/holt`; doing so removes GitHub's redirect.

## Repository settings

- [ ] Keep the repository public and enable Issues.
- [ ] Enable Discussions if the maintainer wants questions and early proposals
  separated from actionable issues.
- [ ] Set the description to: `Evidence-backed assessments of whether a GitHub
  repository is worth an outside contributor's time.`
- [ ] Add topics such as `open-source`, `contributors`, `github`, `python`,
  `cli`, and `repository-analysis`.
- [ ] Enable private vulnerability reporting and subscribe the maintainer to
  security alerts.
- [ ] Enable Dependabot alerts, secret scanning, and push protection.
- [ ] Set the default `GITHUB_TOKEN` permission to read-only; grant write access
  only inside a job that demonstrably needs it.
- [ ] Create a ruleset for `main` that blocks deletion and force pushes and
  requires pull requests and the three CI jobs: `package`, `tests`, and
  `without-the-optional-extra`.
- [ ] Start with zero required approving reviews while there is only one
  maintainer. Require one independent approval after a second maintainer is
  active.
- [ ] Allow squash merging and automatically delete merged branches.

## First issues

Create a small, honest starter set rather than applying `good first issue` to
large architectural work. Good initial candidates include:

- packaging one small replay demonstration without shipping the evaluation
  corpus;
- improving Windows installation and terminal coverage;
- adding an evidence-provider contract example;
- improving accessibility and keyboard documentation in the TUI;
- reviewing public fixtures for minimization and attribution; and
- turning the approved website mockup into a production implementation.

Each starter issue should state the desired behavior, relevant files, how to
test it, and what is intentionally out of scope.

## Release

- [ ] Run `uv build` and `uv run python scripts/check_dist.py dist`.
- [ ] Install the wheel in a clean environment and smoke-test every command
  advertised on the package page.
- [ ] Configure PyPI Trusted Publishing for `holt-oss/holt` and a dedicated
  release workflow; do not store a long-lived PyPI token in GitHub secrets.
- [ ] Publish a release candidate before `0.1.0` if install-from-package behavior
  differs from install-from-clone behavior.
- [ ] Create signed Git tags and GitHub release notes from `CHANGELOG.md`.
- [ ] Verify the package page shows the Apache-2.0 expression, project links,
  maintainer, and license files.

## Announcement

- [ ] Finalize the website design and only then implement and deploy it.
- [ ] Link the canonical Micro1 winner announcement with approved wording.
- [ ] Publish one reproducible demo command and one live command, clearly
  distinguishing their token, model, cost, and network requirements.
- [ ] State the pre-1.0 support boundary and expected maintainer response model.
- [ ] Invite contributions to specific starter issues rather than making a
  generic request for help.
