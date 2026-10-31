# Security policy

## Supported code

Please reproduce security issues against the latest code on the repository's
default branch. Older revisions do not have guaranteed security backports.
Reports are handled on a best-effort basis, without a guaranteed response time.

## Reporting a vulnerability

Do not post vulnerability details, credentials or exploit instructions in
public issues or pull requests.

If GitHub private vulnerability reporting is enabled, report privately through
this repository's Security page. Otherwise, open an issue titled
`Security contact request`, asking for a private reporting channel
without describing the vulnerability. Share the report only after a private
channel has been established.

Include in the private report:

- Affected commit or version, Python version and operating system.
- Relevant Provider, model and configuration, with secrets removed.
- Reproduction steps or a minimal proof of concept using synthetic data.
- Expected behavior, observed behavior and potential impact.

Coordinate public disclosure with the maintainer while the issue is assessed
and a fix is prepared. Never attach live API keys, account tokens or unredacted
session logs.

## Security boundaries

- Shell commands and local MCP servers run with your operating system account's
  access, without a sandbox. Tool confirmations and dangerous-command detection
  do not provide process isolation. `PA_ENABLE_SHELL=0` disables the shell Tool;
  it does not disable MCP servers.
- `auto` mode skips routine Tool confirmations. Use it only where you accept
  the resulting file, command and network access.
- Prompts, selected file content and Tool results can be sent to the selected
  model Provider. Avoid providing secrets or data you cannot share with it.
- Conversations, Tool output, recovery data and optional detailed audit data
  are stored locally under `~/.personal_agent/`. Key redaction does not
  guarantee removal of arbitrary secrets; logs are not automatically pruned.

See the [README](README.md#costs-and-local-data) and
[user guide](docs/USER_GUIDE.md) for operational details.
