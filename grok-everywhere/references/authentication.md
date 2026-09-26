# Authentication, routing, cost, privacy, and portability

## Authentication sources

The CLI supports three modes:

- `--auth auto` (default): `XAI_API_KEY`, then `GROK_API_KEY`, then an API key in the local Grok auth store, then an optional signed-in Grok CLI session token.
- `--auth api-key`: API key sources only.
- `--auth session`: a Grok CLI session token only.

The public and recommended route is an xAI API key:

```sh
export XAI_API_KEY="your-key"
python3 scripts/grok.py system auth-status
```

PowerShell:

```powershell
$env:XAI_API_KEY = "your-key"
py -3 scripts\grok.py system auth-status
```

Never put a key in a command argument, source file, README, screenshot, test fixture, or Git history.

## Grok CLI auth store and `GROK_HOME`

By default, the CLI looks for `auth.json` in `~/.grok/`. Set `GROK_HOME` to use a different Grok CLI home directory; the CLI then looks for `auth.json` under that directory. For example:

```sh
export GROK_HOME="/path/to/grok-home"
```

Windows PowerShell:

```powershell
$env:GROK_HOME = "C:\path\to\grok-home"
```

The explicit `--auth-file` option selects a specific auth file. The CLI reads credentials without printing their values, refuses expired tokens, and does not refresh tokens or write to the auth store.

## Session-token compatibility and API routing

A Grok CLI session token is an optional compatibility path, not the public xAI API contract; its behavior may change without notice. With session authentication, only `text` and `search` requests using the Responses API are routed through the Grok CLI proxy.

Other operations use public xAI API endpoints. This includes model and voice discovery, TTS, STT, image and video operations, and the public API stage of meeting-minutes generation. Selecting a Grok CLI session token does not establish that these endpoints support that token or that a Grok consumer subscription covers their use. Use an xAI API key for public API operations unless xAI documents otherwise.

Do not implement session-token refresh or writeback without a documented xAI contract. If a session expires, renew it with the Grok CLI outside this Skill.

## Cost and retry behavior

Search tools, model tokens, speech, image, and video operations can incur xAI charges. A direct user request authorizes that operation, not an open-ended batch.

The CLI does not retry paid POST requests after a transport failure because the server may already have accepted the request. Video polling uses GET; if polling times out, retain the returned `request_id` and check that request before considering a new generation.

When xAI returns `cost_in_usd_ticks`, the CLI reports `cost_usd`. Missing cost data means unknown, not free.

## Local artifacts and privacy

Each live run writes requests, raw responses, transcripts, and generated media under:

- `GROK_EVERYWHERE_CACHE`, when set;
- `%LOCALAPPDATA%\grok-everywhere` on Windows;
- `$XDG_CACHE_HOME/grok-everywhere` when set;
- otherwise `~/.cache/grok-everywhere`.

Saved request records redact credential fields and embedded data-URI media. Prompts, transcripts, generated outputs, and response bodies are not anonymized. Tell the user before uploading sensitive audio or private media to xAI.

## Portability

The CLI targets Python 3.9+ and uses the standard library. It is designed for macOS, Linux, and Windows; Linux and Windows have not been smoke-tested for this 0.2.0 update. Use:

- macOS/Linux: `python3 scripts/grok.py ...`
- Windows: `py -3 scripts\grok.py ...`

Official xAI API documentation remains the authority when request schemas or supported routes change.
