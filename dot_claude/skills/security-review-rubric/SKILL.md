---
name: security-review-rubric
description: Canonical security rubric for the security-reviewer and supply-chain-reviewer agents — code-level vulnerabilities (authz, injection, XSS, SSRF, crypto) and build/config risks (dependencies, CI, deploy, secrets). Preloaded by those agents; apply directly for a small interactive security check.
---

# Security Review Rubric

Anchored to the OWASP Top 10 categories. Two halves — each agent applies its own and hands the other's territory to its sibling.

## Application code (security-reviewer)

For each change, trace untrusted input to dangerous sinks and ask what guards the path:

- **Access control:** changed endpoints enforce authz; no privilege taken from client-side state; object references not guessable or unscoped (IDOR).
- **Authentication:** token/session creation, validation, expiry; credential storage and verification; no bypass via new defaults.
- **Injection:** SQL/NoSQL/command construction from input; XSS via `innerHTML`, templates, or attribute sinks; template injection.
- **Cryptographic failures:** hardcoded keys, weak algorithms or modes, plaintext secrets, unsalted or fast-hash comparisons.
- **SSRF:** outbound requests whose URL or host is user-influenced.
- **Insecure design:** a trust boundary the diff crosses without the check a straightforward design would include.

## Build and configuration (supply-chain-reviewer)

- **Components:** added/updated dependencies — advisories, unmaintained packages, install scripts; lockfile consistency.
- **Misconfiguration:** debug modes, permissive CORS, default credentials, verbose errors, exposed ports or tooling in config.
- **Integrity:** CI workflows — untrusted input reaching privileged steps (`pull_request_target`, script steps), unpinned action refs, `curl | sh`, unverified artifacts.
- **Secrets:** credentials in config/env/deploy files (a secret in a file that ships as config belongs here; one in executable source belongs to security-reviewer); secrets echoed into logs or shipped into artifacts.

## Evidence bar

Same as reviewer-contract: a concrete attack path with a specific input. No theoretical hardening, no findings outside the diff.
