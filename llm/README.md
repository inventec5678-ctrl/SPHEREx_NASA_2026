# In-site assistant: index and language model

The assistant endpoint (`web/api_ask.py`) answers questions about the page a visitor is viewing. It uses three things:

1. Passages retrieved from an index of papers in `llm/index/`. This part is optional.
2. Facts measured by the site, read from `web/data/fields/<id>/field.json` when the page is a field or target.
3. An OpenAI-compatible chat-completions server that streams the answer. Without one, a stub answer is streamed.

Every part is optional. Without an index or an embedding model, retrieval returns nothing and answers are marked
`grounded: false`. Without a language model server, the stub answer is used, so the frontend can be built and tested.

## Endpoints

- `POST /api/ask` takes `{"question", "lang": "en"|"zh-Hant", "history"?, "context"?}` and returns `text/event-stream`.
  Each event is one `data:` line holding JSON, in this order:
  - one `sources` event (its list may be empty)
  - many `token` events
  - one `done` event with `{"grounded", "model"}`, or an `error` event with `{"message"}` if something fails.
  `model` is `"stub"` when the canned answer was used.
- `GET /api/ask/health` returns `{"llm": "up"|"down"|"stub", "index": {"chunks", "papers"}}`.

Responses with status 429 carry `{"detail": "busy"|"slow_down"|"daily_limit"}` and a `Retry-After` header. Bad
requests and bodies over 64 KiB get a 422.

## Index format (`llm/index/`)

| file | content |
|---|---|
| `chunks.jsonl` | one JSON object per line: `{"id", "paper_id", "title", "authors", "year", "arxiv", "url", "text"}` |
| `embeddings.npy` | `float32` array of shape `(n_chunks, dim)`, one row per line of `chunks.jsonl` in the same order, each row L2-normalised |

- `id` must be unique per chunk, for example `"<paper_id>#<n>"`. `paper_id` groups chunks into papers, which is the
  `papers` count in the health response.
- `year` is an integer. `arxiv` (for example `"2404.11017"`) and `url` may be empty strings.
- `text` is the passage. About 150 to 400 words works well. The first 300 characters become the `snippet` shown on
  the page, and up to 1200 characters go into the prompt.
- Embed the passages with the same model the server uses (`SX_EMBED_MODEL`, BGE-M3 by default) and the same
  `PASSAGE_PREFIX` (empty for BGE-M3), using `normalize_embeddings=True`. `llm/build_index.py` does this.
- If the row count of `embeddings.npy` does not match the number of lines in `chunks.jsonl`, the index is ignored.

The index and the embedding model are loaded on the first question and then kept in memory. Restart the web service
after you rebuild the index.

Build: `python llm/build_index.py [embed_model_path]` (reads `llm/data/chunks.jsonl`, writes `llm/index/`).

Retrieval takes the top 5 chunks by cosine similarity and drops any below `MIN_SCORE` (0.53 in `web/api_ask.py`,
calibrated for BGE-M3: 16 off-topic English/Chinese questions top out at 0.39-0.53, 22 on-topic ones score
0.51-0.74). BGE-M3 is multilingual, so a Chinese question finds the English papers; the English-only bge-small used
at first could not, and multilingual-e5-small scored off-topic and on-topic questions in overlapping ranges. The retrieval query is the question with the context kind and name in front, for example
`target Barnard's Star: how fast does it move?`. An answer counts as grounded when at least one passage clears the
threshold.

## Environment variables

| variable | default | meaning |
|---|---|---|
| `SX_EMBED_MODEL` | `BAAI/bge-m3` | sentence-transformers model name or local path, used for queries (needs the `sentence-transformers` package) |
| `SX_LLM_URL` | `http://127.0.0.1:8800/v1` | base URL of an OpenAI-compatible server (`POST <url>/chat/completions` with `stream: true`, `GET <url>/models` for health). `stub` always uses the canned answer. |
| `SX_LLM_MODEL` | `spherex-assistant` | the `model` sent to the server |
| `SX_LLM_TIMEOUT` | `60` | seconds to wait for the next streamed piece (connecting is limited to 3 s) |
| `SX_ASK_PER_MIN` | `10` | questions per visitor per minute |
| `SX_ASK_PER_DAY` | `200` | questions per visitor per day |
| `SX_ASK_INFLIGHT` | `4` | answers being streamed at once, all visitors together |

Generation uses `max_tokens` 512 and `temperature` 0.3. Any server that speaks the OpenAI streaming format works,
for example vLLM, llama.cpp `llama-server` or Ollama's `/v1`. If the server cannot be reached, the endpoint falls back
to the stub. If the server fails after it has started answering, the stream ends with an `error` event.

Visitors are identified by the salted IP hash from `web/common.py`. The text of questions is never logged or stored.
