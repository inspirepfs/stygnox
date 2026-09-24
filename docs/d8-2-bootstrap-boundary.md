# D8.2 bootstrap and tracked-policy / ignored-runtime boundary

## Stage outcome

D8.2 extends the installed Stygnox product with a bounded adoption bootstrap.
The installed command can now inspect an adopting Git worktree, produce a
**read-only preview**, bind explicit human confirmation to that exact preview,
and record a bootstrap handoff that materializes reviewed tracked policy/config
and ignored controller-owned runtime evidence.

The installed surface is:

```text
stygnox adopt preview  --project PATH --operator NAME
stygnox adopt abort    --project PATH --operator NAME --preview SHA256
stygnox adopt handoff  --project PATH --operator NAME --preview SHA256 --confirm HANDOFF
```

`stygnox bootstrap` is an equivalent installed alias.  No command delegates to
`ralph`, `ralph_*`, a target-local controller, or the Stygnox source tree.

## Exact authority boundary

Preview is no-change.  Before handoff Stygnox may inspect Git and render the
proposed tracked files, but it does not create `stygnox.toml`,
`stygnox.policy.md`, `.stygnox/`, or modify `.gitignore`.

A handoff is valid only when all of the following remain exact:

- installed `stygnox` resolves outside the adopting worktree;
- the Git baseline fingerprint is unchanged;
- the named operator is unchanged;
- the full proposed tracked configuration/policy bytes are unchanged;
- the runtime boundary remains `/.stygnox/` and controller-owned;
- any dirty-repository external recovery attestation remains exact; and
- the operator supplies the literal `--confirm HANDOFF` plus the exact preview
  SHA-256.

Any mismatch refuses before bootstrap mutation and requires a fresh preview.

The D8.2 handoff grants **bootstrap-policy-runtime-boundary-only** authority.
It does not grant autonomous controller execution.

## Tracked project material

Handoff creates the reviewed `stygnox.toml` and `stygnox.policy.md`, and adds a
root `/.stygnox/` ignore rule when the project does not already have an
equivalent rule.  The config keeps provider, model, and effort neutral and
records that controller execution is false at this stage.

These files are ordinary project material.  They remain visible to Git review
and qualification; ignored runtime can never substitute for them.

## Controller runtime

`.stygnox/` is ignored project-local controller bookkeeping.  D8.2 records the
confirmed bootstrap handoff in `.stygnox/adoption.json` only **after** tracked
ignore policy has been materialized and verified.  The supported runtime-write
API accepts only the controller actor and rejects agent writes.

Ignored runtime is not a qualified native project delta.  This is a controller
boundary, not a claim that POSIX permissions can distinguish two processes
running as the same operating-system user.

## Dirty repositories and D8.3 ownership

D8.2 does **not** create, own, or restore dirty-repository recovery material.
A dirty handoff requires an operator-owned external attestation whose baseline
fingerprint matches the current worktree and whose external capture digest
verifies.  The attestation must state that independent restoration was
rehearsed and identify the verifier and all dirty categories represented.

This only qualifies D8.2's admission boundary and external-custody contract.
D8.3 owns the supported capture format, transactional execution, interruption,
rollback, restoration and full clean/dirty recovery qualification.

## Qualification

Run:

```bash
python3 scripts/qualify_d8_2_bootstrap.py
```

The qualifier builds one immutable wheel, installs that exact artifact into a
fresh virtual environment, and exercises new/unborn, clean and dirty fixtures.
It proves preview/abort are no-change, stale baseline or policy invalidates
confirmation, handoff is explicit, tracked policy remains reviewable, runtime
is ignored, agent runtime writes are refused through the installed API, and
hostile Ralph decoys are not imported.

For the dirty fixture the qualification harness independently creates an
external capture, restores it into a separate location, compares Git status and
worktree content/modes, and only then supplies the external attestation to the
installed D8.2 admission surface.  That rehearsal is qualification evidence;
it is not a shipped D8.3 recovery implementation.
