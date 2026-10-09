# Project instructions

Read README.md and CONTRIBUTING.md. Preserve the visual design and home page; follow docs/design-system.md. Do not add a framework, ORM, or build tool without a concrete need. Keep the frontend in frontend/, the API and SQLite code in backend/, collectors in ingest/, and local data in data/.

## Language conventions

Use English for new and renamed source files, directories, modules, functions, classes, variables, constants, and internal identifiers, including CSS classes and DOM IDs. Use English names in tests and update imports, build configuration, documentation links, and callers when renaming code. Comments and docstrings may remain in Brazilian Portuguese. Keep user-facing interface text in Brazilian Portuguese and preserve official names and source quotations.

Treat official API field names and URLs, existing public API contracts, database columns, persisted snapshot keys and filenames, environment variables, and deployed service identities as compatibility boundaries. Do not translate them mechanically or rename local data. Map source fields to English internal identifiers where appropriate; any contract or data migration must be explicit and preserve existing data and clients. Missing data does not mean zero.

## Changes and verification

Keep changes focused, tests proportional, and commits clear. Always run `git diff --check` before finishing. For small, localized changes, run only the checks and tests for the affected scope, including directly affected callers and contracts. Documentation-only changes need review and a whitespace check; do not run the full suite for each documentation or text adjustment.

Run `make check` for cross-cutting changes, before integration or deployment, or when there is uncertainty about effects outside the tested scope. Broaden testing when failures, new changes, or unresolved concerns justify it. Once appropriate checks pass, do not repeat or expand them without a new reason. Report what was checked and any material verification limits.

Never commit databases, downloads, caches, backups, or secrets. Do not include agent session links (such as `Claude-Session:`) in commit or PR messages. Do not change stated coverage without evidence from the sources.

Delegate independent work when it saves time: use luna_max_worker with fork_turns none and explicit responsibilities and paths. Do not clone the root agent. Workers must not revert other contributors' changes or commit without coordination.

The user's current instruction takes precedence. Complete authorized local changes without unnecessary confirmation; preserve existing data and work.
