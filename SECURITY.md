# Security Policy

Mneme Memory MCP welcomes reports that help protect users and their local
memory data. Please report suspected vulnerabilities privately so they can be
investigated before technical details are published.

## Supported versions

| Version | Security updates |
| --- | --- |
| Latest revision on `main` | Supported |
| Earlier commits and development snapshots | Not supported |

Mneme is pre-1.0 and does not yet publish versioned releases. Security fixes
land on `main`. Please confirm that a report applies to the current revision
before submitting it.

## Report a vulnerability

Use [GitHub Private Vulnerability Reporting](https://github.com/jollyzachary/mneme-memory-mcp/security/advisories/new)
to submit a confidential report. Do not disclose vulnerability details in a
public issue, discussion, or pull request.

A useful report includes:

- the affected commit and operating environment;
- a clear description of the issue and its potential impact;
- minimal reproduction steps using synthetic data;
- supporting logs or screenshots with private information removed;
- a suggested mitigation, if one is known.

Do not submit credentials, real memory stores, conversation transcripts,
database dumps, or identifying local paths. Redact private information from all
diagnostic material.

## Response and disclosure

Reports should receive an acknowledgment within five business days. The next
steps are to reproduce the issue, assess its impact, and determine a remediation
plan. Fix and disclosure timing will depend on the scope and complexity of the
issue.

Please allow a reasonable remediation period before public disclosure. When a
report is validated, disclosure and reporter credit will be coordinated through
the private advisory unless the reporter prefers to remain anonymous.

## Security boundary

Mneme's default server uses local stdio transport and is designed for one user
running trusted local clients. It is not an internet-facing authentication
service or a multi-tenant isolation boundary.

Reports are most useful when they demonstrate that an untrusted input can cross
this boundary, such as unauthorized access to memory, secret exposure, durable
memory poisoning, arbitrary command execution, or installer behavior that
changes unrelated user configuration.

Conversation capture and local agent delegation are optional features that
expand the security boundary when enabled. A connected AI client may send
retrieved context to its configured model provider; Mneme does not control that
provider relationship.

## Good-faith research

Conduct research only on systems and data you own or are authorized to test.
Use synthetic data and avoid privacy violations, service disruption, data
destruction, social engineering, and testing against third-party services.
Stop testing and report the issue if you encounter real user data.

The project will not pursue legal action against researchers who follow this
policy, act in good faith, and make a reasonable effort to avoid harm. This safe
harbor applies only to Mneme Memory MCP and does not authorize testing of third
parties.
