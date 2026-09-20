"""MCP server of the exoskeleton hand: anything that speaks MCP (Claude, another agent, a script)
can look at the hand, move it, run its skills and teach it new ones.

It is a thin client of the web console's backend (application/backend, http://localhost:8000):
no ROS here, so it runs on any machine that reaches the backend. Every movement still goes
through /hand/command and the HAL below it - its speed limit and its contact stop hold for an
agent as they do for a slider.

    python server.py                       stdio: for Claude Code / Claude Desktop (README has the config)
    python server.py --http --port 8765    streamable HTTP on http://127.0.0.1:8765/mcp

A SKILL is a named hard-coded path: a list of (pose, seconds), saved as a Python file in the
repo's movements/ folder and shown in the console's Movement dropdown as well. For now teaching
IS writing such a path; skills learnt from demonstrations can become a second kind later.
"""

import argparse
import os
import time

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

BACKEND_URL = os.environ.get("HTN_BACKEND_URL", "http://localhost:8000").rstrip("/")
FINGERS = ["thumb", "index", "middle", "ring", "pinky"]
ARRIVED = 0.04  # as the backend's movement player: measured within this of the pose = the hand is there

INSTRUCTIONS = """\
You control a wearable exoskeleton hand with 5 fingers, each with ONE degree of freedom (curl).
A pose is 5 numbers in the order thumb, index, middle, ring, pinky: 0 = fully open, 1 = fully closed.
A person's hand may be inside it: prefer small, slow movements when trying something out.

The hand takes ~0.3 s for a full open-to-close travel (its controller limits the speed; the real
motors can be slower), so a step of a path needs at least about 0.1 s + 0.25 s per unit of travel
before the next pose makes sense - give quick repeated strokes a short travel, so each one arrives.

Skills are named hard-coded paths. To do what the user wants: look at list_skills first; if a
skill fits, run_skill. If not, design a path (try poses with move_hand, check get_hand_state),
save it with teach_skill, then run_skill it. Tell the user what you taught and how long it takes.
"""

mcp = MCPServer("htn-hand", instructions=INSTRUCTIONS)


def backend(method: str, path: str, body: dict | None = None):
    """One call of the console backend. Its error text (a 4xx `detail`) is the tool's error: a
    ToolError, because the text of any other exception never reaches the model."""
    try:
        response = httpx.request(method, f"{BACKEND_URL}{path}", json=body, timeout=10.0)
    except httpx.HTTPError as error:
        raise ToolError(f"the console backend at {BACKEND_URL} does not answer ({error}): start application/dev.sh") from error
    if response.status_code >= 400:
        detail = response.json().get("detail", response.text) if response.headers.get("content-type", "").startswith("application/json") else response.text
        raise ToolError(str(detail))
    return response.json()


def by_finger(values) -> dict | None:
    return None if values is None else {finger: round(float(v), 3) for finger, v in zip(FINGERS, values)}


@mcp.tool()
def get_hand_state() -> dict:
    """Where the hand is now: the measured curl of each finger (0 = open .. 1 = closed), the last
    command, whether ROS is connected, whether the torque is off (passive: commands are ignored
    then), the skill that is running, and the objects the wrist camera sees (label and position
    in metres relative to the camera: x forward, y left, z up)."""
    state = backend("GET", "/api/state")
    return {
        "ros_connected": state["ros_connected"],
        "measured": by_finger(state["state"]),
        "commanded": by_finger(state["command"]),
        "passive": state["passive"],
        "running_skill": state.get("movement"),
        "episode_session": state.get("session"),
        "objects": [{"label": o["label"], "xyz_m": o["xyz"], "seen_s_ago": o["age"]} for o in state.get("objects", [])],
    }


@mcp.tool()
def move_hand(thumb: float, index: float, middle: float, ring: float, pinky: float, wait_s: float = 3.0) -> dict:
    """Send ONE pose (each finger 0 = open .. 1 = closed) and return when the hand has ARRIVED there
    (every finger measured within 0.04 of it), or after wait_s seconds (0 .. 10) at the latest. It
    reports what the hand measured and `arrived`. Use it to try a pose before it goes into a skill.
    A finger that does not arrive has met something (the contact stop holds it there with a low
    force). Never send the next pose of a sequence before the last one has arrived."""
    pose = [thumb, index, middle, ring, pinky]
    sent = backend("POST", "/api/command", {"values": pose})["sent"]
    deadline = time.monotonic() + min(10.0, max(0.0, wait_s))
    while True:
        measured = backend("GET", "/api/state")["state"]
        there = all(abs(m - s) <= ARRIVED for m, s in zip(measured, sent))
        if there or time.monotonic() >= deadline:
            return {"sent": by_finger(sent), "measured": by_finger(measured), "arrived": there}
        time.sleep(0.05)


@mcp.tool()
def list_skills() -> list[dict]:
    """The skills the hand has: name (for run_skill), title, description, how long it takes, and
    `error` for a skill file that is broken."""
    return backend("GET", "/api/movements")


@mcp.tool()
def read_skill(name: str) -> dict:
    """One skill with its full path: steps of {pose, seconds}. `taught` false = a person wrote the
    file by hand: it can be run and read, not replaced - teach a changed copy under a new name."""
    return backend("GET", f"/api/movements/{name}")


@mcp.tool()
def teach_skill(name: str, title: str, description: str, steps: list[dict]) -> dict:
    """Teach the hand a new skill, or replace one that was taught before: a hard-coded path.

    name: lower case letters, digits and _ (e.g. "peace_sign"); title and description are for people.
    steps: a list of {"pose": [thumb, index, middle, ring, pinky], "seconds": s}. Each pose
    (0 = open .. 1 = closed) is sent to the hand, then nothing happens for `seconds` (0 < s <= 30)
    - and until the hand has arrived at the pose: the next pose is never sent before that, so
    `seconds` is the SHORTEST a step takes (the hold), not a promise of the tempo. At most 2000 steps.
    Start and end a path in a relaxed pose (e.g. all 0.15) unless the user wants otherwise.
    The skill is saved as movements/<name>.py in the project and is in the console's dropdown."""
    return backend("PUT", f"/api/movements/{name}", {"title": title, "description": description, "steps": steps})


@mcp.tool()
def run_skill(name: str, wait: bool = False) -> dict:
    """Play a skill on the hand. It returns at once with the number of steps; with wait = true it
    returns when the skill has finished (or after 120 s). Refused while another skill or a replay
    of a recording runs: stop_skill first."""
    started = backend("POST", "/api/movements/play", {"name": name})
    deadline = time.monotonic() + 120.0
    while wait and time.monotonic() < deadline and backend("GET", "/api/state").get("movement"):
        time.sleep(0.25)
    return {"started": started, "finished": wait and not backend("GET", "/api/state").get("movement")}


@mcp.tool()
def stop_skill() -> dict:
    """Stop the skill that is running. The hand stays in the pose it is in."""
    backend("POST", "/api/movements/stop")
    return {"stopped": True}


@mcp.tool()
def forget_skill(name: str) -> dict:
    """Delete a skill that was taught through teach_skill. A skill a person wrote by hand is refused."""
    backend("DELETE", f"/api/movements/{name}")
    return {"forgotten": name}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--http", action="store_true", help="streamable HTTP instead of stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--public-host", help="the name an HTTPS proxy in front serves this under (e.g. "
                        "tailscale serve: <machine>.<tailnet>.ts.net); on localhost the SDK refuses any other Host")
    args = parser.parse_args()
    if args.http:
        security = None  # the SDK's default: on localhost, only localhost as Host (DNS rebinding protection)
        if args.public_host:
            names = ["127.0.0.1", "localhost", args.public_host]
            security = TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=[entry for name in names for entry in (name, name + ":*")],
                allowed_origins=[f"{scheme}://{entry}" for scheme in ("http", "https")
                                 for name in names for entry in (name, name + ":*")])
        mcp.run("streamable-http", host=args.host, port=args.port, transport_security=security)
    else:
        mcp.run("stdio")
