# WS-01G real catalog-core evidence

Issue: #48

Current extension (#67, 2026-09-15): standalone proofs described below stay
ephemeral. The internal measurement runner now accepts `retain_projection=True`
only as an explicit packaging opt-in. It returns the verified projection handle
after all existing checks pass; any failed proof still cleans the projection.
Packaging owns subsequent failure cleanup and publishes these exact bytes instead
of rebuilding. Report schema/bindings and public proof behavior are unchanged.

This workstream is a local, read-only, value-free acceptance gate over one
`VerifiedReconciledGenerationV1`. It independently derives the expected public
Product GIDs, exercises all four games and all supported request families through
the existing authenticated keyset paginator, checks canonical single-card search
and missing-name accounting, checks complete contextual facet maps, and bootstraps
the existing synchronization core with callbacks that must remain unused.

The returned opaque evidence binds the shop, authenticated reconciliation-summary
SHA-256, dataset generation, catalog-content SHA-256, immutable projection-file
fingerprint, and reviewed code SHA. It has no public constructor or serialization
method and rejects pickle reduction.

The projection is an ephemeral caller-selected file outside the repository and the
closed-shape reconciled bundle. It is activated only inside the paginator object, is
never promoted as catalog output, and is made writable and removed on every
completed or rejected proof. Cleanup failure rejects the proof. The persistent
external report must also be outside both the repository and bundle directory, so a
report can never invalidate a future verification of that bundle's exact shape.

The zero-argument operational runner reads its five separately controlled inputs
from `NLA_RECONCILED_BUNDLE_DIRECTORY`, `NLA_RECONCILIATION_SUMMARY_SHA256`,
`NLA_CORE_EVIDENCE_PROJECTION_PATH`, and `NLA_CORE_EVIDENCE_CODE_SHA`. This keeps
paths and digests out of command history and the process argument list. The fifth,
`NLA_CORE_EVIDENCE_REPORT_PATH`, must select a normalized, nonexistent file outside
the repository in an existing directory. Only after every proof and cleanup check
succeeds, the runner atomically installs canonical JSON there without overwrite.
The external report binds the exact evidence values and contains separate nanosecond
durations for projection build, complete pagination traversal, search queries, facet
evaluation, and synchronization bootstrap, plus aggregate page, query, facet, and
bootstrap operation counts. It contains no Product GID, catalog value, input path, or
per-record measurement and must never be committed.

The runner's only console line is either `VALUE_FREE_RESULT: ACCEPTED` or
`VALUE_FREE_RESULT: REJECTED`; it never prints a path, digest, count, timing, or
catalog value. Staging SLO thresholds and their retained evidence remain the separate
responsibility of issue #13.

This workstream adds no network client, Shopify or TCG PowerTools write, live-data
access, database engine, serving surface, capability promotion, theme change, or
publication authority. Rollback is a normal code revert; no persistent data or
runtime activation is created.
