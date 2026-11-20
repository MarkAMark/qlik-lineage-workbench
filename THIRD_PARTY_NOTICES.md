# Third-party notices

This application was adapted from the MIT-licensed [React Flow Vite + TypeScript starter](https://github.com/xyflow/vite-react-flow-template). The upstream copyright and license are retained in [LICENSE](./LICENSE).

The upstream App, CSS and page metadata were replaced with the lineage workbench. Its React/Vite entry structure and React Flow interaction primitives are retained and extended. The Qlik metadata parser, local API, assessment model and workbench screens are additions.

Principal runtime components:

| Component | Purpose | License / source |
| --- | --- | --- |
| React Flow / @xyflow/react, @xyflow/system | Interactive lineage graph | MIT, <https://github.com/xyflow/xyflow> |
| React / React DOM | UI | MIT, <https://github.com/facebook/react> |
| Lucide React | Interface icons | ISC, <https://github.com/lucide-icons/lucide> |
| SQLGlot 29.0.1 | Oracle SQL AST and column lineage | MIT, <https://github.com/tobymao/sqlglot> |

Vite and TypeScript are build dependencies. Build tools can emit code into the application; the distribution therefore retains installed build dependency notices as well as frontend dependency notices. This includes Vite's modulepreload helper and the upstream attributions in Vite/Rolldown license files. The package lock records exact JavaScript dependencies and integrity hashes; the Python dependency is pinned in [requirements.txt](./requirements.txt).

No Qlik or AWS SDK is required. Qlik Sense and Amazon QuickSight are product names owned by their respective owners; this workbench is an independent local analysis tool.

The [license inventory and original texts](./docs/licenses/README.md) are included in both source and portable distributions. They cover all 80 locked npm package declarations and installed package notices, including build tools. LightningCSS is MPL-2.0, used during builds; its native binaries are not included in the portable release. No claim is made that every dependency is MIT or that all licenses are permissive.

Public Windows portable archives redistribute CPython 3.15.0 under its PSF/historical and incorporated-component licenses (runtime/LICENSE.txt and docs/licenses/CPython-3.15-NOTICES.md), SQLGlot under MIT (licenses/SQLGlot-LICENSE.txt), and npm dependency notices under licenses/frontend/. The CPython runtime also includes Microsoft proprietary redistributable code. It is not open source and is not relicensed under MIT. Its original Windows binary conditions are retained; users and redistributors must follow [Windows runtime terms](./docs/WINDOWS-RUNTIME-TERMS.md). Source archives do not include these runtime binaries.

The portable runtime omits unused Tcl/Tk GUI binaries, the Python GUI launcher, and sampling-profiler vendor libraries and logo assets. The complete upstream Python license document is still retained, including historical notices for components not shipped. The machine-readable package manifest identifies the files actually present.
