# Claude Cache Timer for Herdr

Shows in Herdr's agents panel when each Claude agent's prompt cache expires:

```
 agents
 ● Code/herdr · main · ▰▰▰▰▰▰
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

Herdr runs the plugin when an agent's status changes and once at startup.
While one run waits for its turn, further events' runs end at once. Each run
brings every agent up to date, so a missed event is corrected on the next
run. While an agent works it keeps sending requests, each one starting its
cache time again, but Herdr starts no run for them: so while any Claude agent
works, a small watcher process looks at the working agents' files every 2
seconds, and ends once none works. The plugin reports each Claude agent's
time to Herdr as pane tokens:

- `$cache`: `cache 14:52`, the time its cache expires.
- `$cache_until`: the same time in seconds since the epoch.
- `$cache_span`: the time of its last request and the time its cache
  expires, in seconds since the epoch, as `FROM/UNTIL`.
- `$cache_tokens`: `70.0k`, how many tokens its last request's prompt had,
  counting those read from and written to the cache: the number Claude
  Code's status line gets as the context used. Most of it is in the cache,
  and the next request after the cache has expired writes it all again.
  After `/compact`, like the status line, it shows nothing until the next
  response.

`$cache` is reported to expire with the cache. `$cache_until`, `$cache_span`
and `$cache_tokens` stay after that, so the panel can show that the cache has
expired. Nothing is kept between runs: after a server restart, which clears
Herdr's tokens, the startup run reads the times again. The watcher notes when
it starts and ends, and why, in `watching-*.log` in the plugin's state folder
(`~/.local/state/herdr/plugins/bagonyi.claude-cache-timer/`).

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
  { equals = "▱▱▱▱▱▱", fg = "#f7768e", dim = true, strikethrough = true },
] }]]
```

It starts full, counting from the agent's last request, and loses a segment each time a
sixth of its cache time is over: every 10 minutes of an hour's cache, every 50 seconds of a
5-minute one. Once the cache has expired the bar is empty, `▱▱▱▱▱▱`. Rules match the
segments shown: here the last one is orange, and an expired cache's bar is dim red and
crossed out (`strikethrough` needs Herdrsson 2026.10.29.2 or later). To show nothing once
the cache has expired, give the empty bar `hide = true` instead.

Or count down in minutes (`42m left`, `50s left` in steps of 10 seconds) with
`{ token = "$cache_until", format = "left" }`. It shows `0s left` in the last 10 seconds
and from then on; a rule can give that its own look.

To show the size of the conversation's context next to the bar (`70.0k · ▰▰▰▰▱▱`), put
`"$cache_tokens"` before it in the row. With Agent Recency's time in front as well
(`12m ago · 122.7k · ▰▰▰▰▱▱`), such a line needs a sidebar about 29 columns wide: at
Herdr's default width of 26 the end of the bar is cut off.

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
  that don't go into the conversation's file aren't seen. While an agent
  works, the tokens go by its last response, so a request still on its way
  isn't counted yet (Claude Code's status line goes by the same).
- **Switching conversation inside Claude.** `/clear` and `/resume` change the
  conversation without changing the agent's status, and Herdr has no event
  for it, so the plugin doesn't run: the agent keeps the previous
  conversation's time and context (or, after `/resume`, shows none) until it next works.
- **After the computer sleeps.** Herdr's token lifetimes stop while the
  computer sleeps, so `$cache` can outlast the cache, showing a time that
  has passed, until the next run (any agent's next status change) clears
  it. The bar and `left` go by the clock, so they're right.

## Uninstall

```sh
herdr plugin unlink bagonyi.claude-cache-timer
```

The tokens already reported stay until the server restarts (`$cache` only
until its cache expires). The same goes for `herdr plugin disable`. After
either, a watcher still running brings the working agents' tokens up to date
until none works.
