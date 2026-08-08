# Contributing to Touchline

Read this file before opening a PR. Lint, typecheck, and test CI checks must be green.

## Branches and pull requests

- Create feature branches from `main` using `feature/<short-description>`.
- Keep each pull request focused on one feature.
- Rebase onto `main` before opening a pull request.
- Delete feature branches after merge.

## Commits

Use conventional commits in the form `<type>(<scope>): <description>`.

Allowed types are `feat`, `fix`, `docs`, `chore`, and `refactor`. Use `ledger`, `canon`,
`integrity`, or `ci` as the scope when applicable; omit the scope when none fits.

## Product specification

Implementation must follow the
[Touchline rib specification](https://github.com/ed-insights-ai/ed-insights-platform/blob/main/docs/specs/touchline-rib.md).
