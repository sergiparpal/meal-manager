# Security Policy

## Reporting a vulnerability

Please report security issues privately through
[GitHub Security Advisories](https://github.com/sergiparpal/meal-manager/security/advisories/new)
rather than opening a public issue.

Expect an initial response within 7 days. If a report is confirmed, the fix and the advisory
are published together.

## Supported versions

Only the latest release on `main` receives security fixes.

## Scope

This repository is a Hermes plugin that runs locally on the user's machine. It uses **only the
Python standard library** — it declares no third-party dependencies, so it has no package
supply chain to speak of. It exposes no network service and holds no credentials.

The parts most worth scrutiny are therefore:

- **Local state handling** — the plugin reads and writes the user's recipe, inventory, and
  cooking-history files.
- **Input parsing** — the conversational interface parses user-supplied text into commands.

Out of scope: the nutritional accuracy or suitability of any suggested meal plan, and any
behaviour of the host agent itself.
