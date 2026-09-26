# Speech and meeting workflows

Audio CLI workflows use xAI REST endpoints. Schema checked against the official documentation on 2026-09-26. The docs do not establish when each capability first became available.

## Text to speech

```sh
python3 scripts/grok.py system voices
python3 scripts/grok.py audio tts "Good evening. [pause] <whisper>Keep this quiet.</whisper>" \
  --voice eve --language en --codec mp3 --speed 1.1 --output speech.mp3
```

The REST endpoint is `POST /v1/tts`; it has no model field. `text` and `language` are required by the API. The CLI defaults to voice `eve` and language `auto`. `--voice` is passed as `voice_id` without a local allowlist, so a known custom voice ID can be used. Speech tags in `text` are passed through unchanged; the CLI does not parse or validate them. xAI documents built-in voices, language support, and inline/wrapping tags in its [Text to Speech guide](https://docs.x.ai/developers/model-capabilities/audio/text-to-speech).

REST TTS options:

| CLI option | API field | Behavior |
| --- | --- | --- |
| `--codec` | `output_format.codec` | `mp3`, `wav`, `pcm`, `mulaw`, `alaw`; `ulaw` is accepted as an alias and sent as `mulaw`. Default is MP3. The CLI requests an `Accept` MIME type matching the codec. |
| `--sample-rate` | `output_format.sample_rate` | 8000, 16000, 22050, 24000, 44100, or 48000 Hz. |
| `--bit-rate` | `output_format.bit_rate` | MP3 only: 32000, 64000, 96000, 128000, or 192000. |
| `--speed` | `speed` | 0.7–1.5; 1.0 is normal speed. |
| `--optimize-streaming-latency` | `optimize_streaming_latency` | 0–2. This REST CLI option is forwarded but does not make the request stream. |
| `--text-normalization` / `--no-text-normalization` | `text_normalization` | Boolean; omitted unless explicitly chosen. API default is false. |
| `--with-timestamps` | `with_timestamps` | Requests a JSON envelope rather than raw audio. The CLI base64-decodes `audio`, saves it using the returned content type, and writes the remaining duration and `audio_timestamps.graph_chars` / `graph_times` data to `speech-timestamps.json`. |
| repeatable `--replace PHRASE=PRONUNCIATION` | `replace` | At most 200 unique entries; phrase up to 100 characters, pronunciation up to 128. |

The REST text limit is 60,000 characters. Character timestamps add an alignment pass and return parallel per-character start/end intervals. Output format defaults to MP3, 24 kHz, 128 kbps; bit rate applies only to MP3. These values and limits are documented in the official [TTS request and output-format reference](https://docs.x.ai/developers/model-capabilities/audio/text-to-speech).

## Transcription

```sh
python3 scripts/grok.py audio transcribe meeting.mp3 \
  --stt-model grok-voice-transcribe-2.0 --language en --format \
  --diarize --keyterm "Product Name" --filler-words
```

The REST endpoint is `POST /v1/stt` and accepts either a file upload or URL; this CLI supports local files only. The server accepts files up to 500 MB, while this CLI deliberately keeps its local-upload safety limit at 100 MiB. It preserves `transcript.json` (raw response), `transcript.md` (readable rendering), and an optional `--output` Markdown file.

| CLI option | API field | Behavior |
| --- | --- | --- |
| `--stt-model` | `model` | `grok-voice-transcribe-1.0` or `grok-voice-transcribe-2.0`; default is 2.0. This is independent of the text model used for minutes. |
| `--language CODE` | `language` | Optional formatting language. Legacy `--language auto` is normalized to omission. |
| `--format` | `format=true` | Enables inverse text normalization and requires an explicit language; `--language auto` does not satisfy this requirement. |
| `--audio-format` plus `--sample-rate` | `audio_format`, `sample_rate` | For raw/headerless `pcm`, `mulaw`, or `alaw`; both CLI options must be supplied together. Supported rates are 8000, 16000, 22050, 24000, 44100, and 48000 Hz. Container formats such as MP3/WAV are auto-detected. |
| `--multichannel` / `--channels N` | `multichannel`, `channels` | Transcribes channels independently. `N` is 2–8; raw multichannel audio requires `--channels`, while container channel counts can be detected. |
| `--diarize` | `diarize=true` | Enables anonymous speaker IDs in word segments. Without diarization the transcript is labeled `Transcript`, not `Speaker unknown`. For multichannel results, speaker IDs are counted within each channel because the same numeric label may occur on different channels. |
| repeatable `--keyterm TERM` | repeated `keyterm` fields | Up to 100 terms, each no longer than 50 characters. |
| `--filler-words` | `filler_words=true` | Keeps filler words that are otherwise removed by default. |
| `--vad-threshold N` | `vad_threshold` | 0.0–1.0; lower values may retain quieter speech but can admit more noise. |

The response may include word-level start/end times, detected language, duration, diarization labels, and per-channel results. Transcription and diarization still need human review. See xAI's [Speech to Text request, response, and limits](https://docs.x.ai/developers/model-capabilities/audio/speech-to-text).

## Meeting minutes

```sh
python3 scripts/grok.py audio minutes meeting.m4a \
  --stt-model grok-voice-transcribe-2.0 --model grok-4.6 \
  --reasoning-effort low --output minutes.md
```

This performs two separate API calls: STT first, then a chat completion over the saved transcript. `--stt-model` selects the transcription model; `--model` selects the summary model. The summary model defaults to `XAI_TEXT_MODEL` or `grok-4.6`, independent of the STT default. `--reasoning-effort` is an optional chat-completion field (`low`, `medium`, `high`, or `xhigh`). The transcript is saved before the summary call, so if that second call fails, the transcript remains available without rerunning STT. The prompt asks the model not to invent people, decisions, owners, or deadlines; review its output against the transcript before relying on it.

## Custom voices and realtime speech

Custom voice IDs may be supplied with `--voice`; the CLI does not create or manage custom voices, and `system voices` uses the built-in TTS voices endpoint rather than listing custom voices. xAI documents custom voice creation and lifecycle separately in the [Custom Voices guide](https://docs.x.ai/developers/model-capabilities/audio/custom-voices).

xAI also documents WebSocket streaming and realtime speech-to-speech, including a full-duplex `wss://api.x.ai/v1/realtime` workflow. This CLI does not implement WebSocket TTS/STT, speech-to-speech, ephemeral-token setup, or phone/SIP agents; these are distinct from the REST TTS, STT, and minutes flows above. See the official [Speech to Speech guide](https://docs.x.ai/developers/model-capabilities/audio/speech-to-speech).
