# D8.0 adoption contract

## Purpose and terms

This contract governs a human's adoption of Stygnox by a Git project.  It is
an operating contract, not an implementation instruction: it neither creates
files nor runs Stygnox in the adopting project.

* **Controller** means the installed Stygnox command and the controller state
  it owns.  The controller is not an agent.
* **Project** means the Git worktree being adopted.  Its operator retains
  ownership until the authority-handoff gate below succeeds.
* **Qualified native delta** means a change to tracked project material that is
  attributable to the approved work.  Ignored controller bookkeeping is not a
  project delta and is excluded from this evaluation.

Adoption requires a resolvable, installed Stygnox command.  It must not depend
on a target-project `scripts/ralph.py`, importing Stygnox from a source tree,
or a local Ralph fallback.  Failure to establish that command boundary aborts
admission; it is not repaired by copying or invoking legacy project tooling.

The default model and effort are neutral: no model, provider, or effort level
is implied by adoption.  A reviewer must explicitly choose any non-neutral
setting in tracked configuration or policy before authority is handed over.

## Shared admission and review gates

Before any controller authority is granted, the operator and reviewer must
complete all of the following:

1. Identify the exact Git worktree and confirm the installed command resolves
   outside that worktree.  Record its resolved executable/version and the
   worktree top level as adoption evidence.
2. Review proposed **tracked** Stygnox configuration and policy in the normal
   Git review flow.  The review records the command boundary, neutral defaults
   (or each explicitly approved override), protected paths, scope, and named
   human decision makers.
3. Preview the adoption plan, paths, controller runtime location, requested
   authority, and recovery procedure.  A human must explicitly confirm this
   preview; a command invocation, an agent response, or silence is not
   confirmation.
4. Confirm controller bookkeeping is in an ignored runtime location.  It is
   exclusively controller-owned, agents must not edit it, and it remains
   outside qualified native-delta evaluation.  Tracked configuration and
   policy remain reviewable project material; ignored runtime material does
   not become a substitute for them.
5. Record the pre-authority Git evidence described by the applicable journey.
   If it cannot be captured and independently restored, abort before handoff.

The **authority handoff** is a distinct, recorded human gate after items 1--5:
the named operator grants the controller only the reviewed, previewed scope.
Until that point, the controller may inspect and preview but may not change the
project.  Any expanded scope, changed policy/configuration, unresolved command
boundary, or changed baseline invalidates confirmation and requires a new
preview and explicit confirmation.

At every human gate, the operator can abort without granting or continuing
authority.  On abort, the controller makes no project change (or stops further
changes after a prior handoff), preserves evidence, and reports how to restore
the selected baseline.  Authority can be revoked at any time by a human; the
controller must stop at a safe boundary and retain only its ignored,
controller-owned bookkeeping.

## Journey A: a new Git project

**Admission.** The operator confirms that this is a newly initialized Git
worktree with the intended initial tracked content and no unreviewed adoption
residue.  Record `HEAD` (or the documented unborn-branch state), branch,
worktree top level, status, and the initial tracked file inventory.

**Preview and confirmation.** Show the installed command resolution, reviewed
tracked configuration/policy, neutral defaults, ignored controller runtime,
scope, and the no-change baseline.  The operator explicitly confirms the
preview.

**Handoff, interruption, and abort.** The operator then grants the recorded
authority handoff.  If interrupted before handoff, resume only by rechecking
the recorded no-change baseline and confirmation.  If interrupted or aborted
after handoff, stop work, preserve controller evidence, and return the
worktree to the recorded initial state through normal Git restoration chosen
by the operator.  Do not silently reset or discard user work.

**Rollback, restoration, and evidence.** Rollback targets the recorded initial
commit or unborn state and the tracked inventory; the operator approves the
restoration action.  Evidence includes the preview/confirmation and handoff
records, Git identity/status/inventory, tracked configuration/policy review,
command resolution, controller-runtime exclusion, interruption/abort record,
and verification that the selected baseline was restored.

## Journey B: an existing clean Git repository

**Admission.** The operator proves the repository is clean: no staged,
unstaged, renamed, deleted, or untracked project content.  Record `HEAD`,
branch, worktree top level, porcelain status, and a tracked-tree identity
(commit/tree identifier or equivalent reproducible inventory).  A clean
repository that changes while awaiting confirmation is no longer admitted and
must be previewed again.

**Preview and confirmation.** Present the shared review evidence and the clean
baseline.  The preview states exactly what authority will be handed over and
how the commit/tree baseline will be restored.  The operator explicitly
confirms.

**Handoff, interruption, and abort.** Handoff occurs only at the shared
authority-handoff point.  An interruption before it requires clean-baseline
revalidation and new confirmation.  An abort before it leaves the repository
unchanged.  After handoff, interruption or revocation stops the controller at
a safe boundary; it may not reinterpret pre-existing or new residue as its
native delta.

**Rollback, restoration, and evidence.** The operator selects and approves
restoration to the recorded clean `HEAD`/tree baseline.  Evidence includes all
shared-gate records, clean status and tree evidence before handoff, the
handoff/stop decision, the restoration action, and a post-restoration status
and tree comparison demonstrating recovery.

## Journey C: an existing dirty Git repository

**Admission and operator-owned baseline capture.** Dirty adoption is admitted
only when the operator, before authority handoff, preserves a complete,
restorable baseline outside controller authority.  The capture must describe
and preserve all staged, unstaged, renamed, deleted, and untracked content.
It is not sufficient to record paths, filenames, or a checkpoint path list.

The capture is restorable evidence and must include:

* repository identity: worktree top level, `HEAD` (or unborn state), branch,
  index/tree identity, and timestamp;
* staged changes as a reproducible patch or equivalent index snapshot;
* unstaged changes as a reproducible patch or equivalent worktree snapshot;
* renamed and deleted content with both status metadata and enough content/tree
  evidence to recreate the original and resulting states; and
* every untracked item as complete restorable material (for example, an
  operator-verified archive plus manifest with paths, types, modes, digests,
  and any required empty directories), stored where restoration remains
  possible.  A list of untracked paths alone is expressly inadequate.

The operator verifies that this evidence restores into a safe location or by a
documented reversible procedure before confirmation.  The capture location,
access method, integrity results, and restoration rehearsal/result are recorded
as evidence.  The controller and agent must not create, alter, or become sole
custodian of this operator-owned baseline.

**Preview and confirmation.** The preview separately displays the dirty
baseline categories, the location and verification of restorable evidence, the
reviewed tracked configuration/policy, neutral defaults, command resolution,
ignored controller runtime, requested authority, and rollback boundaries.  A
human explicitly confirms both that recovery evidence is complete and that the
specified authority may proceed.

**Handoff, interruption, and abort.** Only after that confirmation does the
operator grant the shared authority handoff.  Before handoff, any interruption,
baseline change, or failed recovery verification aborts adoption and requires a
new operator-owned capture and preview.  After handoff, an interruption,
abort, or authority revocation stops the controller at a safe boundary and
preserves its evidence without modifying the captured baseline.  Pre-authority
dirty material is never attributed to the controller.

**Rollback, restoration, and evidence.** Rollback first preserves any
post-handoff work the operator wishes to retain, then restores the exact
operator-owned dirty baseline using the verified staged/index, worktree,
rename/deletion, and untracked-content evidence.  The operator approves the
restoration and verifies status plus content/digests against the capture.
Evidence includes all shared-gate records; complete capture artifacts and
manifest; proof of restorability; explicit confirmation and handoff; records of
interruption, abort, or revocation; restoration commands/actions; and the
post-restoration comparison.

## Recovery and evidence retention

For every journey, clean-bootstrap recovery means that a failed, interrupted,
or abandoned initial adoption can return to the selected pre-authority clean
baseline (initial/unborn state for a new project, recorded clean tree for an
existing clean repository) without inventing controller ownership of project
content.  Dirty repositories use the stronger dirty-baseline procedure above,
not clean-bootstrap assumptions.

Evidence must remain available to the operator through handoff, execution,
abort, rollback, interruption, and restoration.  Controller runtime records
may assist diagnosis but never replace reviewed tracked policy/configuration or
operator-owned recovery evidence.  A journey is complete only when the human
records either successful adoption within the handed-over authority or verified
restoration after stopping it.
