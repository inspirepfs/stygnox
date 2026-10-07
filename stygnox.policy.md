# Stygnox Project Policy

Schema: `stygnox_project_policy_v1`
Runtime: `.stygnox/`
Named operator / human decision maker: `pfsykes`
Execution-policy reviewer: `pfsykes`
Reviewed provider/model/effort: `codex` / `gpt-5.6-terra` / `high`

## D8.2 bootstrap authority

- This tracked file and `stygnox.toml` are project material and remain subject
  to normal Git review. Ignored runtime material never substitutes for them.
- `.stygnox/` is controller-owned runtime. Agents and implementation
  workers must not create, edit, delete, rename, or adopt content there.
- Provider, model, and effort default to neutral. Any non-neutral selection
  shown above is bound to this tracked policy/configuration preview and named
  reviewer before authority handoff. Changing it invalidates confirmation.
- The D8.2 handoff grants only the exact bootstrap writes previewed by the
  installed command. It does **not** grant autonomous controller execution.
- A changed baseline, changed tracked policy/configuration, changed external
  dirty-recovery evidence, or expanded scope invalidates confirmation and
  requires a fresh preview and explicit handoff.
- D8.3 owns transaction, interruption, rollback, and restoration behavior.
