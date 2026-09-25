# D8.7 release-candidate closure map

## Decision boundary

D8.7 packages and qualifies the standalone product produced by D8.1–D8.6. It
is the final release-candidate stage before D9, not the D9 release decision
itself. D9 still requires the D8.7 exact-artifact gate and an independent
review of the retained evidence.

The historical D8.0 gap matrix remains unchanged as the original audit record.
This document records where each D9 gate is now expected to obtain its closure
evidence.

| D9 gate | D8.7 closure evidence | D8.7 disposition |
| --- | --- | --- |
| D9-G-01 installed command | One versioned wheel; exact SHA-256; D8.1 resolves `stygnox` outside new/clean/dirty worktrees. | CLOSE WHEN D8.7 PASS |
| D9-G-02 neutral surfaces | Wheel import scan plus D8.1/D8.6A/D8.6B installed CLI/Web/TUI gates; no legacy Ralph import dependency. | CLOSE WHEN D8.7 PASS |
| D9-G-03 new bootstrap | D8.2/D8.3 new-unborn preview, handoff, interruption revalidation, safe stop and exact restore against the release wheel. | CLOSE WHEN D8.7 PASS |
| D9-G-04 tracked/runtime boundary | D8.2/D8.3 prove tracked config/policy review and ignored controller-owned `.stygnox/` runtime. | CLOSE WHEN D8.7 PASS |
| D9-G-05 neutral identity/controller | D8.5 neutral profile/policy/controller qualification against the release wheel. | CLOSE WHEN D8.7 PASS |
| D9-G-06 no local fallback | D8.1–D8.6 hostile `ralph*` decoys plus release wheel import scan. | CLOSE WHEN D8.7 PASS |
| D9-G-07 clean adoption | D8.2/D8.3 clean baseline revalidation, handoff and exact restoration against the release wheel. | CLOSE WHEN D8.7 PASS |
| D9-G-08 dirty adoption | D8.2/D8.3 independently owned dirty capture/attestation and fail-closed verification against the release wheel. | CLOSE WHEN D8.7 PASS |
| D9-G-09 untracked restoration | D8.3 dirty round trip covers untracked content, modes and empty directories and compares exact post-restore state. | CLOSE WHEN D8.7 PASS |
| D9-G-10 extraction migration | D8.4 clean/dirty supported legacy migration, retained inventory, rollback and source-fallback isolation against the release wheel. | CLOSE WHEN D8.7 PASS |
| D9-G-11 upgrade/uninstall | D8.4 support policy, upgrade compatibility, uninstall preparation, actual pip uninstall and retained-evidence readability. | CLOSE WHEN D8.7 PASS |
| D9-G-12 Web/TUI | D8.6A/D8.6B installed Web/TUI/operator parity with loopback-only Web policy. | CLOSE WHEN D8.7 PASS |
| D9-G-13 reconciliation UX | D8.6 operator model exposes operator/native/runtime/external/unresolved attribution, human-decision stop, `auto_adopt=false`, `auto_reattribute=false`. | CLOSE WHEN D8.7 PASS |
| D9-G-14 release docs | Release set contains the operator guide, closure map, post-extraction report, README, detailed stage docs and license. | CLOSE WHEN D8.7 PASS |
| D9-G-15 exact artifact | D8.7 builds once and supplies the same wheel digest to every predecessor installed qualifier. | CLOSE WHEN D8.7 PASS |
| D9-G-16 post-extraction report | `docs/d8-7-post-extraction-report.md` plus wheel/source scans classify each retained legacy reference. | CLOSE WHEN D8.7 PASS |
| D9-G-17 `scripts/ralph.py` coupling | Installed wheel and operator docs contain no normal-path `python3 scripts/ralph.py`; hostile target-local decoys remain refused. | CLOSE WHEN D8.7 PASS |

D9-G-18 remains the documented post-D9 non-semantic UX category and is not a
D9 release blocker while it does not alter authority or recovery semantics.

## Release artifacts

`scripts/build_d8_7_release.py` creates a deterministic release set containing:

- the supported install wheel;
- a deterministic source-review tarball containing source, tests, qualifiers,
  documentation, branding authority and provenance;
- `OPERATOR-GUIDE.md`;
- `RELEASE-CANDIDATE.md`;
- `POST-EXTRACTION-REPORT.md`;
- `LICENSE`;
- `release-manifest.json`; and
- `SHA256SUMS`.

The source-review archive is not an additional supported installation medium.
The wheel remains the install boundary declared by `stygnox support`.

## Build-once qualification

Every D8.1–D8.6B qualifier retains standalone operation, but D8.7 supplies the
release wheel through `STYGNOX_QUALIFICATION_WHEEL`. Each qualifier must report
the same wheel SHA-256. A mismatch is a release failure.

D8.7 also performs a second deterministic build only as a reproducibility
comparison. That second build is never substituted into predecessor gates; the
first immutable wheel remains the artifact under qualification.

## Pre-D9 findings carried into this gate

The full regression population remains the authority for the retained
compatibility controller. The material pre-D9 findings have explicit source
characterization:

- **D8-FINDING-02 — mixed self-hosting recovery deadlock:** retained
  self-hosting tests require exact same-plan grants, current fingerprints and
  explicit lifecycle expiry; mixed tooling/product attribution records only
  verified attribution.
- **D8-FINDING-03 — retired snapshot-only work re-entering ownership:**
  snapshot-only residue is external reconciliation, and replacement plans do
  not absorb approval-time residue as plan-owned work.
- **D8-FINDING-05 — semantic step failure laundered into PASS:** an explicit
  `BLOCKED_HUMAN` result required by step acceptance remains blocking even when
  generic validation/gates could otherwise pass.
- **D8-FINDING-06 — tooling carry-forward grant deadlock:** carry-forward
  tooling adoption requires current self-hosting authority; expired authority
  refuses and every candidate receives an explicit durable disposition rather
  than silent absorption.

These findings remain part of the source regression gate even though the legacy
controller is not part of the installed wheel.

## D9 no-go

Do not promote to D9 if any predecessor qualifier reports a different wheel
digest, any release checksum fails, deterministic rebuild differs, operator
documentation is absent, an installed module imports legacy Ralph code, dirty
restoration is not exact, unsupported legacy state mutates before refusal, or
any D8.1–D8.6B gate is not green.
