# .claude/ Directory Convention

**Purpose:** AI workspace for session continuity and working files.

Files here are **point-in-time session artifacts**, not project documentation.
They record what was true when they were written and are deliberately not
maintained afterwards, so:

- File paths, module names and line numbers in them may no longer resolve.
- Findings may have been fixed, superseded, or reversed since.
- Nothing here is current guidance. For that, read `README.md`, `docs/`, and
  the canonical contracts in `LegiVellum/docs/canonical/`.

They can be lost without breaking the project. They are kept because they are
useful for AI session handoffs and as a record of how the code got here.

## What goes here

- Session notes and progress tracking
- Code reviews, audits and punchlists from a given session
- Temporary working files and scratch notes
- Permission settings (`settings.local.json`)

## What does NOT go here

- Production code (`src/`, `tests/`)
- Project documentation (`docs/`, `README.md`)
- Specifications
- Build/deploy configs

This mirrors the convention already documented in `AsyncGate/.claude/README.md`.
