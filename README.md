# Trace · Qlik Lineage Workbench

A local workbench for exploring Qlik Sense metadata and assessing migration to Amazon QuickSight. The interface is currently in Chinese. [中文说明](./README.zh-CN.md).

**This public edition contains no Qlik metadata, business reports or business screenshots.** Import your own local export to begin. No Qlik, database or AWS credentials are required. This is an independent community tool, not an official Qlik or AWS product.

## Capabilities

- Browse multiple Streams, applications, Sheets and field usages.
- Trace fields through chart expressions, model fields, SQL and Qlik LOAD to exported data sources.
- Inspect code evidence and full imported source files; explore table and technical field lineage.
- Highlight related paths, inspect edges, search across apps and export inventories.
- Review migration complexity and indicative effort; estimates require calibration against actual migration work.

## Windows portable edition

Download the **Public Windows x64** archive from GitHub Releases when published, extract the entire archive, then double-click `Start-Trace.cmd`. No Python or Node installation is needed for recipients. The default address is `http://127.0.0.1:8775`; if busy, the launcher tries the next 30 ports. Keep the terminal open while using the app.

The initial screen is intentionally empty. Click **选择元数据目录**, paste the absolute path to your export and click **扫描并导入**. Files stay on the local machine. Selecting an external folder lasts for the current process; pass `-MetadataRoot` when launching to reuse it after restart, or place exports under the package's local `metadata/apps` folder.

## Run from source

Requirements: Python 3.10+ and Node.js 20+ (24 LTS recommended). Building portable archives additionally requires Windows x64 CPython 3.12+.

```powershell
.\Setup.ps1
.\Start-Local.ps1
# Optional: start against an external directory on a separate port
.\Start-Local.ps1 -MetadataRoot 'D:\QlikExports\apps' -Port 8875
```

On macOS/Linux, or for manual setup:

```sh
python -m pip install --target .deps -r requirements.txt
npm ci
npm run build
python -B -m backend.server
```

For UI development, run the backend on port 8775 and `npm run dev` in another terminal. Vite proxies local API calls to that port.

## Bring your own metadata

See [metadata format and production import](./docs/metadata-import.md). Binary `.qvf` files alone are not supported. An app export is expected to contain `app-properties.json`, `script.qvs` and JSON object definitions under `objects/`; variables and master dimensions/measures should be exported when used. Directory grouping is supported as `apps/Stream/App/` or flat `apps/App/`.

Import reads the selected directory into a process-local snapshot without modifying export files. An empty or invalid import returns an error and preserves the previous snapshot. Restart to clear the process-local snapshot. There is no automatic conversion or deployment to QuickSight.

## Verification and releases

```sh
python -B -m unittest discover -s tests
npm run test:graph
npm run build
python tools/check_public.py
npm run test:browser
# Windows x64 only: source ZIP + zero-metadata portable ZIP
python tools/package_public.py
```

The browser test launches its own server on a free port, generates synthetic exports in an OS temporary folder and uses Chrome/Edge (set `QLIK_BROWSER` if needed). It does not read user exports. See [release process](./docs/releasing.md).

## Scope and limitations

Lineage is static analysis, bounded by the exported files. External includes, database view definitions, dynamic script expansion, wildcard schemas and selection-context behavior may need manual review. Unresolved expressions and cycles are marked; a parsed dependency does not prove runtime equivalence. Migration effort is a planning aid, not a delivery commitment.

The HTTP service binds to loopback and has no authentication. Run it locally; it is not intended for shared-server hosting or GitHub Pages. Runtime analysis uses local assets and does not require network access. Installing dependencies requires access to package registries.

## License and contribution

[MIT](./LICENSE). Built on the React Flow Vite + TypeScript starter. See [third-party notices](./THIRD_PARTY_NOTICES.md), [contribution guide](./CONTRIBUTING.md) and [security guidance](./SECURITY.md). Do not attach real exports, SQL, connection strings or business screenshots to public issues.
