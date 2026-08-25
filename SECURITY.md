# Security policy

## Supported version

Security fixes target the latest v1 release line. Older commits and untagged development snapshots are not supported releases.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for this repository when available. Do not include credentials, private user data, or exploit material in a public issue. If private reporting is unavailable, open a minimal public issue asking the maintainer for a private contact channel without disclosing the vulnerability.

## Deployment boundary

Agent Studio v1 is a single-user, loopback-only development workbench. It has no authentication, authorization, RBAC, or multi-tenancy and must not be exposed as a public/shared service. See [docs/SECURITY_DESIGN.md](docs/SECURITY_DESIGN.md) for the threat model, implemented controls, tests, and limitations.
