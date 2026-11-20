# Third-party license material

Trace application code is distributed under the root MIT license, with the
original template copyright retained. Third-party components remain subject to
their own licenses; this directory does not relicense them.

- `npm-inventory.json`: all 80 locked npm package records, exact versions,
  declared licenses and upstream/registry sources, verified on 2026-11-20.
  Platform-optional entries may not be installed or distributed. A metadata
  declaration is not a complete native/static dependency SBOM.
- `npm/`: unmodified LICENSE/COPYING/NOTICE and third-party notice files from
  installed runtime and build dependencies. Build notices are conservatively
  retained to cover emitted helpers, including Vite's modulepreload polyfill.
  Including notices does not mean the build-tool binaries are shipped.
- `MPL-2.0.txt`: LightningCSS uses MPL-2.0, a file-level copyleft license.
  This release uses it as a build tool and ships no LightningCSS native binary
  or covered source file. Do not infer that merely generating CSS relicenses
  the entire application under MPL. Redistributing covered files requires
  separately satisfying MPL, including the applicable source-availability duties.
- `SQLGlot-29.0.1-LICENSE.txt`: MIT license for the unchanged SQLGlot dependency.
- `CPython-LICENSE.txt`: the original CPython 3.15.0 Windows binary license,
  including historical, incorporated-library and Microsoft redistribution terms.
- `CPython-3.15-NOTICES.md`: the complete license section extracted from the
  CPython 3.15.0 documentation, covering Expat (MIT), libmpdec (BSD), mimalloc
  (MIT), Unicode data, zlib and other incorporated software. This comprehensive
  upstream list may mention components excluded from the actual package.
- `OpenSSL-3.5.9-LICENSE.txt`: Apache-2.0 license retained for the bundled OpenSSL.
- `runtime-provenance.json`: reviewed Python version and original license / local
  documentation hashes. Packaging fails if the Python version or binary license
  differs; review refreshed notices before using another runtime.

The portable ZIP additionally contains `licenses/frontend-dependencies.json`,
mapping installed npm components to their license texts, and `manifest.json`,
listing the actual shipped files and their SHA-256 hashes. Microsoft runtime
conditions are explained in [Windows runtime terms](../WINDOWS-RUNTIME-TERMS.md).
Tcl/Tk binaries, Python GUI launchers, sampling-profiler vendor JavaScript and
profiler logo assets are excluded because this web application does not use them.

Qlik Sense and Amazon QuickSight are third-party product names used to describe
compatibility and analysis targets. This project is independent and is not
endorsed by their owners. No trademark license is granted by the project MIT license.
