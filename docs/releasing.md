# Public release process

The public edition must be maintained as its own clean repository. Do not copy an internal Git history, internal ZIP, reports or screenshots into it. Source installation is cross-platform; the bundled portable edition is Windows x64 only.

## Verify from a clean checkout

Install the requirements and build steps in [README](../README.md), then run:

```sh
python -B -m unittest discover -s tests
npm run test:graph
npm run build
npm audit --omit=dev --audit-level=high
python tools/check_public.py
npm run test:browser
```

All test exports are synthetic and generated under OS temporary folders. The public-content guard checks a source allowlist, tracked-file boundaries, metadata filenames, personal absolute paths and common credential patterns. It is an automated baseline; review the final diff and archive contents for organization-specific information too.

Dependency auditing requires access to the npm security endpoint. If that service is unavailable, record the incomplete check and rerun it before publishing. The CI workflow includes this audit; local content scans do not replace it.

## Package

```sh
# Source archive on any platform
python tools/package_public.py --source-only
# Source + self-contained runtime; Windows x64 CPython 3.12+
python tools/package_public.py
# Exercise the real ZIP using only its bundled runtime
python tools/verify_public.py releases/Trace-Qlik-Lineage-Public-Windows-x64-v0.1.0.zip
```

The packager has no metadata-root option. It fails when repository metadata contains any payload, copies only allowed source files, and creates a portable archive with an empty `metadata/apps` placeholder. Source ZIPs omit dependencies, compiled assets, generated outputs and Git history. Portable ZIPs include built frontend, backend, isolated CPython, SQLGlot and license texts. Their manifest includes per-file SHA256 hashes and explicitly records zero metadata files. Each ZIP has a SHA256 sidecar.

After extraction, verify portable contents with:

```powershell
.\runtime\python.exe -I -B .\verify_package.py
.\Start-Trace.cmd
```

Check empty onboarding on a machine without Python/Node, and import a temporary synthetic export. Do not import business data into a directory that will later be uploaded as a release artifact. Build an upload candidate from a fresh clean checkout.

## Publish on GitHub

1. Choose a repository name (suggested: `qlik-lineage-workbench`) and confirm the code can be published under the retained MIT license.
2. Create an empty repository. Make the first commit from this public source tree, using your own Git identity. Do not attach any internal repository history.
3. Before pushing, inspect `git diff --cached --stat` and `git diff --cached`, run the public-content guard, and ensure the tracked metadata directory contains only `.gitkeep`.
4. Push source, let CI finish and review its artifacts. CI builds candidates but does not publish releases.
5. Create tag `v0.1.0`, create a GitHub Release, and attach only the **Public Windows x64**, **Source** ZIPs and matching SHA256 files produced by this workflow.
6. Enable private vulnerability reporting and secret scanning when available. Describe the Chinese UI, supported export format and static-analysis limitations in the repository About/README.

Do not upload an internal sharing package even if its filename looks similar. GitHub Pages cannot host the Python backend; users run this application locally.
