# Connecting AI apps

`scipatch connect` does two things for each app:

1. registers SciPatch's **MCP server** (`scipatch serve`), which gives the app the
   operations `find_tools`, `describe_tool`, `run_tool`, and so on;
2. installs SciPatch's **skills** (`SKILL.md` files) where the app reads them: how
   to use SciPatch, how to onboard repositories, and one skill per installed tool.

```bash
scipatch connect                 # asks about each app it finds
scipatch connect claude-code     # or name them
scipatch connect --all           # every app found, without asking
scipatch disconnect cursor       # undo
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

### How SciPatch edits configuration files

- Only the entry named `scipatch` is added, changed, or removed.
- The original file is copied to `<file>.scipatch-backup` the first time.
- Files SciPatch cannot parse (for example JSON with comments) are never modified;
  SciPatch prints what to add by hand instead.
- Skill folders SciPatch writes contain a `.scipatch-managed` marker. Folders without
  it are never changed or deleted, even if they have the same name.

## Claude Desktop and claude.ai skills

Claude Desktop uses the MCP server directly, and that is all it needs. To also
give it SciPatch's skills, export them as zip files and upload them in Claude's
skills settings:

```bash
scipatch skills export ~/Desktop/scipatch-skills --zip
```

## API keys in each app

Some tools need an API key. Keys never go through the chat; when one is missing,
you enter it on a page that SciPatch serves on your own computer:

| Where you work | What happens |
|---|---|
| Claude Code (2.1.281 or later) | It asks whether to open the page in your browser. Enter the key there, and the run continues on its own. |
| Claude Desktop | Claude gives you a link to the page. Enter the key there, then ask Claude to try again. |
| Other MCP apps | They open the page themselves if they support MCP *URL elicitation*; otherwise they show the link, as Claude Desktop does. |
| Agents using the command line (skills) | The agent runs `scipatch secret set NAME`, which opens the page in your browser. |
| You, in a terminal | `scipatch add` asks for the key; later, `scipatch secret set NAME`. Or use the Keys page of `scipatch ui`. |

## Other MCP clients

Any MCP client can use SciPatch. Print the configuration to copy:

```bash
scipatch connect --show
```

```json
{
  "mcpServers": {
    "scipatch": { "command": "/Users/you/.local/bin/scipatch", "args": ["serve"] }
  }
}
```

Use the absolute path: desktop apps don't see your shell's `PATH`.

## Agents without MCP

Agents that can run shell commands can use SciPatch through its command line with
`--json` output. Install the skills so they know how:

```bash
scipatch skills install agents      # ~/.agents/skills (Codex, Gemini CLI, OpenCode, ...)
scipatch skills install ./my-skills # any folder
```

## Remote access (advanced)

`scipatch serve --http` serves MCP over Streamable HTTP at
`http://127.0.0.1:8765/mcp`, for clients that cannot start local processes. It
listens only on your computer by default. Exposing it beyond that (`--host
0.0.0.0`) lets anyone who can reach the port run your tools; put it behind an
authenticated tunnel or proxy if you do.
