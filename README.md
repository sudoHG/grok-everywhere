# Grok Everywhere

[![CI](https://img.shields.io/github/actions/workflow/status/sudoHG/grok-everywhere/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/sudoHG/grok-everywhere/actions/workflows/ci.yml) [![Release](https://img.shields.io/github/v/release/sudoHG/grok-everywhere?style=flat-square&label=release)](https://github.com/sudoHG/grok-everywhere/releases/latest) [![Downloads](https://img.shields.io/github/downloads/sudoHG/grok-everywhere/total?style=flat-square&label=downloads)](https://github.com/sudoHG/grok-everywhere/releases) [![Stars](https://img.shields.io/github/stars/sudoHG/grok-everywhere?style=flat-square&label=stars)](https://github.com/sudoHG/grok-everywhere/stargazers) [![License](https://img.shields.io/github/license/sudoHG/grok-everywhere?style=flat-square)](LICENSE) [![README views](https://hits.sh/github.com/sudoHG/grok-everywhere.svg?style=flat-square&label=README%20views)](https://hits.sh/github.com/sudoHG/grok-everywhere/)

English | [简体中文](README.zh-CN.md)

> One Grok subscription, multiple API-like capabilities.
> Plug X search, image generation, video generation, voiceovers, and transcription directly into your primary agents—Claude Code, Codex, Cursor—and your everyday workflows.

<p align="center"><img src="docs/demo.gif" width="720" alt="A fresh Claude Code session asks Grok for a video of itself as Claude's intern, fetching coffee. Grok renders it."></p>
<p align="center"><sub>One sentence in Claude Code. Grok made the video. Real run, 2026-09-27.</sub></p>

---

## Why I Built This

I subscribed to SuperGrok Heavy right when Grok 4.5 came out. By the time Grok 4.7 rolled around, I'd stopped handing it coding tasks: it was slow, and the reasoning just wasn't reliable enough. So I canceled. But plenty of people prepaid for a whole year, and a canceled plan usually keeps running until the billing period ends. Is all of that just going to sit idle?

Even if I don't want to use it for coding anymore, image generation, video generation, voice synthesis, transcription, and X search are all things I still have a use for. If I could hook them directly into my current primary tools, the remaining subscription would actually be useful.

So I built **Grok Everywhere**. It reuses your existing local Grok login session, turning those capabilities into something you can invoke just like an API. You prompt your agent in Claude Code, Codex, or Cursor, and it can search X, generate images or videos, synthesize voice, transcribe audio, and bring the results right back into your workflow.

That's also why I'm open-sourcing it: if you're also paying for Grok but no longer want to use it as your main tool, give this approach a try. There's more you can do with that subscription than just opening a chat window.

---

## One Subscription, Multiple APIs

**One Grok subscription ≈ X Search API + Image Generation API + Video Generation API + Voice API...**

With Grok Everywhere, capabilities that previously required opening the Grok web UI can now be invoked on demand by your Codex or Claude Code agents:

- **X Search API**: Pull real-time discussions, fetch posts from specific accounts, grab source URLs, and continue your research.
- **Image Generation & Editing API**: Create illustrations and cover images, edit existing images, and blend multiple reference images.
- **Video Generation & Editing API**: Generate videos from text or images, define start/end and key frames, and edit or extend existing clips.
- **Voice Synthesis API**: Turn text into voiceovers with customizable voices, languages, and speech rates.
- **Speech-to-Text API**: Transcribe audio with speaker diarization, allowing your agent to synthesize meeting minutes and action items.
- **Grok Model API**: General Q&A, writing, web search, and image understanding—with your choice of model.

---

## How It Works (The Short Version)

The underlying mechanics are straightforward:

1. You log in to your account via Grok Build (the Grok CLI), which saves your session locally.
2. Grok Everywhere reads this local session, and a Python script sends requests to the corresponding endpoints. Under subscription session mode, text and search route through the Grok CLI proxy channel, while audio, image, and video requests go directly to the appropriate xAI endpoints.
3. Results are returned to your active agent, with generated text, images, audio, and video saved locally so you can keep working with them.

You don't need to manually copy tokens, and you aren't converting your subscription into a new API key. It uses your existing login session, and the setup steps below explicitly use this workflow.

---

## Common Use Cases

Once installed, you can prompt your agent directly in natural language:

- **Social Research & Content Creation**: "Search X for the latest discussions about this product, include links to the original posts, summarize the top user questions, and generate a header image for my overview article."
- **Article Cover & Voiceover**: "Generate a cover image for this newly written article, then create an English voiceover narration for the introduction."
- **Meeting Notes & Action Items**: "Transcribe this product discussion recording with speaker diarization, and summarize the key takeaways and action items."
- **Image-to-Video Generation**: "Use this photo as the first frame to generate a 6-second slow push-in shot."

Image generation supports batch creation and multi-image editing; voice synthesis supports multiple voices; video generation supports first/last frames, keyframes, editing, and extending clips. General text Q&A and image understanding are also supported out of the box, defaulting to Grok 4.6 (or whichever model you specify).

---

## Getting Started

### 1. Prerequisites & Login

Requires **Python 3.9+**. Grok Everywhere relies solely on the Python standard library—no extra Python packages to install.

If you haven't installed Grok Build yet, follow its [official setup guide](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/01-getting-started.md). Once installed, run the following command to log in to your subscribed Grok account via your browser:

```bash
grok login
```

Download and extract this project's source code. From the repository root (containing the `grok-everywhere/` folder), open a terminal and verify your login session:

```bash
python3 grok-everywhere/scripts/grok.py --auth session system auth-status
```

On Windows, you can replace `python3` with `py -3`. The returned `status` should show `available: true`, `kind: "session"`, and `expired: false`. This indicates that the CLI found a valid login session (though it does not guarantee entitlement for every individual service). If it reports that the session has expired, rerun `grok login`.

We explicitly include `--auth session` here to prevent any existing standalone API keys on your machine from being picked up first. If your Grok configuration is stored in a non-default path, point to it with `GROK_HOME`.

### 2. Connect Your Agent (Skill Mode)

Copy the inner `grok-everywhere/` directory from the source package into your agent's skills directory:

- **Codex**: Copy to `~/.codex/skills/grok-everywhere/`
- **Claude Code**: Copy to `~/.claude/skills/grok-everywhere/`, see the [official Skills documentation](https://code.claude.com/docs/en/skills).
- **Cursor**: Copy to `~/.cursor/skills/grok-everywhere/`, see the [official Skills documentation](https://prod.cursor.com/docs/skills).

Any other tool capable of loading skills and executing commands can also be integrated. Note that this applies to local execution—remote or cloud-hosted agents will not automatically have access to your local machine's login session.

Make sure to install only the inner `grok-everywhere/` folder, not the entire source repository. After installing, start a new chat session to confirm your agent recognizes Grok Everywhere.

### 3. Generate Your First Image

Prompt your agent:

> Use Grok Everywhere to generate an image of a white paper boat floating on blue water using my Grok login session. Pass `--auth session` for the call.

Or run it directly from the repository root:

```bash
python3 grok-everywhere/scripts/grok.py --auth session image generate "A white paper boat floating on blue water" --output paper-boat.jpg
```

Upon success, you'll receive the image file, and the `artifacts` field in the output will list its path. Image generation makes a live API call that consumes quota or incurs costs; if you only want to validate your parameters without generating an image, add `--dry-run` before the subcommand.

---

## More Commands

Let your agent invoke these on demand—there's no need to memorize the parameters below. Expand the section below for examples you can run in your terminal.

<details>
<summary>Expand command cheat sheet: Search, Audio, Image, Video, and Text</summary>

> The examples below are executed from the repository root. If you are already inside the `grok-everywhere/` directory, run `python3 scripts/grok.py ...` directly.

### Text & Vision (`text`)

The default text model is `grok-4.6` (with built-in web search enabled, disable with `--no-search`; specify `grok-4.7` via `--model grok-4.7`):
```bash
# Basic reasoning and analysis
python3 grok-everywhere/scripts/grok.py --auth session text "Help me make this explanation clearer"

# Understand local images or URLs
python3 grok-everywhere/scripts/grok.py --auth session text "Describe the main subject and colors in this image" --image ./photo.png
```

### X Search & Web Search (`search`)

Fetch real-time updates directly from X or run open web searches, with `quick` / `balanced` / `deep` depth presets:
```bash
# Search real-time X discussions (quick mode)
python3 grok-everywhere/scripts/grok.py --auth session search x "What are the major AI announcements in the past 24 hours?" --depth quick

# Targeted search for specific accounts and date ranges
python3 grok-everywhere/scripts/grok.py --auth session search x "Product update summary" \
  --allow xai,OpenAI --from-date 2026-07-01 --to-date 2026-07-31

# Web search restricted to official domains
python3 grok-everywhere/scripts/grok.py --auth session search web "Latest Python stable release features" --allow-domain python.org
```

### Speech Synthesis & Meeting Minutes (`audio`)

Includes Text-to-Speech (TTS), Speech-to-Text (STT), and meeting minutes extraction:
```bash
# List available voices
python3 grok-everywhere/scripts/grok.py --auth session system voices

# Voice synthesis (TTS, supports presets like eve)
python3 grok-everywhere/scripts/grok.py --auth session audio tts "Good afternoon, everyone. Let's go over where things stand on the project." \
  --voice eve --language en --output output.mp3

# Audio transcription with speaker diarization (STT 2.0)
python3 grok-everywhere/scripts/grok.py --auth session audio transcribe meeting.m4a --diarize --output transcript.md

# One-click meeting minutes (transcribes and extracts decisions & action items)
python3 grok-everywhere/scripts/grok.py --auth session audio minutes meeting.m4a --output minutes.md
```

### Image Generation & Editing (`image`)

Powered by `grok-imagine-image-2.0`, supporting aspect ratio adjustments and blending up to 5 reference images:
```bash
# Text-to-image
python3 grok-everywhere/scripts/grok.py --auth session image generate "An origami boat in a storm, cinematic lighting" \
  --aspect-ratio 16:9 --resolution 2k --output cover.jpg

# Image editing and reference image blending
python3 grok-everywhere/scripts/grok.py --auth session image edit product.png "Place the product in front of a storefront window on a rainy night" \
  --reference-image background.jpg --aspect-ratio 16:9 --output result.jpg
```

### Video Generation, Editing & Resuming (`video`)

Text-to-video and image-to-video are powered by `grok-imagine-video-1.5`; video editing and extending are powered by `grok-imagine-video` (classic):
```bash
# Image-to-video (recommended to match aspect ratio with source image)
python3 grok-everywhere/scripts/grok.py --auth session video generate "A paper boat drifting naturally with the water flow" \
  --image boat.jpg --duration 6 --aspect-ratio 16:9 --output boat.mp4

# Constrain scene with first/last frames and keyframes
python3 grok-everywhere/scripts/grok.py --auth session video generate "Camera slowly zooms out from a close-up to a wide shot" \
  --image start.jpg --last-frame end.jpg --keyframe 3.0=mid.jpg --duration 8

# Video editing and video extension (based on classic model)
python3 grok-everywhere/scripts/grok.py --auth session video edit source.mp4 "Change the scene to a rainy neon style"
python3 grok-everywhere/scripts/grok.py --auth session video extend source.mp4 "The subject slowly walks out of the frame" --duration 4

# Async task status and resume download (Resume timed-out tasks without submitting a new generation request)
# Replace REQUEST_ID with the actual task ID returned earlier
python3 grok-everywhere/scripts/grok.py --auth session video get REQUEST_ID
python3 grok-everywhere/scripts/grok.py --auth session video resume REQUEST_ID --max-wait 600
```

</details>

---

## Local Cache & Privacy

- **Local Cache Directory**: The `--cache-dir` option takes precedence over `GROK_EVERYWHERE_CACHE`. If neither is set, it defaults to `%LOCALAPPDATA%\grok-everywhere` on Windows, `$XDG_CACHE_HOME/grok-everywhere` if set, or `~/.cache/grok-everywhere`. Artifacts with explicit `--output` paths are saved to their specified destinations.
- **Duplicate Billing Protection**: The script does not blindly retry failed paid POST requests. Asynchronous tasks like video generation retain their `request_id`, allowing you to resume polling and download results via `video resume`.
- **Privacy Considerations**: Prompt text and media are sent to xAI for processing. Local logs redact credential fields, but prompts, transcripts, raw responses, and generated files are not automatically anonymized—avoid publishing your runtime cache directory publicly.

---

## Boundaries & Known Limitations

- **Scope of Capabilities**: This project focuses on REST workflows. It currently does not include WebSocket real-time voice conversations (Realtime Voice), streaming STT/TTS, custom voice clone creation, telephony/SIP integration, or automatic session token refresh.
- **Session Access**: Reading a local session is a convenience compatibility layer; it does not constitute an official API commitment, nor does it guarantee unlimited quota or support across every account tier. X search capabilities are strictly focused on search and analysis—not posting tweets or managing accounts.
- **Tested Scope**: Version 0.2.0 has been verified under macOS / Codex via the session route across 25 representative workflow calls and 40 offline tests. On 2026-09-27, a fresh headless Claude Code session on macOS also completed one `video generate` call (6 s, 1080p) end-to-end via the session route; the demo at the top is that run. A successful API call does not mean generated content passes all quality bars—search, transcription, and media generation results still require review. Beyond that one call, Claude Code, Cursor, Windows/Linux, and standalone API key routes have not undergone the same round of end-to-end testing.
- **Quotas & Billing**: This testing confirmed that these calls work, but did not audit account billing statements. Do not assume your subscription covers all usage; endpoints that do not return pricing metadata are not guaranteed to be free.

---

## License & Disclaimer

This project is licensed under the [MIT License](LICENSE).
This is an independent open-source community project and is not officially affiliated with or endorsed by xAI, Grok, or Anthropic.
