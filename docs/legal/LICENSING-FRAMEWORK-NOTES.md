# StygNox licensing framework maintenance notes

The repository licensing framework is part of the project's release governance, not an installation step.
These notes preserve the review safeguards from the original one-time licensing-pack application guidance.

## Canonical governance files

The project should keep the following files mutually consistent:

- `LICENSE` — unmodified GNU AGPL v3 licence text;
- `LICENSING.md` — community and alternative-licensing overview;
- `COMMERCIAL-LICENSING.md` — alternative commercial-licensing route;
- `CLA.md` and `CONTRIBUTING-LICENSING.md` — contribution/relicensing grant and sign-off process;
- `RECOGNITION.md`, `CONTRIBUTORS.md`, and `CREDITS.md` — durable contribution and idea provenance;
- `NOTICE.md` and `TRADEMARK.md` — copyright/licence notice and project-identity boundary;
- `docs/legal/SOURCE-HEADER.md` — recommended SPDX/source-header form.

## Release review checkpoint

Before a public release, confirm that:

- `LICENSE` remains the unmodified GNU AGPL v3 text;
- project-facing files consistently say `AGPL-3.0-only` where that is the intended community licence;
- accepted third-party contributions have the required authority/CLA record;
- dependencies, vendored material and bundled assets retain any separate required notices;
- commercial-licensing contact/funding details are current;
- trademark wording does not imply a registration that has not been obtained; and
- the source-review release archive contains the governance material while the installed runtime wheel contains only the licence/notice metadata it needs.

## Legal review

The standard AGPL text should remain unchanged. The custom CLA, commercial-licensing policy and trademark policy are project-specific documents and should receive professional legal review before they are relied on for a material commercial agreement or dispute.
