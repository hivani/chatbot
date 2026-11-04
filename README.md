# Growchatbot

A facts-only mutual-fund FAQ assistant grounded in official Groww pages. It
answers with at most three sentences, exactly one official citation, and a
`Last updated from sources` timestamp. PII, investment advice, and performance
questions are refused before retrieval, and raw PII is never persisted.

## What is included

- **Stitch-derived web UI** (`index.html`, `styles.css`, `app.js`) with a chat
  surface, official citation, timestamp, and six-artifact RAG inspector. This is
  the primary UI, served by FastAPI at `/`.
- **Streamlit reference UI** (`src/app/streamlit_app.py`) with the same chat and
  six-tab inspector for local review.
- **FastAPI API** (`src/app/api.py`) serving the web UI and JSON endpoints.
- **Guardrails** for PII, advice, and performance questions.
- **Retrieval, generation, and validation** with per-query artifacts under
  `artifacts/<query_id>/`.
- **Two retrieval modes**: Chroma + sentence-transformers locally, and a
  dependency-free BM25 index on Vercel so the function bundle stays small.

## UI design source of truth

`stitch_fintech_ai_chatbot_interface.zip` is the canonical Stitch export for the
“Fintech AI Terminal” screen. It contains `DESIGN.md`, `code.html`, and
`screen.png`; `doc/stitch/DESIGN.md` is a readable copy and the zip wins if they
differ. The production UI preserves the Stitch dark terminal layout and maps the
accent to Groww green `#00B386`. There is no live Stitch MCP connector in this
runtime, so a new export is applied by replacing the zip and updating
`index.html`, `styles.css`, and `app.js`. See `doc/stitch/README.md`.

## Local setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-local.txt
cp .env.example .env          # add GROQ_API_KEY and GROQ_MODEL
```

Run the primary web UI:

```bash
uvicorn src.app.api:app --reload
# or the Vercel-compatible root entrypoint:
uvicorn app:app --reload
# open http://127.0.0.1:8000/
```

Run the optional Streamlit reference surface:

```bash
streamlit run src/app/streamlit_app.py
```

Run the tests:

```bash
pytest -q
```

## API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | Static Stitch UI |
| `POST` | `/query` | `{"query": "..."}` → answer envelope |
| `GET` | `/health` | Index count, retriever mode, provider |
| `GET` | `/artifacts/{query_id}` | Six stage artifacts for the inspector |

Example:

```bash
curl -X POST http://localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"query": "What is the exit load on HDFC ELSS?"}'
```

## Environment variables

| Variable | Purpose |
| --- | --- |
| `GROQ_API_KEY` | Groq API key for real generation |
| `GROQ_MODEL` | Groq model id, for example `qwen/qwen3.8-27b` |
| `GROWCHAT_RETRIEVER` | Set to `lexical` to force the BM25 retriever locally |

Without a Groq key the app still runs with an extractive offline generator for
demos and tests.

## Vercel deployment

`app.py` is the Vercel entrypoint and re-exports the FastAPI app. Vercel
installs `requirements.txt` / `[project.dependencies]` from `pyproject.toml`,
which deliberately excludes torch, transformers, and Chroma. When `VERCEL=1`
is present, retrieval automatically uses the committed
`data/chunks/chunks.jsonl` BM25 index, artifacts are written under
`/tmp/growchatbot/artifacts`, and the read-only corpus is copied to `/tmp`.

Add these in **Vercel → Project Settings → Environment Variables**:

- `GROQ_API_KEY`
- `GROQ_MODEL=qwen/qwen3.8-27b`

After deploying, check:

```bash
curl https://<your-deployment>.vercel.app/health
```

A healthy response includes `"status": "ok"`, `"index_count": 108`, and
`"retriever": "lexical-bm25"`.

## Repository layout

```text
index.html / styles.css / app.js  Stitch-derived primary web UI
doc/stitch/                       Stitch design provenance and token copy
stitch_*.zip                      Canonical Stitch UI export
app.py                            Vercel entrypoint
src/app/                          FastAPI app and Streamlit reference UI
src/guardrails/                   PII, advice, and performance checks
src/ingest/                       Load, chunk, embed, and index pipeline
src/rag/                          Retriever, BM25 fallback, generator, validator
src/query/orchestrator.py         Query flow and six artifacts
data/                             Committed corpus, chunks, embeddings, Chroma index
tests/                            Unit and integration tests
```
