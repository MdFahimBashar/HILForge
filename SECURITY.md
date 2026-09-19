# Security Policy

## Supported versions

HILForge is an early local-development MVP. Security fixes are made only on the
latest revision of the default branch; older revisions are not supported.

## Reporting a vulnerability

Please do not disclose a suspected vulnerability in a public issue. Use the
repository's **Security** tab to submit a private vulnerability report. If
private reporting is unavailable, open a public issue that requests a private
contact channel but contains no vulnerability details.

Include the affected revision, reproduction steps, expected impact, and any
suggested mitigation. Please allow time for triage and a fix before publishing
details.

## Deployment warning

The current MVP has no authentication or transport-layer security and is
intended for a trusted local development environment. Compose publishes only
the API on the loopback interface, but that is not a production security
boundary. Do not expose HILForge to an untrusted network without adding and
reviewing appropriate authentication, authorization, TLS, secret management,
and network controls.

Credentials shown in `.env.example` are disposable local defaults, not secrets
and not suitable for a shared or production environment.
