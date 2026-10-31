# 0034 — MCP Resources

## Goal

Let the agent use context exposed by a user-configured MCP server during a routed task.

## Scope and settled decisions

- Connect to one opt-in local MCP server over stdio, launched from a command and arguments configured by the user. The model cannot choose or change the process command. With no server configured, MCP capabilities are unavailable.
- Let the agent list Resources and Resource Templates and read a Resource on demand during a routed task. The user does not have to select each Resource manually. Expose only these read operations to the model; bound list and read results before they enter the Conversation.
- In `plan` and `build`, each MCP operation requires Tool Confirmation before starting the server or making the request. The prompt identifies the configured server and operation, including the Resource URI for a read. In `auto`, these operations run without a prompt after validation. A rejected operation neither starts the server nor sends the request.
- MCP content is untrusted external input. Keep the existing Tool result display and Call Log behavior. A configured local server runs as a process under the user's account, with its own access to the host; Workspace Root restrictions on built-in file Tools do not confine that process. Make this clear in user-facing configuration documentation.
- Verify the three operations, mode behavior, rejection before launch, disabled state, bounds, failure reporting, and process cleanup with offline tests.

## Out of scope

MCP Tools, including read-only Tools; remote HTTP servers, multiple servers, plugin installation, OAuth, and automatic discovery of unconfigured servers. No model-supplied server command or MCP write/action method.

## Open questions

None. The planner owns the exact configuration variable or file, Tool names and schemas, connection lifecycle, supported content types, and bounded defaults. The user authorized local SDD commits for feature 0034; do not push.
