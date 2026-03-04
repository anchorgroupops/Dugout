# Project Constitution: Softball

## Data Schemas

*To be defined after Link phase.*

## Behavioral Rules

1. **Deterministic Logic**: Favor Python scripts in `tools/` over probabilistic LLM actions.
2. **Self-Healing**: Tools must handle common errors and log issues to `.tmp/`.
3. **Layer Separation**: Architecture (SOPs) must be updated before code changes.

## Architectural Invariants

- Root: `h:/Repos/Personal/Softball`
- Memory: `project-memory/softball/`
- Tools: `tools/`
- SOPs: `architecture/`
