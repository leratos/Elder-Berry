# Elder-Berry Git Guardrails

These hooks are a local safety net for agent-assisted work. They do not replace
`AGENTS.md`; they catch the two mistakes that are easiest for an LLM to make:

- committing directly on `main` or an unexpected branch
- committing without a Bramble MCP journal reference

Enable them once per clone:

```powershell
.\scripts\Install-AgentGuardrails.ps1
```

The hooks require commit messages to contain one of:

```text
Journal: elder-berry#123
Journal: skipped (short reason)
```

Emergency bypass:

```powershell
$env:ELDER_BERRY_SKIP_GUARDRAILS = "1"
git commit
Remove-Item Env:\ELDER_BERRY_SKIP_GUARDRAILS
```
