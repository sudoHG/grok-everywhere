---
name: grok-everywhere
description: Use Grok for X and web research, text generation, speech synthesis and transcription, meeting minutes, image generation/editing, and video generation/editing/extension. Trigger when the user asks to use Grok/xAI or needs these capabilities in an agent workflow. Works through a Python CLI in Codex, Claude Code, Cursor, and other hosts that can read these instructions and execute commands.
---

# Grok Everywhere

Use `scripts/grok.py` as the single execution entrypoint. It requires Python 3.9+ and only the standard library.

## Route the request

| User intent | Command |
| --- | --- |
| Ask Grok to answer, reason, analyze, or draft | `text` |
| Search X posts, accounts, or current X discussion | `search x` |
| Search the public web with optional domain filters | `search web` |
| Generate speech or compare voices | `system voices`, then `audio tts` |
| Transcribe audio or separate speakers | `audio transcribe --diarize` |
| Produce a transcript and meeting minutes | `audio minutes` |
| Generate or edit an image | `image generate` or `image edit` |
| Generate, edit, or extend video | `video generate`, `video edit`, or `video extend` |
| Check or finish downloading an existing video request | `video get REQUEST_ID` or `video resume REQUEST_ID` |
| Diagnose setup | `system auth-status`, `system models`, or `system voices` |

Read only the relevant reference before executing:

- Grok text and search: [references/search.md](references/search.md)
- Audio: [references/audio.md](references/audio.md)
- Images and video: [references/image-video.md](references/image-video.md)
- Credentials, cost, privacy, and portability: [references/authentication.md](references/authentication.md)

## Execution rules

1. Run from this Skill directory: `python3 scripts/grok.py ...`. On Windows, use `py -3 scripts\grok.py ...` when `python3` is unavailable.
2. Treat an explicit request to search, transcribe, generate, edit, extend, or test as authorization for that single external call. Otherwise explain the likely call and cost exposure before sending it.
3. Use `--dry-run` when parameters, media routing, or authorization are uncertain. Global options such as `--dry-run`, `--auth`, and `--cache-dir` must precede the module name.
4. Never print, paste, store, or return a credential. Prefer `XAI_API_KEY`; session-token support is compatibility-only.
5. Do not automatically retry paid POST requests. For video timeout, preserve and report the `request_id`; use `video get` to inspect it or `video resume` to continue polling and download instead of resubmitting.
6. Read the final JSON from stdout. Progress is on stderr. Use `artifacts` absolute paths to open or return generated files.
7. After `text`, relay the complete `answer` in the host's main response. Render prose as normal Markdown or a blockquote so it wraps; use a fenced code block only for actual code. Label it as Grok output unless independently verified.
8. State what was actually verified. A successful HTTP response does not establish answer accuracy, transcript accuracy, factual search quality, or identity-perfect media preservation.
9. Check `response_status` and `warnings`: an `incomplete` answer is partial even when the CLI successfully saved it (`ok=true`). Show the limitation, preserve the artifacts, and do not retry without a new user request.

## User-controlled defaults

- TTS voice: pass `--voice VOICE_ID` or set `XAI_VOICE`. Do not replace an explicit user choice.
- TTS language: pass `--language BCP47` or set `XAI_TTS_LANGUAGE`.
- Grok text: Web Search is available by default with `tool_choice: auto`; pass `--no-search` only when the user explicitly wants an offline/model-only answer.
- Text, search, and meeting-summary model: default `grok-4.6`. Honor `--model` or `XAI_TEXT_MODEL`; offer `grok-4.7` as a user choice, never silently upgrade to it. Use `system models` when account availability matters. For text/search, `--reasoning-effort` overrides the task's default; higher effort can be slower and more expensive.
- Image quality: use `--quality medium --resolution 2k` when the user explicitly requests high-quality, high-resolution Image 2.0 output; otherwise leave these cost-sensitive options unset.
- Run storage: pass `--cache-dir PATH` or set `GROK_EVERYWHERE_CACHE`.
- Authentication route: pass `--auth auto|api-key|session` or set `XAI_AUTH_MODE`.

List voices before offering choices when availability matters. Never assume that a model, voice, resolution, custom voice, or session-token route is enabled for every xAI account.

## Current boundary

This version covers REST workflows. It does not implement WebSocket realtime voice, streaming STT/TTS, custom-voice creation, phone/SIP agents, or automatic session-token refresh.
