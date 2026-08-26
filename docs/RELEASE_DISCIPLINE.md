> **DO NOT EDIT THIS DOC:** This document defines core release discipline rules and instructions to be followed by the agent and must not be modified.

# Release & SemVer Discipline (AgentAnyStack Core)

Workflow rules for closing completed tasks and keeping release records in sync.

## Rules

- **SemVer Bump**: After completing any task on AgentAnyStack core, bump SemVer appropriately (usually patch).
- **Obsidian Releases Log**: Add 3–6 concise bullets to `~/Documents/obsidian_vault/AgentAnyStack/Releases.md` covering:
  - **What** was changed
  - **When** (timestamp in IST)
  - **Why** the change was made
  - **Impact** on behavior, architecture, or stability
- **Examples Log**: When relevant, link to or update the matching section in `~/Documents/obsidian_vault/AgentAnyStack/Examples.md` for detailed walk-throughs or payload samples.
- **User Approval First**: Always propose the exact text for `Releases.md` (and `Examples.md` if applicable) to the user for approval before writing.
- **Immutable Releases (Append-Only)**: Once a release version is written to disk and shipped, it is strictly immutable and non-editable. Never modify, retroactively edit, or rewrite past release entries or version numbers. Any subsequent changes, bug fixes, or enhancements must be shipped under a new, distinct SemVer bump.
- **Group Trivial Work**: Small consecutive fixes or chores may be batched into a single SemVer bump to reduce noise.
- **When Unsure**: Ask the user for clarification on version number, scope, or impact.

