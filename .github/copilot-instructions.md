# Elder-Berry Copilot Guardrails

`AGENTS.md` is the source of truth. This file is intentionally short so VS Code
Chat sees the hard gates even when the full repository context is large.

For every phase, feature, bugfix, or substantial file change:

1. Read `AGENTS.md` first.
2. Read active project memory with `journal_read(project="elder-berry", n=20)`.
   If the state is unclear, use `journal_search(project="elder-berry", ...)`.
3. Before editing files, create or switch to a suitable branch. Phase work should
   use `feature/phase-X-short-description`.
4. Before editing files, append an `in_arbeit` entry to the Bramble MCP journal.
   If MCP journal tools are unavailable, say so clearly and ask before
   continuing.
5. Name the files you intend to change and wait for confirmation unless the user
   has explicitly asked you to proceed immediately.
6. Never write new entries to `docs/journal.txt`; it is historical only.
7. After edits, run focused tests with `.\.venv\Scripts\python.exe -m pytest`
   from the repository root and report the result.
8. After substantial work, append an `abgeschlossen`, `bugfix`, or `notiz`
   journal entry with tests, decisions, and follow-up work.
9. Commits must include a footer like `Journal: elder-berry#123`, or
   `Journal: skipped (reason)` for trivial work or MCP outages.

If a user asks for "auto", "just do it", or similar, still follow the journal,
branch, and test gates above.
