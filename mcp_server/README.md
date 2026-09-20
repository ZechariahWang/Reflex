# mcp_server

An MCP server for the hand: anything that speaks MCP (Claude Code, Claude Desktop, another agent,
your own script) can read the hand's state, move it, run its skills and teach it new ones.

It is a thin client of the web console's backend - no ROS here - so it runs on any machine that
reaches the backend (`HTN_BACKEND_URL`, default `http://localhost:8000`). Every movement goes
through `/hand/command` and the HAL below it: the speed limit and the contact stop hold for an
agent as they do for a slider.

A **skill** is a named hard-coded path: a list of `(pose, seconds)`, saved as
`movements/<name>.py` and also shown in the console's Movement dropdown. For now, teaching IS
writing such a path; the agent designs it from what the user asks for. A skill somebody wrote by
hand (`movements/hot_cross_buns.py`) can be run and read through MCP, never replaced or deleted.

| Tool | |
|---|---|
| `get_hand_state` | measured and commanded curl per finger, passive mode, the running skill, the objects the camera sees |
| `move_hand` | one pose (thumb .. pinky, 0 = open .. 1 = closed), then what the hand measured after `wait_s` |
| `list_skills` / `read_skill` | what the hand can do, and the full path of one skill |
| `teach_skill` | save a new path (or replace a taught one) |
| `run_skill` / `stop_skill` | play a skill (`wait: true` = return when it is done) |
| `forget_skill` | delete a taught skill |

## Setup

```bash
cd mcp_server
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests        # needs pytest: .venv/bin/pip install pytest
```

The console backend must run (`application/dev.sh`; `MOCK=1 application/dev.sh` to try it with
no robot).

## Connect

Claude Code, from the repo root:

```bash
claude mcp add htn-hand -- "$PWD/mcp_server/.venv/bin/python" "$PWD/mcp_server/server.py"
```

Claude Desktop (`claude_desktop_config.json`), or any client with the same format:

```json
{
  "mcpServers": {
    "htn-hand": {
      "command": "/home/zech/htn-2026/mcp_server/.venv/bin/python",
      "args": ["/home/zech/htn-2026/mcp_server/server.py"],
      "env": {"HTN_BACKEND_URL": "http://localhost:8000"}
    }
  }
}
```

A client on another machine, or one that wants HTTP: `python server.py --http --port 8765`
serves streamable HTTP on `http://127.0.0.1:8765/mcp` (`--host 0.0.0.0` to open it to the
network - there is no authentication, so only on a network you trust: it moves a hand that
somebody may be wearing).

Then ask for things: "what can the hand do?", "make a peace sign", "teach it to count to
three on its fingers and show me".
