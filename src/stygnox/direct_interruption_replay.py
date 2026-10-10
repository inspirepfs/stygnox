"""Read-only receipt-chain reconstruction for failed DIRECT controller turns.

Not an execution grant, controller receipt, qualification PASS, or rebase.
Only existing integrity-checked accepted controller receipts may establish the
pre-interruption repository manifest. Any missing/ambiguous history fails closed.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Callable

HEX = re.compile(r"^[0-9a-f]{64}$")
REQUIRED = ("before_manifest_sha256", "after_manifest_sha256", "paths")

class EvidenceRefused(RuntimeError):
    pass


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def checked(record: object, field: str = "record_sha256") -> dict:
    if not isinstance(record, dict):
        raise EvidenceRefused("record is not a JSON object")
    sha = record.get(field)
    body = dict(record)
    body.pop(field, None)
    if not isinstance(sha, str) or not HEX.fullmatch(sha) or digest(body) != sha:
        raise EvidenceRefused(f"{field} missing or invalid")
    return record


def _relative(value: object, *, allow_protected: bool = False) -> str:
    if not isinstance(value, str) or not value or '\\' in value or '\x00' in value:
        raise EvidenceRefused(f"invalid repository path: {value!r}")
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or p.as_posix() != value or value.startswith('./') or value.endswith('/'):
        raise EvidenceRefused(f"noncanonical repository path: {value!r}")
    if p.parts[0] in ('.git', '.stygnox') or (p.parts[0] == '.ralph' and not allow_protected):
        raise EvidenceRefused(f"runtime or protected path in manifest evidence: {value}")
    return value


def _manifest(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise EvidenceRefused("immutable repository manifest missing")
    result: dict[str,str] = {}
    for raw, fingerprint in value.items():
        key = _relative(raw, allow_protected=True)
        if not isinstance(fingerprint, str) or not HEX.fullmatch(fingerprint):
            raise EvidenceRefused(f"invalid manifest fingerprint: {key}")
        result[key] = fingerprint
    return result


def _scope(value: object) -> list[str]:
    if not isinstance(value, list) or not value:
        raise EvidenceRefused("immutable write scope missing")
    result = [_relative(p) for p in value]
    if result != sorted(set(result)):
        raise EvidenceRefused("scope must be sorted and unique")
    return result


def _receipt_delta(receipt: Mapping[str,Any], *, plan_hash: str, tx: str, scope: list[str]) -> dict:
    r = checked(dict(receipt))
    binding = r.get("plan_binding")
    delta = r.get("actual_delta")
    if (r.get("schema") != "stygnox_controller_run_result_v1"
        or r.get("repository_authority") != "write" or r.get("transaction_id") != tx
        or r.get("human_gate") is not None or not isinstance(binding, Mapping)
        or binding.get("plan_hash") != plan_hash
        or binding.get("repository_mutation_scope") != scope
        or binding.get("repository_mutation_scope_sha256") != digest(scope)
        or not isinstance(r.get("provider_result"), Mapping)
        or r["provider_result"].get("status") != "PASS"
        or r.get("next_action") not in ("continue-same-step", "qualification-required", "turn-complete")
        or not isinstance(delta, Mapping)):
        raise EvidenceRefused("accepted controller receipt authority/scope/provider evidence invalid")
    body = {key: delta.get(key) for key in REQUIRED}
    if delta.get("delta_sha256") != digest(body) or not isinstance(body["paths"],list):
        raise EvidenceRefused("accepted controller receipt delta digest is invalid")
    for field in REQUIRED[:2]:
        if not isinstance(body[field],str) or not HEX.fullmatch(body[field]):
            raise EvidenceRefused("accepted controller receipt manifest digest missing")
    return dict(delta)


def _apply(before: dict[str,str], delta: Mapping[str,Any], scope: set[str], approval: dict[str,str],
           *, add_only: bool) -> dict[str,str]:
    if digest(before) != delta.get("before_manifest_sha256"):
        raise EvidenceRefused("accepted receipt before-manifest discontinuity")
    out = dict(before)
    seen=set()
    for row in delta["paths"]:
        if not isinstance(row, Mapping):
            raise EvidenceRefused("malformed accepted receipt path row")
        path = _relative(row.get("path"))
        old,new = row.get("before_fingerprint"), row.get("after_fingerprint")
        kind = "created" if old is None else "deleted" if new is None else "modified"
        if path in seen or path not in scope or row.get("kind") != kind or old == new:
            raise EvidenceRefused("duplicate, out-of-scope or impossible accepted receipt delta")
        seen.add(path)
        if old is not None and (not isinstance(old,str) or not HEX.fullmatch(old)):
            raise EvidenceRefused("malformed before fingerprint")
        if new is not None and (not isinstance(new,str) or not HEX.fullmatch(new)):
            raise EvidenceRefused("malformed after fingerprint")
        if out.get(path) != old:
            raise EvidenceRefused("accepted receipt path fingerprint does not match predecessor")
        if add_only and path.startswith("tests/") and path in approval:
            raise EvidenceRefused("accepted receipt mutated an approval-time existing test")
        if new is None:
            out.pop(path,None)
        else:
            out[path]=new
    if digest(out) != delta.get("after_manifest_sha256"):
        raise EvidenceRefused("accepted receipt after-manifest digest mismatch")
    return out


def _accepted_references(state: Mapping[str,Any], *, steps: list) -> list[tuple[str,str,Mapping[str,Any],int]]:
    """Derive event order from the accepted plan, not from repository-manifest hashes.

    Each completed step's continuations precede its qualification PASS.  Both
    are written to separate plan arrays, and no-op receipts legitimately share
    the exact same before- and after-manifest.  Unreferenced receipts are never
    inferred as accepted merely because their delta matches the manifest.
    """
    step = state.get("current_step")
    if type(step) is not int or step < 1 or step > len(steps):
        raise EvidenceRefused("invalid current step")
    completed = {}
    for row in state.get("step_results") or []:
        if not isinstance(row, Mapping):
            raise EvidenceRefused("malformed accepted step result")
        if row.get("result") == "HUMAN_CONFIRMED":
            continue
        if row.get("result") != "PASS":
            raise EvidenceRefused("unaccepted step result")
        checked(dict(row))
        n = row.get("step")
        sha = row.get("controller_receipt_sha256")
        if type(n) is not int or not 1 <= n <= step or n in completed or not isinstance(sha,str) or not HEX.fullmatch(sha):
            raise EvidenceRefused("duplicate, displaced, or malformed accepted step result")
        completed[n] = ("sha", sha, row, n)
    continuations = state.get("continuation_history")
    if not isinstance(continuations,list) or not continuations:
        raise EvidenceRefused("no accepted continuation history")
    by_step = {}
    previous_step = 0
    for row in continuations:
        checked(row)
        n = row.get("step")
        sha = row.get("origin_preview_sha256")
        if (row.get("plan_hash") != state.get("plan_hash") or type(n) is not int
            or n < previous_step or not 1 <= n <= step
            or not isinstance(sha,str) or not HEX.fullmatch(sha)):
            raise EvidenceRefused("displaced, invalid, or reordered accepted continuation")
        previous_step = n
        by_step.setdefault(n,[]).append(("origin", sha, row, n))
    ordered=[]
    for n in range(1,step+1):
        ordered.extend(by_step.get(n,[]))
        if n in completed:
            ordered.append(completed[n])
    return ordered


def _accepted_receipts(state: Mapping[str,Any], *, steps: list,
                       receipt_loader: Callable[[str],dict], plan_hash: str,
                       tx: str, scope: list[str],
                       recovery_edge: tuple[list[str],str,str] | None = None) -> list[tuple[dict,dict,str,Mapping[str,Any]]]:
    """Resolve each *explicitly accepted* event and prove ordered baseline linkage."""
    ordered=[]
    seen_receipts=set()
    seen_origins=set()
    last_baseline=state.get("approval_baseline_sha256")
    lineage=[]
    for how,identifier,reference,n in _accepted_references(state,steps=steps):
        try:
            receipt=receipt_loader(identifier)
        except KeyError as exc:
            raise EvidenceRefused("missing accepted controller receipt") from exc
        if not isinstance(receipt,dict):
            raise EvidenceRefused("missing accepted controller receipt")
        delta=_receipt_delta(receipt,plan_hash=plan_hash,tx=tx,scope=scope)
        if ((how == "sha" and receipt.get("record_sha256") != identifier)
            or (how == "origin" and receipt.get("preview_sha256") != identifier)
            or (receipt.get("plan_binding") or {}).get("current_step") != n):
            raise EvidenceRefused("accepted controller receipt identity or step mismatch")
        if receipt["record_sha256"] in seen_receipts or receipt.get("preview_sha256") in seen_origins:
            raise EvidenceRefused("duplicate accepted controller provenance")
        seen_receipts.add(receipt["record_sha256"])
        seen_origins.add(receipt.get("preview_sha256"))
        if recovery_edge is not None and lineage == recovery_edge[0]:
            if last_baseline != recovery_edge[1]:
                raise EvidenceRefused("reviewed recovery predecessor baseline does not match accepted chain")
            last_baseline=recovery_edge[2]
        before=receipt.get("before_baseline_sha256")
        after=receipt.get("after_baseline_sha256")
        if not isinstance(before,str) or not HEX.fullmatch(before) or not isinstance(after,str) or not HEX.fullmatch(after):
            raise EvidenceRefused("accepted controller receipt baseline identity missing")
        if isinstance(last_baseline,str) and HEX.fullmatch(last_baseline) and before != last_baseline:
            raise EvidenceRefused("accepted controller baseline discontinuity")
        if how == "origin":
            if (receipt.get("next_action") != "continue-same-step"
                or reference.get("before_baseline_sha256") != before
                or reference.get("after_baseline_sha256") != after):
                raise EvidenceRefused("accepted continuation does not match exact controller baseline/action")
        else:
            if (receipt.get("next_action") not in ("turn-complete", "qualification-required")
                or reference.get("qualified_baseline_sha256") != after):
                raise EvidenceRefused("accepted step qualification does not match controller receipt")
        last_baseline=after
        lineage.append(receipt["record_sha256"])
        ordered.append((receipt,delta,how,reference))
    return ordered


def reconstruct_predecessor(state: Mapping[str,Any], *, receipt_loader: Callable[[str],dict]) -> dict:
    """Reconstruct accepted source state by exact step/continuation provenance.

    Matching manifest digests are only integrity checks, never ordering authority.
    """
    if state.get("status") != "APPROVED" or state.get("active_gate") is not None or state.get("self_development_grant") is not None:
        raise EvidenceRefused("predecessor plan is not cleanly approved")
    approval=_manifest(state.get("approval_repository_manifest"))
    plan=state.get("plan")
    if not isinstance(plan,Mapping):
        raise EvidenceRefused("approved plan missing")
    scope=_scope(plan.get("repository_mutation_scope"))
    if plan.get("repository_mutation_scope_sha256") != digest(scope) or state.get("repository_mutation_scope") != scope:
        raise EvidenceRefused("plan mutation scope digest mismatch")
    steps=plan.get("steps")
    if not isinstance(steps,list) or not steps:
        raise EvidenceRefused("approved plan steps missing")
    sequence=_accepted_receipts(state,steps=steps,receipt_loader=receipt_loader,
                                plan_hash=state["plan_hash"],tx=state["transaction_id"],scope=scope)
    current=dict(approval)
    receipt_shas=[]
    for r,delta,_,_ in sequence:
        prior_step=(r.get("plan_binding") or {}).get("current_step")
        policy=steps[prior_step-1].get("test_change_policy") if type(prior_step) is int and 1 <= prior_step <= len(steps) else None
        if policy not in ("add-only","none"):
            raise EvidenceRefused("accepted receipt step or test policy invalid")
        current=_apply(current,delta,set(scope),approval,add_only=policy=="add-only")
        if policy == "none" and any(item["path"].startswith("tests/") for item in delta["paths"]):
            raise EvidenceRefused("accepted receipt violates no-test policy")
        receipt_shas.append(r["record_sha256"])
    last=sequence[-1][0]
    continuations=state["continuation_history"]
    # The interrupted turn's predecessor is specifically the latest accepted
    # same-step continuation, not a completed step result or an abandoned receipt.
    if (last.get("preview_sha256") != continuations[-1].get("origin_preview_sha256")
        or last["record_sha256"] != receipt_shas[-1]
        or digest(current) != last["actual_delta"]["after_manifest_sha256"]
        or state.get("step_authority_baseline_sha256") != last.get("after_baseline_sha256")):
        raise EvidenceRefused("last accepted controller checkpoint identity mismatch")
    return {"predecessor_manifest":current,
            "predecessor_manifest_sha256":digest(current),
            "accepted_controller_receipt_sha256s":receipt_shas,
            "last_accepted_controller_receipt_sha256":last["record_sha256"],
            "approval_manifest_sha256":digest(approval),
            "repository_mutation_scope_sha256":digest(scope)}


def verify_reviewed_transition(state: Mapping[str,Any], preview: Mapping[str,Any],
                               *, receipt_loader: Callable[[str],dict]) -> dict:
    """Prove exactly what changed AFTER the last accepted controller turn.

    This never infers that the interrupted provider had execution/self-development
    authority. A human can separately review identified source changes later.
    """
    checked(dict(preview),"preview_sha256")
    ancestor=reconstruct_predecessor(state,receipt_loader=receipt_loader)
    before=ancestor["predecessor_manifest"]
    current=_manifest(preview.get("candidate_manifest"))
    if preview.get("candidate_manifest_sha256") != digest(current):
        raise EvidenceRefused("candidate manifest digest mismatch")
    if preview.get("last_accepted_manifest_sha256") != ancestor["predecessor_manifest_sha256"]:
        raise EvidenceRefused("preview last-accepted manifest mismatch")
    if preview.get("last_accepted_controller_receipt_sha256") != ancestor["last_accepted_controller_receipt_sha256"]:
        raise EvidenceRefused("last accepted receipt was substituted")
    if preview.get("approval_manifest_sha256") != ancestor["approval_manifest_sha256"]:
        raise EvidenceRefused("approval manifest substituted")
    if preview.get("plan_hash") != state.get("plan_hash") or preview.get("transaction_id") != state.get("transaction_id"):
        raise EvidenceRefused("review snapshot refers to wrong plan or transaction")
    if preview.get("predecessor_baseline_sha256") != state.get("step_authority_baseline_sha256"):
        raise EvidenceRefused("review snapshot predecessor baseline is stale")
    scope=set(_scope(state["plan"]["repository_mutation_scope"]))
    approval=_manifest(state["approval_repository_manifest"])
    changed=[]
    for p in sorted(set(before)|set(current)):
        prior,after=before.get(p),current.get(p)
        if prior == after:
            continue
        if p not in scope or p in ("stygnox.toml", "stygnox.policy.md"):
            raise EvidenceRefused(f"interrupted turn changed operator-owned or out-of-scope path: {p}")
        if p.startswith("tests/") and p in approval:
            raise EvidenceRefused(f"interrupted turn changed approval-existing test: {p}")
        if not p.startswith("src/stygnox/") and not p.startswith("tests/test_stygnox_"):
            raise EvidenceRefused(f"interrupted change is not the exact scoped self-development surface: {p}")
        if prior is None and after is not None: kind="created"
        elif prior is not None and after is None: kind="deleted"
        else: kind="modified"
        changed.append({"path":p,"kind":kind,"before_fingerprint":prior,"after_fingerprint":after})
    if not changed:
        raise EvidenceRefused("interrupted turn has no repository delta to review")
    body={"predecessor_manifest_sha256":ancestor["predecessor_manifest_sha256"],
          "candidate_manifest_sha256":digest(current),
          "origin_preview_sha256":preview.get("origin_preview_sha256"),
          "changed_paths":changed,
          "operator_config_unchanged":before.get("stygnox.toml")==current.get("stygnox.toml"),
          "classification":"UNATTRIBUTED_INTERRUPTED_SOURCE_REQUIRES_HUMAN_REVIEW",
          "past_provider_success":False,"retrospective_grant":False}
    if not body["operator_config_unchanged"]:
        raise EvidenceRefused("operator configuration was not proved unchanged")
    body["proof_sha256"]=digest(body)
    return {**ancestor,**body}


def build_provenance_preview(project: Path, origin_file: Path, expected_preview: str,
                             reviewed_paths: list[str]) -> dict:
    """Inspect a real isolated Stygnox install and the live project READ-ONLY."""
    from . import adoption, planning, direct_interruption
    root=adoption.resolve_worktree(project)
    try:
        reviewed=direct_interruption.review_preview(root,origin_file,expected_preview,reviewed_paths)
    except direct_interruption.RecoveryRefused as exc:
        raise EvidenceRefused(f"Stage A review refused: {exc}") from exc
    state=planning._record(root)
    if not isinstance(state,dict):
        raise EvidenceRefused("missing integrity-checked plan record")
    runtime=root/adoption.RUNTIME_NAME
    def loader(identifier: str) -> dict:
        if not isinstance(identifier,str) or not HEX.fullmatch(identifier):
            raise EvidenceRefused("unrecognised accepted receipt identifier")
        path=runtime/f"controller-run-{identifier[:16]}.json"
        if not path.is_file() or path.is_symlink():
            # Completed step results use record digests, not origin previews.
            # Full-sha match is required. Files with invalid content are ignored;
            # a duplicate matching digest is rejected.
            matches=[]
            for candidate in runtime.glob("controller-run-*.json"):
                if candidate.is_symlink() or not candidate.is_file():
                    raise EvidenceRefused("unsafe controller receipt path")
                try:
                    obj=json.loads(candidate.read_text(encoding="utf-8"))
                except (OSError,ValueError):
                    raise EvidenceRefused("malformed controller receipt in runtime")
                if isinstance(obj,dict) and obj.get("record_sha256")==identifier:
                    matches.append(obj)
            if len(matches)!=1:
                raise EvidenceRefused("missing or duplicate matching step controller receipt")
            return checked(matches[0])
        try:
            result=json.loads(path.read_text(encoding="utf-8"))
        except (OSError,ValueError) as exc:
            raise EvidenceRefused("invalid controller receipt") from exc
        checked(result)
        if result.get("preview_sha256") != identifier:
            raise EvidenceRefused("origin preview filename/receipt mismatch")
        return result
    proof=verify_reviewed_transition(state,reviewed,receipt_loader=loader)
    return {"schema":"stygnox_direct_interruption_manifest_proof_v1",
            "worktree":str(root),"plan_hash":state["plan_hash"],
            "current_step":state["current_step"],
            "origin_preview_sha256":expected_preview,
            "review_preview_sha256":reviewed["preview_sha256"],
            "predecessor_manifest_sha256":proof["predecessor_manifest_sha256"],
            "candidate_manifest_sha256":proof["candidate_manifest_sha256"],
            "accepted_controller_receipt_sha256s":proof["accepted_controller_receipt_sha256s"],
            "changed_paths":proof["changed_paths"],
            "operator_config_unchanged":proof["operator_config_unchanged"],
            "proof_sha256":proof["proof_sha256"],
            "authority_changed":False,
            "recovery_admissible":False,
            "next_required_control":"separate reviewed attribution integration into authoritative qualification"}


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser=argparse.ArgumentParser(description="Read-only direct-interruption manifest provenance reconstruction")
    parser.add_argument("--project",type=Path,required=True)
    parser.add_argument("--origin-file",type=Path,required=True)
    parser.add_argument("--origin-preview-sha256",required=True)
    parser.add_argument("--review-path",action="append",required=True)
    args=parser.parse_args(argv)
    try:
        result=build_provenance_preview(args.project,args.origin_file,args.origin_preview_sha256,args.review_path)
    except (EvidenceRefused, OSError, ValueError) as exc:
        print(f"REFUSED: {exc}",file=__import__("sys").stderr)
        return 2
    print(json.dumps(result,indent=2,sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
