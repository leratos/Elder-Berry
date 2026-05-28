---
description: Start an Elder-Berry phase safely
---

Start an Elder-Berry phase using the repository guardrails.

Required workflow:

1. Read `AGENTS.md`.
2. Read project memory with `journal_read(project="elder-berry", n=20)`.
3. If the phase context is unclear, use `journal_search(project="elder-berry",
   query=..., limit=...)`.
4. Check the current branch. If needed, propose or create
   `feature/phase-X-short-description`.
5. Name the files you expect to edit.
6. Append an `in_arbeit` journal entry before editing.
7. Wait for confirmation unless the user explicitly already said to proceed.

Do not write to `docs/journal.txt`.
