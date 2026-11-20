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

Vite and TypeScript are build dependencies. Dependency packages retain their upstream license files in the installed distributions. The package lock records exact JavaScript dependencies and integrity hashes; the Python dependency is pinned in [requirements.txt](./requirements.txt).

No Qlik or AWS SDK is required. Qlik Sense and Amazon QuickSight are product names owned by their respective owners; this workbench is an independent local analysis tool.

Public Windows portable archives additionally redistribute CPython under its PSF license (see runtime/LICENSE.txt in the archive), SQLGlot under its MIT license (licenses/SQLGlot-LICENSE.txt), and production frontend dependency license texts under licenses/frontend/. These runtime files are generated during packaging and are not part of the source tree.
