# Claude Cache Timer for Herdr

Shows in Herdr's agents panel when each Claude agent's prompt cache expires:

```
 agents
 ● Code/herdr · main
 ○ Code/changes · ui · ▰▰▰▰▰▰
 ○ Web/site · docs · ▰▰▰▰▱▱
 ○ Code/herdr · setup · ▰▱▱▱▱▱
 ○ Web/blog · draft
```

Claude Code caches the start of each request's prompt for 5 minutes or an
hour, depending on your setup, and every request that uses the cache starts
that time again. Until it runs out, carrying on with a conversation is
cheaper and faster, as Claude reads most of it from the cache.

![Herdrsson's agents panel with a bar under each idle Claude agent: full 3 and 7 minutes after its last request, two segments gone after 24, one orange segment left after 52, and none on the agents whose cache has expired](screenshot.png)

The bars come from this plugin, drawn by [Herdrsson, my fork of Herdr](https://github.com/bagonyi/herdrsson/blob/herdrsson/FORK.md) (see
[Showing the time](#showing-the-time)). The agents panel's order and times come from
[Agent Recency](https://github.com/bagonyi/herdr-agent-recency) and the tab markers from [Tab Status](https://github.com/bagonyi/herdr-tab-status).

## How it works

A conversation's cache expires one cache time after its last request. Claude
Code's file for the conversation, under `~/.claude/projects/` (or
`$CLAUDE_CONFIG_DIR`), records each response's time and which cache time it
wrote, so the plugin reads the time from there. Herdr knows which file
belongs to which agent.

While an agent works it keeps sending requests, so its time stands still only
once it stops: it finishes, or asks you something. Herdr runs the plugin when
an agent's status changes and once at startup. There is no background
process, and while one run waits for its turn, further events' runs end at once. Each
run brings every agent up to date, so a missed event is corrected on the next
run. It reports an idle or blocked agent's time to Herdr as three pane tokens:

- `$cache`: `cache 14:52`, the time its cache expires.
- `$cache_until`: the same time in seconds since the epoch.
- `$cache_span`: the time of its last request and the time its cache
  expires, in seconds since the epoch, as `FROM/UNTIL`.

They are reported to expire with the cache, so an agent whose cache has
expired shows none of them. A working agent has none, as its cache keeps
being refreshed. The plugin keeps nothing of its own: after a server
restart, which clears Herdr's tokens, the startup run reads the times again.

## Showing the time

Add `$cache` to the agent rows in Herdr's `config.toml`, e.g.:

```toml
[ui.sidebar.agents]
rows = [["state_icon", "workspace", "tab", "$cache"], ["terminal_title_stripped"]]
```

then reload the config (`prefix+shift+r`).

On [Herdrsson](https://github.com/bagonyi/herdrsson/blob/herdrsson/FORK.md) 2026.10.29 or
later, the time can instead show as a bar of six segments that empties as you watch, by
putting `$cache_span` in the row with `format = "bar"`:

```toml
[ui.sidebar.agents]
rows = [["state_icon", "workspace", "tab", { token = "$cache_span", format = "bar", rules = [
  { equals = "▰▱▱▱▱▱", fg = "#ff9e64" },
  { equals = "▱▱▱▱▱▱", hide = true },
] }]]
```

It starts full, counting from the agent's last request, and loses a segment each time a
sixth of its cache time is over: every 10 minutes of an hour's cache, every 50 seconds of a
5-minute one. Rules match the segments shown: here the last one is orange, and an empty
bar is hidden, which it can only be when the token outlasts the cache (see
[Limitations](#limitations)).

Or count down in minutes (`42m left`, `50s left` in steps of 10 seconds, `0s left` in the
last 10) with `{ token = "$cache_until", format = "left" }`.

Only Herdrsson 2026.10.29 and later know `format = "left"` and `"bar"`. Stock Herdr and
older Herdrsson builds reject them, and at startup that makes them ignore the **whole**
`config.toml`, not just this row: they start with their defaults (a config reload in a
running server only keeps its old sidebar settings).

## Requirements

- Herdr 0.9.3 or later
- macOS or Linux
- `python3` on `PATH` (standard library only)
- Claude Code with Herdr's Claude integration, which tells Herdr each agent's
  conversation
- Only for the bar and the `42m left` countdown: [Herdrsson](https://github.com/bagonyi/herdrsson/blob/herdrsson/FORK.md)
  2026.10.29 or later, my fork of Herdr (see [Showing the time](#showing-the-time))

Tested on macOS with Herdrsson 2026.10.29 (Herdr 0.9.5) and Claude Code 2.1.

## Install

```sh
herdr plugin link /path/to/claude-cache-timer
```

Herdr runs no startup hook when a plugin is linked: times show from the next
agent status change, for every agent at once.

## Limitations

- **Claude agents only.** Other agents' files don't record their cache use.
- **An estimate.** The plugin goes by when Claude logged each response, which
  is a little after the request was sent, and assumes 5 minutes when it
  finds no cache write near the end of the file. Requests Claude Code makes
  that don't go into the conversation's file aren't seen.
- **A long tool run.** An agent that works for longer than its cache time
  without a request, as while a long command runs, can lose its cache while
  it shows as working.
- **Switching conversation inside Claude.** `/clear` and `/resume` change the
  conversation without changing the agent's status, and Herdr has no event
  for it, so the plugin doesn't run: the agent keeps the previous
  conversation's time (or, after `/resume`, shows none) until it next works.
- **After the computer sleeps.** Herdr's token lifetimes stop while the
  computer sleeps, so the tokens can outlast the cache until the next run
  (any agent's next status change) clears them. Meanwhile a bar shows empty
  (hide it with a rule, as above), `left` shows `0s left`, and `$cache` shows
  a time that has passed.

## Uninstall

```sh
herdr plugin unlink bagonyi.claude-cache-timer
```

The tokens already reported stay until they expire, within the hour, or
until the server restarts, even on agents that start working.
