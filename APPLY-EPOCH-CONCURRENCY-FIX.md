# R3D.2 — Epoch-reservation concurrency correction

**Source baseline:** `2769e6e` plus the integrated denied-only cutover overlay already applied locally. This archive changes only `src/stygnox/direct_interruption_epoch_reservation.py` and its existing test file.

## Root cause

Two publishers can both pass a non-atomic `SLOT`/`.pending` absence check. One publishes the record and renames `.pending` into `SLOT`; a delayed second publisher can then create `.pending` again. The result is a valid winning record accompanied by a stale marker, which the reader correctly refuses. Depending on timing, `os.rename` could also replace the first writer's completed directory.

## Correction

Acquire a nonblocking exclusive Linux `flock` on the already opened, verified private root directory before checking for a slot or pending marker, and hold it through write, rename and fsync. A concurrent publisher refuses; late publishers find the existing final slot. A process crash drops the kernel lock while retaining an interrupted `.pending` marker, which continues to block execution.

This lock coordinates publishers that use the trusted function. It is **not** host-wide legacy-process exclusion, controller admission, or provider release.

## Regression evidence

- A deterministic delayed-directory-claim test was run against the original publisher and failed with the same stranded `.pending` error reported on the host.
- The corrected publisher passes that test, the existing eight-thread one-winner test, and a separate eight-process contention test against real Linux filesystem operations.
- Selected recovery regression groups passed with exit code 0: **169 passed, 5 skipped**; **104 passed, 3 skipped, 14 subtests passed**. These do not qualify the actual host-enforced cutover or the complete historical test suite.

## Host use

Do not apply this archive to any deployed `/usr/local/libexec` tree or `/var/lib/stygnox` slot. Apply only to the development checkout, rerun the source tests as directed in the conversation, then inspect before committing. Do not delete any `.pending` record on the live host.
