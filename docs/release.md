# Release

`untaped-github` publishes to TestPyPI and PyPI from the GitHub Actions
`Release` workflow. The workflow is manual-only and uses Trusted Publishing
with PyPA's publish action so package uploads include provenance attestations.

## Trusted Publishers

Create pending Trusted Publishers before dispatching the workflow:

- Package: `untaped-github`
- Owner: `alexisbeaulieu97`
- Repository: `untaped-github`
- Workflow: `.github/workflows/release.yml`
- Environments: `testpypi` and `pypi`

The `testpypi` GitHub environment must exist before a TestPyPI dispatch. The
`pypi` environment must require reviewer approval. Do not change environments
or repository settings without explicit approval for that exact repository.

## Dispatch

Use `workflow_dispatch` with:

- `version`: the exact package version from `pyproject.toml`
- `index`: `testpypi` or `pypi`

Production `pypi` dispatches must run from `main`. TestPyPI may run from the
reviewed release branch while piloting the workflow. The workflow verifies that
the version input matches package metadata, that production releases do not
reuse an existing tag or GitHub release, that `untaped>=2.4.4,<3` resolves from
the selected install path, and that the built wheel installs the
`untaped-github` console script.

## Dependency Pins

Development and CI intentionally keep the `untaped` git source pin. The
published wheel metadata comes from the dependency range because release builds
use `uv build --no-sources`.

When raising the SDK floor, update these in the same PR:

- `project.dependencies`: `untaped>=<version>,<3`
- `[tool.uv.sources].untaped.rev`: `v<version>`
- `uv.lock`

The source rev and dependency floor must agree so `uv sync --frozen` remains
satisfiable before publishing.

## Burn Recovery

PyPI and TestPyPI versions are immutable. If upload succeeds but a later smoke
or GitHub release step fails, the version is burned.

Do not rerun the same version workflow after a successful upload. Recover only
the missing side effect when appropriate, such as a manual `gh release create`
for a missing production GitHub release, then fix the workflow in a follow-up
PR. If another package upload is required, bump the patch version and restart
the package release cycle.
