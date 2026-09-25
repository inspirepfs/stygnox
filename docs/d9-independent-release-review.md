# D9 independent release review

D9 is a release decision, not a feature stage. The runtime/controller architecture remains frozen unless independent evidence identifies a release-blocking defect.

## Release-hardening findings

- **D9-F01 — cross-builder reproducibility:** the D8.7 wheel was produced through the host setuptools/wheel toolchain, so materially different builders could produce different wheel bytes. The D9 release candidate uses a project-owned canonical standard-library wheel assembler with fixed member order, timestamps, modes, metadata and `RECORD` generation.
- **D9-F02 — contribution/commercial governance:** repository governance is present and is included in the source-review release set. It remains separate from runtime code.
- **D9-F03 — stale development-stage wording:** operator-facing CLI/Web/product identity no longer describes D8.6/D8.7 as a future gate.
- **D9-F04 — final version identity:** the independently reproduced hardening candidate has been promoted to `0.1.0`. The `v0.1.0` tag is permitted only after an independent supported host reproduces the canonical `0.1.0` wheel digest and the D9 gate reports `QUALIFIED_FOR_TAGGING`.

## Canonical build contract

The supported install artifact is the wheel. Its byte representation is built without setuptools/wheel runtime dependencies by `scripts/build_d8_7_release.py`. The release manifest records the canonical generator and the absence of host setuptools/wheel dependencies.

The source-review archive carries product source, tests, qualification tooling, branding authority, provenance and licensing/contribution governance. The installed wheel must not contain repository-only governance, tests, Ralph source wrappers or provenance material; it carries AGPL licence metadata plus NOTICE/trademark material in its `.dist-info` directory.

## Decision gate

Run:

```bash
python3 scripts/qualify_d9_release_review.py
```

A passing final qualification reports `QUALIFIED_FOR_TAGGING`, but the release tag is pushed only after an independent supported host builds the same canonical `0.1.0` wheel SHA-256.
