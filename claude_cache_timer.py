#!/usr/bin/env python3
"""Show when each Claude agent's prompt cache expires, in Herdr's agents panel.

Claude Code caches the start of each request's prompt for 5 minutes or an
hour, and every request that uses the cache starts that time again. So a
conversation's cache expires one such time after its last request; until
then, carrying on with it is cheaper and faster. Claude's own file for the
conversation records each response's time and which cache time it wrote.

While an agent works it keeps sending requests, so its time stands still
only once it stops: it finishes, or asks you something. Herdr runs this
script when an agent's status changes, and once at startup. Each run looks
at every agent. A working one loses its tokens; an idle or blocked Claude
agent gets

- `$cache`: `cache 14:52`, when its cache expires,
- `$cache_until`: the same time in seconds since the epoch, which
  Herdrsson's `format = "left"` shows as `42m left`, counting down, and
- `$cache_span`: the time of its last request and that time, `FROM/UNTIL`,
  which Herdrsson's `format = "bar"` shows as `▰▰▰▰▱▱`, the share of the
  cache time still left.

`$cache` is reported to expire with the cache. `$cache_until` and
`$cache_span` stay, so the agents panel can show that the cache has expired:
the bar is empty then, `▱▱▱▱▱▱`, which a rule can strike through. Herdr's
token lifetimes stop while the computer sleeps, so after a sleep `$cache`
can outlast the cache until the next run clears it; the bar goes by the
clock. Agents other than Claude get no tokens.

Herdr starts no run when Claude switches conversation without a status
change (`/clear`, `/resume`), so the tokens keep showing the previous
conversation until the agent next works.

Nothing is kept between runs: each one works the times out again from
Claude's files, so a missed event is corrected by the next run, and a
server restart, which drops Herdr's tokens, loses nothing once the startup
run has been. While one run waits for its turn, further events' runs end
at once (see turn).

Usage:
  claude_cache_timer.py   bring every agent's tokens up to date
"""
import fcntl
import glob
import hashlib
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime

PLUGIN_ID = os.environ.get("HERDR_PLUGIN_ID", "bagonyi.claude-cache-timer")
SOURCE = f"plugin:{PLUGIN_ID}"
LABEL_TOKEN = "cache"
TIME_TOKEN = "cache_until"
SPAN_TOKEN = "cache_span"
TOKENS = (LABEL_TOKEN, TIME_TOKEN, SPAN_TOKEN)
STATE_DIR = os.environ.get("HERDR_PLUGIN_STATE_DIR", ".")
SESSION = os.environ.get("HERDR_SOCKET_PATH", "")
# Claude Code keeps each conversation in projects/<folder>/<session id>.jsonl.
CLAUDE_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")

CACHE_5M = 300
CACHE_1H = 3600
# Herdr may see an agent stop around when Claude writes its last response
# to the file, so a run first waits until the files of the agents that
# aren't working have been still this long, counting from the run's start,
# but no longer than SETTLE_MAX_SECONDS.
SETTLE_SECONDS = 1.0
SETTLE_MAX_SECONDS = 3.0
# How far back from a file's end to look for a cache write.
TAIL_MAX = 8 << 20
# The longest time Herdr keeps a token reported with a lifetime.
TTL_MAX_MS = 86_400_000
# How long a Herdr CLI call may take before the run gives up on it.
HERDR_TIMEOUT_SECONDS = 10


def herdr(*args):
    """Run a Herdr CLI command and return its parsed JSON result, if it
    prints one."""
    binary = os.environ.get("HERDR_BIN_PATH", "herdr")
    completed = subprocess.run(
        [binary, *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
        timeout=HERDR_TIMEOUT_SECONDS,
    )
    return json.loads(completed.stdout)["result"] if completed.stdout.strip() else None


@contextmanager
def turn():
    """Wait for this run's turn, as Herdr may start several hooks at once,
    and yield whether to run.

    A run gives up while another one is already waiting for its turn: that
    one starts once the current run ends, and sees all that has happened by
    then. So a burst of events, as when a restarted server finds its agents
    again, leads to at most two runs at a time instead of one per event; the
    others end at once. Every session shares the state directory and a run
    sees only its own session, so the locks are kept per session.
    """
    os.makedirs(STATE_DIR, exist_ok=True)
    session = hashlib.sha256(SESSION.encode()).hexdigest()[:16]
    with open(os.path.join(STATE_DIR, f"waiting-{session}.lock"), "w") as waiting, open(
        os.path.join(STATE_DIR, f"running-{session}.lock"), "w"
    ) as running:
        try:
            fcntl.flock(waiting, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        fcntl.flock(running, fcntl.LOCK_EX)
        # The next run can wait behind this one now.
        fcntl.flock(waiting, fcntl.LOCK_UN)
        yield True


def conversation_file(agent):
    """The file of the agent's Claude conversation, or None.

    Herdr knows a Claude agent's session id, which names the file. A new
    conversation has no file until its first message.
    """
    session = agent.get("agent_session") or {}
    name = os.path.basename(session.get("value") or "")
    if session.get("agent") != "claude" or session.get("kind") != "id" or not name:
        return None
    pattern = os.path.join(glob.escape(CLAUDE_DIR), "projects", "*", glob.escape(name) + ".jsonl")
    paths = glob.glob(pattern)
    return paths[0] if paths else None


def modified(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0


def wait_until_still(paths):
    """Wait until none of the files has changed for SETTLE_SECONDS, counting
    the run's start as a change, or for SETTLE_MAX_SECONDS at most.

    Counting the start makes every run wait at least SETTLE_SECONDS, so a
    last response written just after Herdr saw the agent stop, following a
    quiet spell (as while Claude streams a long answer), is still seen.
    """
    if not paths:
        return
    start = time.time()
    give_up = start + SETTLE_MAX_SECONDS
    while True:
        newest = max(start, *(modified(path) for path in paths))
        wait = min(newest + SETTLE_SECONDS, give_up) - time.time()
        if wait <= 0:
            return
        time.sleep(wait)


def cache_window(path):
    """When the conversation's last request was sent and when its cache
    expires (or expired), in seconds, or None if there's no response to go
    by."""
    try:
        sent, cache_time = last_request(path)
    except OSError:
        return None
    if sent is None:
        return None
    # No cache write in view: assume the shorter time rather than overstate it.
    return sent, sent + (cache_time or CACHE_5M)


def last_request(path):
    """When the conversation's last request was sent, and the cache time of
    its latest cache write, read from the file's end, as the file can be
    many megabytes."""
    with open(path, "rb") as f:
        end = f.seek(0, os.SEEK_END)
        size = 1 << 18
        while True:
            start = max(0, end - size)
            f.seek(start)
            lines = f.read(end - start).splitlines()
            # The first line may start partway through an entry.
            sent, cache_time = scan(lines[1:] if start else lines)
            if (sent is not None and cache_time) or not start or size >= TAIL_MAX:
                return sent, cache_time
            size = min(size * 4, TAIL_MAX)


def scan(lines):
    """Go back through conversation entries for the last request's time and
    the cache time of the latest cache write."""
    last_id = sent = cache_time = None
    for line in reversed(lines):
        entry = response_entry(line)
        if entry is None:
            continue
        message = entry["message"]
        # One response is written as several entries (thinking, text, tool
        # use); the earliest is closest to when its request was sent.
        if last_id is None:
            last_id = message["id"]
        if message["id"] == last_id:
            sent = parse_time(entry.get("timestamp")) or sent
        elif cache_time:
            break
        if cache_time is None:
            cache_time = written_cache_time(message["usage"])
    return sent, cache_time


def response_entry(line):
    """The entry, if it is a response in the conversation itself: not a
    subagent's, and not one Claude Code made up, such as an error."""
    try:
        entry = json.loads(line)
    except ValueError:
        return None
    if not isinstance(entry, dict) or entry.get("type") != "assistant" or entry.get("isSidechain"):
        return None
    message = entry.get("message")
    if (
        not isinstance(message, dict)
        or not isinstance(message.get("usage"), dict)
        or not message.get("id")
        or message.get("model") == "<synthetic>"
    ):
        return None
    return entry


def written_cache_time(usage):
    """The cache time a response's request wrote with, if it wrote any."""
    creation = usage.get("cache_creation")
    if not isinstance(creation, dict):
        return None
    if creation.get("ephemeral_1h_input_tokens"):
        return CACHE_1H
    if creation.get("ephemeral_5m_input_tokens"):
        return CACHE_5M
    return None


def parse_time(stamp):
    if not isinstance(stamp, str):
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def report(agent, window):
    """Bring the agent's tokens up to date, reporting only what changed.

    `$cache_until` and `$cache_span` stay once the cache has expired, so the
    agents panel can show that; `$cache` is reported to expire with the
    cache. An agent without a conversation (or a working one, whose window
    is None) has none of them.
    """
    pane_id, tokens = agent["pane_id"], agent.get("tokens") or {}
    if window is None:
        clear_tokens(pane_id, tokens, TOKENS)
        return
    # Whole seconds, which is all the tokens hold, so the label never
    # outlasts the time it shows.
    until = int(window[1])
    kept = {TIME_TOKEN: str(until), SPAN_TOKEN: f"{int(window[0])}/{until}"}
    if any(tokens.get(name) != value for name, value in kept.items()):
        set_tokens(pane_id, kept)
    now = time.time()
    if until <= now:
        clear_tokens(pane_id, tokens, (LABEL_TOKEN,))
        return
    label = datetime.fromtimestamp(until).strftime("cache %H:%M")
    if tokens.get(LABEL_TOKEN) != label:
        ttl_ms = min(max(1, int((until - now) * 1000)), TTL_MAX_MS)
        set_tokens(pane_id, {LABEL_TOKEN: label}, "--ttl-ms", str(ttl_ms))


def set_tokens(pane_id, values, *options):
    settings = [arg for name, value in values.items() for arg in ("--token", f"{name}={value}")]
    herdr("pane", "report-metadata", pane_id, "--source", SOURCE, *settings, *options)


def clear_tokens(pane_id, tokens, names):
    clear = [arg for name in names if name in tokens for arg in ("--clear-token", name)]
    if clear:
        herdr("pane", "report-metadata", pane_id, "--source", SOURCE, *clear)


def reconcile():
    agents = herdr("agent", "list")["agents"]
    files = {
        agent["pane_id"]: conversation_file(agent)
        for agent in agents
        if agent["agent_status"] != "working"
    }
    wait_until_still([path for path in files.values() if path])
    failed = False
    for agent in agents:
        path = files.get(agent["pane_id"])
        try:
            report(agent, cache_window(path) if path else None)
        except subprocess.CalledProcessError as error:
            # The pane may have closed since the list; the others still count.
            print(f"{agent['pane_id']}: {error.stderr.strip() or error}", file=sys.stderr)
            failed = True
        except subprocess.TimeoutExpired as error:
            print(f"{agent['pane_id']}: {error}", file=sys.stderr)
            failed = True
    return failed


if __name__ == "__main__":
    with turn() as my_turn:
        if my_turn and reconcile():
            sys.exit(1)
