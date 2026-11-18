# Releasing the SDK on PyPI

The SDK is published as [`sudoo-plugin-sdk`](https://pypi.org/project/sudoo-plugin-sdk/) by
`.github/workflows/publish.yml` with PyPI trusted publishing: GitHub proves to PyPI which workflow is uploading, so
no API token or password is created, stored or pasted anywhere.

## One-time setup (owner)

1. **PyPI account.** Create an account on [pypi.org](https://pypi.org/account/register/) and turn on two-factor
   authentication (Account settings -> Two factor authentication).
2. **Pending publisher.** On pypi.org: Your projects -> Publishing -> Add a new pending publisher -> GitHub, with
   - PyPI project name: `sudoo-plugin-sdk`
   - Owner: `Sudoo-sh`
   - Repository name: `sudoo-plugin-sdk`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`

   The first upload creates the project and turns the pending publisher into a normal one.
3. **GitHub environments.** In the repository: Settings -> Environments -> New environment `pypi`, tick
   "Required reviewers" and add yourself; optionally restrict "Deployment branches and tags" to tags `v*`.
4. **TestPyPI (optional).** Repeat steps 1 and 2 on [test.pypi.org](https://test.pypi.org) (a separate account),
   with environment name `testpypi`, and create the GitHub environment `testpypi` with you as required reviewer.
   Actions -> Publish -> Run workflow then uploads the chosen branch to TestPyPI.

## Each release

1. On `main`, set the version in `pyproject.toml` and in `src/sudoo_plugin_sdk/__init__.py` (`__version__`), and
   give the version a dated heading in `CHANGELOG.md`; merge that through a pull request.
2. On GitHub: Releases -> Draft a new release -> new tag `v<version>` (for example `v0.1.0`) on `main`, title
   `v<version>`, notes from the changelog -> Publish release.
3. Actions -> Publish: the build job checks that the tag, `pyproject.toml` and `__version__` agree, runs the tests,
   builds and checks the wheel and source archive. Approve the `pypi` deployment when asked; the upload carries
   attestations of where the files were built.
4. Check [pypi.org/project/sudoo-plugin-sdk](https://pypi.org/project/sudoo-plugin-sdk/) and
   `pip install sudoo-plugin-sdk==<version>`.

A version that reached PyPI can never be uploaded again, even after deleting it: fix a bad release with a new
version.
