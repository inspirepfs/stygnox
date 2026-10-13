# R3D.2 break-glass: offline adoption of existing tracked policy

**Operator decision:** explicit formal override reported on 2026-10-13, for the forward development checkout only.

**Source base:** `recovery/r3d2-forward` at `3d71dd1901b4c2318dcd7aad3a9926694c668d5b`.

## Specific failure

`stygnox adopt preview` for the reviewed Codex policy routes through `execution_policy.bind_provider_catalog()`, whose `provider_codex.model_catalog()` launcher hits unconditional recovery guard 02N before contacting Codex.

## Approved narrowed behavior

`--offline-existing-policy` is an explicit opt-in for `adopt preview`, `adopt abort` and `adopt handoff` only. It:

- requires a clean Git worktree with no `.stygnox` runtime;
- requires a non-neutral, named-reviewer Codex policy;
- refuses unless both `stygnox.toml` and `stygnox.policy.md` are tracked regular files with the exact approved rendered bytes;
- does not start Codex or fetch model metadata;
- marks the preview `provider_catalog_deferred=true`, and binds the approval hash to that fact;
- preserves the original 02N provider launcher refusal and all historical root custody/execution denial;
- prevents unbound catalogue policy being labelled provider-ready or used in controller execution previews.

This is a bootstrap-only exception; neither the old ACTIVE transaction nor the new project is authorised to execute a Codex turn by this document or switch. The reviewed model/effort remain **unverified against live catalogue**. Plan/provider execution requires a separately reviewed and qualified release path and explicit user approval.

No changes to the interrupted original workspace or root-custody records are allowed under this exception. The human handoff confirmation remains a separate approval step bound to the exact fresh preview hash.
