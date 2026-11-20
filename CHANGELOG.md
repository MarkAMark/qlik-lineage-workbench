# Changelog

## 0.1.2

- Include verified third-party license inventories and original notices in source and portable archives, covering runtime components and emitted build helpers.
- Correct missing license identifiers and retain Vite/Rolldown third-party notice files.
- Exclude unused Python GUI binaries, profiling vendor JavaScript and logo assets; pin the reviewed portable Python runtime.
- Present Windows runtime redistribution terms before launch; support explicit acceptance for unattended verification.
- Keep application behavior and zero-metadata distribution unchanged.

## 0.1.1

- Upgrade the frontend build chain to Vite 8 and its matching React plugin; refresh affected transitive dependencies.
- Audit development and build dependencies in CI as well as runtime dependencies, failing on any known severity.
- Document and check the supported Node.js versions for source builds; portable users still need no Node installation.
- Rebuild zero-metadata public archives with the updated toolchain.

## 0.1.0

- Initial data-free public edition with local metadata onboarding.
- Multi-Stream field, table and technical lineage with code evidence.
- Local source inventory and indicative QuickSight migration assessment.
- Synthetic regression tests, public-content checks and zero-metadata Windows packaging.
