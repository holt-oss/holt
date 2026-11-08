# Holt in Claude and ChatGPT

Holt is a remote MCP server. Add it to Claude or ChatGPT as a connector
and the chat can check repositories for you: "which of these should I
contribute to?" over a list of 30 repos gets a ranked answer, each with
Holt's verdict and a link to its report.

Server URL: **`https://githolt.com/mcp`**

No account or key. It reads public data only and never writes to GitHub.

## Add it to Claude

1. Settings → Connectors → **Add custom connector**.
2. Name: `Holt`. URL: `https://githolt.com/mcp`. Leave the advanced
   settings empty.
3. In a chat, turn Holt on from the tools menu.

On a Team or Enterprise plan an owner adds the connector for the
organisation first.

## Add it to ChatGPT

1. Settings → Apps & Connectors → Advanced settings → turn on
   **Developer mode**.
2. Back in Apps & Connectors, **Create**: name `Holt`, MCP server URL
   `https://githolt.com/mcp`, authentication **No authentication**.
3. In a chat, pick Holt from the tools menu (developer mode).

## What it can do

| Tool | What it answers |
|---|---|
| `check_repo` | One repo: the verdict, why, the key numbers and the report link. A repo Holt hasn't checked lately takes about 20 seconds. |
| `compare_repos` | Up to 30 repos, best first. Holt starts a few new checks per call; the chat calls again for the rest. |
| `starter_issues` | Open issues in a repo that suit a newcomer and nobody has taken. |

The verdict is Holt's, from the same rules as the website; the chat
only explains it. Try:

- "Here are some repos I'm looking at: … Which should I contribute to?"
- "Is pallets/flask worth my time as a first-time contributor?"
- "Find me a starter issue in the best of those."

## Limits

Reports Holt already has are unlimited. New checks from all chats share
an hourly budget; when it's used up the answer says Holt is busy and
links to the report page, where you can check the repo yourself.

The details of the endpoint are in [API.md](../API.md), "MCP".
