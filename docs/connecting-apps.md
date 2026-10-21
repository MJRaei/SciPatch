# Connecting AI apps

`motel connect` does two things for each app:

1. registers Motel's **MCP server** (`motel serve`), which gives the app the
   operations `find_tools`, `describe_tool`, `run_tool`, and so on;
2. installs Motel's **skills** (`SKILL.md` files) where the app reads them: how
   to use Motel, how to onboard repositories, and one skill per installed tool.

```bash
motel connect                 # asks about each app it finds
motel connect claude-code     # or name them
motel connect --all           # every app found, without asking
motel disconnect cursor       # undo
```

Skills are kept up to date automatically when you add or remove tools.

## Supported apps

| App | Key | MCP configuration | Skills folder |
|---|---|---|---|
| Claude Desktop | `claude-desktop` | `claude_desktop_config.json` | upload zips (see below) |
| Claude Code | `claude-code` | `claude mcp add --scope user`, or `~/.claude.json` | `~/.claude/skills` |
| Codex | `codex` | `~/.codex/config.toml` | `~/.agents/skills` |
| Cursor | `cursor` | `~/.cursor/mcp.json` | `~/.cursor/skills` |
| Gemini CLI | `gemini` | `~/.gemini/settings.json` | `~/.gemini/skills` |

Claude Desktop's configuration file is in
`~/Library/Application Support/Claude/` on macOS, `%APPDATA%\Claude\` on Windows,
and `~/.config/Claude/` on Linux.

**After connecting, restart the app**: quit Claude Desktop completely, or start
a new session in the others.

### How Motel edits configuration files

- Only the entry named `motel` is added, changed, or removed.
- The original file is copied to `<file>.motel-backup` the first time.
- Files Motel cannot parse (for example JSON with comments) are never modified;
  Motel prints what to add by hand instead.
- Skill folders Motel writes contain a `.motel-managed` marker. Folders without
  it are never changed or deleted, even if they have the same name.

## Claude Desktop and claude.ai skills

Claude Desktop uses the MCP server directly, and that is all it needs. To also
give it Motel's skills, export them as zip files and upload them in Claude's
skills settings:

```bash
motel skills export ~/Desktop/motel-skills --zip
```

## API keys in each app

Some tools need an API key. Keys never go through the chat; when one is missing,
you enter it on a page that Motel serves on your own computer:

| Where you work | What happens |
|---|---|
| Claude Code (2.1.281 or later) | It asks whether to open the page in your browser. Enter the key there, and the run continues on its own. |
| Claude Desktop | Claude gives you a link to the page. Enter the key there, then ask Claude to try again. |
| Other MCP apps | They open the page themselves if they support MCP *URL elicitation*; otherwise they show the link, as Claude Desktop does. |
| Agents using the command line (skills) | The agent runs `motel secret set NAME`, which opens the page in your browser. |
| You, in a terminal | `motel add` asks for the key; later, `motel secret set NAME`. Or use the Keys page of `motel ui`. |

## Other MCP clients

Any MCP client can use Motel. Print the configuration to copy:

```bash
motel connect --show
```

```json
{
  "mcpServers": {
    "motel": { "command": "/Users/you/.local/bin/motel", "args": ["serve"] }
  }
}
```

Use the absolute path: desktop apps don't see your shell's `PATH`.

## Agents without MCP

Agents that can run shell commands can use Motel through its command line with
`--json` output. Install the skills so they know how:

```bash
motel skills install agents      # ~/.agents/skills (Codex, Gemini CLI, OpenCode, ...)
motel skills install ./my-skills # any folder
```

## Remote access (advanced)

`motel serve --http` serves MCP over Streamable HTTP at
`http://127.0.0.1:8765/mcp`, for clients that cannot start local processes. It
listens only on your computer by default. Exposing it beyond that (`--host
0.0.0.0`) lets anyone who can reach the port run your tools; put it behind an
authenticated tunnel or proxy if you do.
