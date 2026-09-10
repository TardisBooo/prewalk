# Release checklist

## v1.0.1

- [x] Targeted regression tests cover state permissions, Windows CLI shims,
  dotted preset names, packet todo fallback, and Codex patch detection.
- [x] Isolated arm/checkpoint/route acceptance verifies the repaired workflow.
- [x] Engine, manifest, marketplace, changelog, and migration-guide versions
  agree on 1.0.1.
- [x] Vendored engine copies are byte-identical to the canonical package.
- [ ] Tag `v1.0.1` only after review.

## v1.0.0

- [x] Shared unit, adapter, end-to-end, and workflow-matrix suites pass.
- [x] Claude Code 2.1.145/latest and Codex CLI 0.146.0/latest are required in CI on Linux and macOS.
- [x] Claude strict validation and isolated install discover nine skills and one executor agent.
- [x] Codex isolated marketplace install discovers and enables Prewalk.
- [x] Isolated Claude and Codex upgrades move from a 0.3.x fixture to 1.0.0.
- [x] Workflow smoke covers normal review, fast mode, failures, interruption, stale state, and recovery.
- [x] Benchmark record/report sanity check passes without making performance claims.
- [x] Engine, manifest, marketplace, changelog, and migration-guide versions agree on 1.0.0.
- [x] Vendored engine copies in both hosts are byte-identical to the canonical package.
- [ ] Tag `v1.0.0` only after every preceding release gate is complete.
