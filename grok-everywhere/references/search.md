# Grok Text, X Search, and Web Search

## Ask Grok

```sh
python3 scripts/grok.py text "Explain the trade-offs of this design."
```

Text, search, and meeting summaries default to `grok-4.6`. Users can select
`--model grok-4.7` or another available model, or set `XAI_TEXT_MODEL` as their
default. Never silently switch to the newest model. `system models` checks
account availability; there is no automatic model fallback after a rejection.
Text/search accept `--reasoning-effort low|medium|high|xhigh`; support depends on
the chosen model. Omitted effort keeps low for text/quick/balanced, medium for deep.

Image understanding uses repeatable `text --image PATH_OR_URL` with the prompt.
It sends those images to xAI with `store=false`; it does not generate new images.

The `text` command offers Web Search to Grok by default with `tool_choice: auto`.
The model can search when freshness or missing context makes it useful, but it is
not forced to search every time. Use `--no-search` only when the user explicitly
wants a model-only answer.

The result JSON contains `answer`, while `result.md` preserves the same response.
Relay the complete answer in the host Agent's main response. Use wrapping Markdown
or a blockquote for prose, not a fenced code block. Clearly identify unverified
content as Grok output.

Search tools and model tokens may be billable. One text request can trigger many
server-side searches even with one tool turn, so report returned cost and tool-call
counts when available.

## X Search

Fast default:

```sh
python3 scripts/grok.py search x "What are the most discussed AI releases in the last 24 hours?" --depth quick
```

Useful filters:

```sh
python3 scripts/grok.py search x "Summarize product updates" \
  --allow xai,OpenAI --from-date 2026-07-01 --to-date 2026-07-31 \
  --media both --depth balanced
```

- `--allow` and `--exclude` are mutually exclusive.
- Each handle filter accepts at most 20 unique handles.
- Strip `@` automatically.
- `--media image|video|both` enables understanding of media attached to X posts.
- Use ISO dates. The result must still discard clearly out-of-window evidence if a downstream fetch crosses the requested boundary.

## Web Search

```sh
python3 scripts/grok.py search web "Latest stable Python release" \
  --allow-domain python.org --depth quick
```

`--allow-domain` and `--exclude-domain` are mutually exclusive, with at most five
unique domains. Use allowed domains for official-source lookups. Optional
`--enable-image-search` requests image results; `--enable-image-understanding`
allows inspecting images encountered while browsing. These are off by default.

## Depth and latency

- `quick`: requests one tool turn, low reasoning. Default for direct current-fact lookups and top-post requests.
- `balanced`: requests three turns. Use when one refinement may be needed.
- `deep`: requests eight turns and medium reasoning. Use only for genuinely cross-source research.

Do not choose `deep` by reflex. More turns increase latency, token use, tool calls, and cost. The quick path intentionally sets `stream=true`, `max_turns=1`, and `parallel_tool_calls=true`.

`max_turns` is retained for existing route compatibility, not a documented
current public-REST billing cap. A request can trigger multiple tool calls;
do not promise a fixed cost or duration from depth alone.

## Output review

The result JSON contains:

- `answer`: model-written answer;
- `citations`: deduplicated source annotations;
- `tool_call_counts`: observed search calls;
- `usage` and `cost_usd`, when returned;
- `search_items`: returned server-side tool usage details, including
  `x_posts_fetched` and `x_users_fetched` when available; absent counts are unknown;
- `response_status`, `incomplete_details`, and `warnings`: preserve partial answers
  and usage on `response.incomplete`; `ok=true` means artifacts were saved, not
  that an incomplete model response became complete;
- `artifacts`: Markdown answer and sanitized raw response.

Review links before making high-stakes or highly specific claims. Search output can miss posts, misread dates, or overstate popularity; explain the ranking method when the user asks for “top” or “hottest.”

X Search pricing changed to per-item charging on September 21, 2026. Tool-call
counts alone cannot explain cost. Preserve server usage/cost metadata and consult
current pricing; never infer a zero bill from missing fields.

Official docs:

- https://docs.x.ai/developers/tools/x-search
- https://docs.x.ai/developers/tools/web-search
