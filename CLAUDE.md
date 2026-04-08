# CLAUDE.md

This file provides guidance for AI assistants (Claude Code and similar tools) working in this repository.

## Repository Overview

- **Remote**: `mk0323/-`
- **Status**: Freshly initialized — no source code committed yet.
- **Current dev branch**: `claude/add-claude-documentation-BlH34`

This CLAUDE.md should be updated as the project grows to reflect the actual stack, conventions, and workflows in use.

---

## Git Workflow

### Branch Naming

Feature branches follow the pattern: `claude/<short-description>-<random-suffix>`

Example: `claude/add-claude-documentation-BlH34`

### Standard Workflow

```bash
# Create and switch to a feature branch
git checkout -b claude/<feature-name>-<suffix>

# Stage and commit
git add <specific-files>
git commit -m "concise, imperative commit message"

# Push to remote
git push -u origin <branch-name>
```

### Commit Message Guidelines

- Use the imperative mood: "Add feature" not "Added feature"
- Keep the subject line under 72 characters
- Reference issues or context in the body when relevant
- Never skip pre-commit hooks (`--no-verify` is not allowed unless explicitly authorized)

### Protected Branches

- Never force-push to `main` or `master`
- Confirm with the user before any destructive git operations (`reset --hard`, `branch -D`, `push --force`)

---

## Development Setup

> This section will be updated once the project stack is established.

Typical setup steps to document here:
- Language/runtime version requirements
- Dependency installation command (e.g., `npm install`, `pip install -e .`, `cargo build`)
- Environment variable setup (e.g., copy `.env.example` to `.env`)
- Database migration or seed commands

---

## Running the Project

> To be filled in once the project is bootstrapped.

Typical commands to document:
- `<start command>` — starts the development server
- `<build command>` — produces a production build
- `<lint command>` — runs linters/formatters

---

## Testing

> To be filled in once a test framework is chosen.

Document here:
- How to run the full test suite
- How to run a single test file or test case
- Coverage thresholds (if enforced)
- Where tests live relative to source code

---

## Code Conventions

> To be updated as conventions emerge from the codebase.

Key things to record here once established:
- Formatting tool and config (Prettier, Black, rustfmt, etc.)
- Linting tool and config (ESLint, Ruff, Clippy, etc.)
- Import ordering rules
- Naming conventions (files, functions, variables, types)
- Whether the project uses tabs or spaces, and at what width

---

## Project Structure

> To be filled in once source files exist.

A typical layout to document:

```
/
├── src/            # Main application source
├── tests/          # Test files
├── docs/           # Documentation
├── scripts/        # Dev/ops helper scripts
└── CLAUDE.md       # This file
```

---

## AI Assistant Guidelines

When working in this repository, AI assistants should:

1. **Read before editing** — always read a file before modifying it.
2. **Stay on the designated branch** — develop on the branch specified at the start of the session; never push to `main`/`master` without explicit permission.
3. **Minimal scope** — only change what the task requires; do not refactor surrounding code, add docstrings, or introduce speculative abstractions.
4. **No security vulnerabilities** — avoid command injection, XSS, SQL injection, and other OWASP Top 10 issues.
5. **Confirm destructive actions** — before deleting files/branches, force-pushing, or dropping data, check with the user.
6. **Commit incrementally** — small, focused commits with clear messages are preferred over large monolithic ones.
7. **Update this file** — when significant new structure, conventions, or workflows are established, update the relevant sections of this CLAUDE.md.

---

## Updating This File

As the project evolves, keep CLAUDE.md current by updating:
- **Repository Overview** — once the project purpose is clear
- **Development Setup** — when a stack/language is chosen
- **Running the Project** — when scripts/commands are defined
- **Testing** — when a test framework is added
- **Code Conventions** — when linting/formatting is configured
- **Project Structure** — once directories and modules are created
