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
| `check_repo` | One repo: the verdict, why, the key numbers, the report's date and link. A repo with no report takes about 20 seconds. A report over 30 days old is checked again, and its old verdict comes back with its date while that runs. |
| `compare_repos` | Up to 30 repos, best first. Holt starts a few new checks per call; the chat calls again for the rest. |
| `starter_issues` | Open issues in a repo that suit a newcomer, free ones first. Some may already be taken; each one says who is on it. |

The verdict is Holt's, from the same rules as the website; the chat
only explains it. Try:

- "Here are some repos I'm looking at: … Which should I contribute to?"
- "Is pallets/flask worth my time as a first-time contributor?"
- "Find me a starter issue in the best of those."

## Limits

Reports Holt already has are unlimited. New checks from all chats share
an hourly budget, with a smaller limit per address inside it; chats that
reach Holt from the same provider address share that limit too. When
either is used up, the answer says Holt is busy, keeps any older verdict
with its date, and links to the report page. That page may show the same
older verdict.

The details of the endpoint are in [API.md](../API.md), "MCP".
