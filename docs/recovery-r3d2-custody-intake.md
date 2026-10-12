# R3D.2: blocked custody intake (source checkpoint `8030ff3`)

## Scope and evidence

This is a transaction-specific, **non-authorising** integration of the independently protected R3D.2 recovery artifacts. It does not supersede or weaken the Release 02I startup barrier, the Release 02N/02O Codex subprocess blocks, or the root-operated earlier namespace/exclusion primitives. Its output is **not** an exclusive handoff certificate.

The protected host inputs are fixed, never discovered by scanning the home directory:

| Evidence | SHA-256 |
| --- | --- |
| Original Git baseline tar | `8621e84834751c672a62926e4e085726e2139c3032bc33331189f091b5bb4a33` |
| 36-file control manifest | `a1a88ffa4cd4e82d018a3e54457e360dc79cb1210b9de56aa44fb57170bb2cff` |
| Five-file interrupted source manifest | `4d5f3b428f88a076f90ede6333e6af8bcfa754b2b5f0639f58c6ea62b9115547` |
| 609-file offline reconstruction manifest | `d305cd8eccb5cdb8b1c29bfdda614d53887a66c17d2a1a0ef2e792b34a1594eb` |

The validator pins transaction `TX-a6379f065ce68138`, plan `efe4acfaff25edc8fce015ec5c5f0e250a5f58e1a6a39ed569db71c5304cde03`, Git HEAD `1072451db2c85b340e4c78a7b895190ef1b3f5cd`, Step 2/4, eight continuation hashes/baselines, 16 controller canonical hashes, eight preview and baseline-pair bindings, the Step 1 receipt, and all preserved file digests. It reports only non-sensitive state and hashes, never prompt or credential contents.

These historical, user-observed hashes are not signed attestations of external provider identity. The corresponding protected files **have not been uploaded to this development workspace**; synthetic behavioral tests cannot replace a fresh host verification.

## Implementation

- `src/stygnox/direct_interruption_custody_intake.py`: standard-library-only reconciliation and one-time root-owned blocked receipt publication.
- `scripts/stygnox_recovery_custody_intake.py`: tightly scoped CLI, reads its exact colocated source module under `python3 -I -B`, has only `--audit` and `--seal-blocked`, and **always exits 75**. Exit 75 is a hard-deny for use in `ExecStartPre` or other boot gates, even after a successful evidence operation.
- `tests/test_stygnox_direct_interruption_custody_intake.py`: content, provenance, tampering, traversal, interrupted publication, and deny-default behavior tests.

The CLI **must never be run with `sudo` directly from a user-owned clone or tar extraction**. If a separate operator review approves a host evidence-intake trial, install the two Python files together in a *new*, root-owned, immutable deployment directory; verify exact file hashes, inode ownership and ancestor permissions first. Keep the currently staged `8030ff3` successor source immutable. The trusted CLI layout must be:

```text
<new-root-owned-deployment>/scripts/stygnox_recovery_custody_intake.py
<new-root-owned-deployment>/src/stygnox/direct_interruption_custody_intake.py
```

Then, and only then, invoke the protected script with `sudo python3 -I -B <new-root-owned-deployment>/scripts/stygnox_recovery_custody_intake.py --audit` and manually inspect its JSON. Exit **75 is expected even when `phase` is `EVIDENCE_RECONCILED_EXECUTION_BLOCKED`**. Treat any malformed output or another exit code as a refusal. Do not automatically chain `--seal-blocked` to `--audit`.

With explicit operator approval for an *evidence-only* publication, `--seal-blocked` writes the one-shot root-controlled receipt under `/var/lib/stygnox/recovery-r3d2-custody-8030ff3/custody-intake.json`. It does not access the user's live workspace. Existing receipt or `.pending` directory is an error; no retry, rollback or silent repair is provided. Only the root-controlled input directory is writable by this operation. A crash after creating `.pending` requires independent reconciliation.

**A digest match only means that the immutable user-supplied evidence has been preserved and related correctly.** It does not revoke legacy Codex OAuth or open descriptors, exclude new launches of the old controller, establish root-owned exclusive execution, or prove reboot-safe cutover.

## Remaining integrated handoff work (not delivered by this patch)

1. Root supervisor must enforce and attest absence of competing predecessor authority *in the actual host*, including re-launches, already-open handles, and potential external Codex sessions, without disrupting unrelated user sessions.
2. Original active workspace identity and approved authority must be retired with an auditable, crash-safe transaction boundary. Existing C3f/C3g path-retirement primitives have strict root-controlled parent assumptions not met merely by a home-directory workspace.
3. The successor must use separately provisioned credentials and a transaction-bound one-shot claim; the 02N/02O unconditional provider denials must remain until an independently reviewed authorising dispatch is implemented and tested.
4. Prove reboot, interrupted publication, stale process, duplicate claim and record-substitution handling on the target host. Release remains an **explicit operator decision** after these gates, not an automatic result of a successful custody intake.

Do not execute provider, alter the original runtime, stop Codex sessions, run a live C3g retirement, or bypass 02N/02O on the basis of this component.
