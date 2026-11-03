# Implementation Guide: Groww Mutual Fund FAQ Assistant

**Derived from:** [`architecture.md`](./architecture.md) and [`prd.md`](./prd.md)
**Scope:** facts-only RAG over 15–25 official HDFC/Groww/AMFI/SEBI pages.

Build order:

```
1. Create directory
2. Scrape documents
3. Load documents
4. Chunk documents
5. Embed chunks
6. Store in vector DB
7. Retrieval logic + UI
8. Edge cases + guardrail tests
```

---

## 1. Create the directory

### 1.1 Folder structure

```text
Growchatbot/
├── config.yaml
├── .env.example
├── requirements.txt
├── .gitignore
├── data/
│   ├── sources.csv          # 15–25 official URLs
│   ├── raw/                 # scraped docs
│   ├── chunks/              # chunks.jsonl
│   ├── embeddings/          # embeddings.npz + metadata.jsonl
│   └── chroma/              # Chroma persistence
├── artifacts/               # per-query stage snapshots
├── src/
│   ├── config.py
│   ├── artifacts.py
│   ├── ingest/
│   │   ├── loader.py
│   │   ├── chunker.py
│   │   └── pipeline.py
│   ├── rag/
│   │   ├── embedder.py
│   │   ├── store.py
│   │   ├── retriever.py
│   │   ├── prompts.py
│   │   ├── generator.py
│   │   └── validator.py
│   ├── guardrails/
│   │   ├── pii.py
│   │   └── intent.py
│   ├── query/
│   │   └── orchestrator.py
│   └── app/
│       ├── streamlit_app.py
│       └── api.py
├── eval/
│   ├── eval_set.yaml
│   ├── run_eval.py
│   └── sample_qa.md
└── tests/
    ├── fixtures/
    ├── test_loader.py
    ├── test_chunker.py
    ├── test_embedder.py
    ├── test_store.py
    ├── test_retriever.py
    ├── test_guardrails.py
    ├── test_validator.py
    └── test_orchestrator.py
```

### 1.2 Setup commands

```bash
mkdir -p src/{ingest,rag,guardrails,query,app} \
         data/{raw,chunks,embeddings,chroma} \
         artifacts eval tests/fixtures

touch src/__init__.py src/{ingest,rag,guardrails,query,app}/__init__.py

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-local.txt
cp .env.example .env      # add GROQ_API_KEY and GROQ_MODEL
```

### 1.3 `requirements.txt` and `requirements-local.txt`

Vercel installs `requirements.txt` (also mirrored in `pyproject.toml`). It
contains only the serverless runtime: FastAPI, Pydantic, PyYAML, Groq, and the
ingest dependencies. The full local stack adds Streamlit, Chroma, and
sentence-transformers:

```text
# requirements-local.txt
-r requirements.txt
streamlit>=1.36
uvicorn[standard]>=0.30
chromadb==1.5.9
sentence-transformers>=3.0
numpy>=1.26
pytest>=8.2
httpx>=0.27
```

### 1.4 `config.yaml`

```yaml
app:
  disclaimer: "Facts-only. No investment advice."
  max_answer_sentences: 3

paths:
  sources: data/sources.csv
  raw_dir: data/raw
  chunks_file: data/chunks/chunks.jsonl
  embeddings_dir: data/embeddings
  artifacts_dir: artifacts

embedding:
  model: sentence-transformers/all-MiniLM-L6-v2
  max_seq_length: 256
  normalize: true
  batch_size: 32

chunking:
  chunk_size: 220        # must be <= max_seq_length
  chunk_overlap: 40

vector_store:
  persist_path: data/chroma
  collection: groww_mf_faq
  distance: cosine

retrieval:
  top_k: 5
  min_score: 0.35

llm:
  provider: groq
  model_env: GROQ_MODEL
  temperature: 0.1
  max_tokens: 300
  timeout_seconds: 20
```

### 1.5 `.env.example` and `.gitignore`

```text
GROQ_API_KEY=
GROQ_MODEL=
```

Ignore `.env`, `.venv`, `data/raw/`, `data/chunks/`, `data/embeddings/`, `data/chroma/`, `artifacts/`, `__pycache__/`.

**Done when:** `python -c "from src.config import load_settings; print(load_settings().vector_store.collection)"` prints `groww_mf_faq`.

---

## 2. Scrape documents

### 2.1 Create `data/sources.csv`

Use only official public pages. Start with the 5 PRD URLs, then add official Groww help/education, AMFI, and SEBI pages until you have 15–25.

```csv
id,url,title,category,aliases,notes
hdfc-large-cap,https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth,HDFC Large Cap Fund Direct Growth,scheme,HDFC Large Cap|Large Cap Fund,
hdfc-flexi-cap,https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth,HDFC Flexi Cap Direct Plan Growth,scheme,HDFC Flexi Cap|Flexi Cap,
hdfc-elss,https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth,HDFC ELSS Tax Saver Fund Direct Plan Growth,scheme,HDFC ELSS|ELSS Tax Saver|ELSS,
hdfc-mid-cap,https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth,HDFC Mid Cap Fund Direct Growth,scheme,HDFC Mid Cap|Mid Cap,
hdfc-amc,https://groww.in/mutual-funds/amc/hdfc-mutual-funds,HDFC Mutual Fund,amc,HDFC MF|HDFC Mutual Fund,
```

Rules:

- Host allowlist: `groww.in`, `amfiindia.com`, `sebi.gov.in`.
- Scrape **only the exact URLs listed in `sources.csv`**. Never crawl or follow links found on a page.
- Do not download or index linked internal documents (SID, KIM, fact sheet, SAI, PDFs) or any other internal link targets; drop a page's "Documents"/"Downloads" section during extraction.
- No blogs, aggregators, or app-backend pages.
- Validate each URL returns HTTP 200 before adding it.
- `aliases` is optional and pipe-separated; it helps detect the scheme in a query.

### 2.2 Implement `src/ingest/loader.py`

For each source:

1. Fetch with a browser-like user agent, 20 s timeout, 3 retries with backoff.
2. Parse with BeautifulSoup + `lxml`.
3. Remove `script`, `style`, `nav`, `header`, `footer`, `aside`, `form`, `iframe`, `svg`.
4. Extract blocks:
   - headings → `{"kind": "heading", "level": 2, "text": ...}`
   - tables → `{"kind": "table", "rows": [["Expense ratio", "0.5%"], ...]}`
   - lists → `{"kind": "list", "items": [...]}`
   - paragraphs → `{"kind": "paragraph", "text": ...}`
5. Build normalized `text` (table rows on separate lines).
6. Save one file per source: `data/raw/<doc_id>.json`.

Raw document shape:

```json
{
  "doc_id": "hdfc-elss",
  "url": "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth",
  "title": "HDFC ELSS Tax Saver Fund Direct Plan Growth",
  "category": "scheme",
  "scraped_at": "2026-11-01T09:14:22Z",
  "blocks": [
    {"kind": "heading", "level": 2, "text": "Fund details"},
    {"kind": "table", "rows": [["Expense ratio", "..."], ["Exit load", "..."]]}
  ],
  "text": "...",
  "content_hash": "sha256:..."
}
```

Also write `data/raw/ingest_manifest.json` with total/succeeded/failed counts.

### 2.3 Run and check

```bash
python -m src.ingest.pipeline --stage load
```

**Done when:** 15–25 raw files exist, `failed: 0`, and a scheme page contains a table block with expense ratio/exit load rows.

**If a page is empty or JS-rendered:** look for embedded `__NEXT_DATA__` / `ld+json`, add an optional Playwright render path, or replace the source with an equivalent official page. Never keep an empty document.

---

## 3. Load documents

**Goal:** Read the raw documents saved by the scraper, validate them, and pass a clean list to the chunker. The chunker never reads `data/raw/` directly; this is the bridge between scraping and chunking.

### 3.1 Loader function

Add to `src/ingest/loader.py`:

```python
def load_raw_documents(raw_dir: Path, sources: list[SourceSpec]) -> list[RawDocument]:
    ...
```

Steps:

1. Read `data/raw/ingest_manifest.json`; require `succeeded >= 15`.
2. Iterate `data/raw/*.json`, skipping `ingest_manifest.json`.
3. Parse each file into a `RawDocument`.
4. Validate the required fields: `doc_id`, `url`, `title`, `scraped_at`, `blocks`, `text`, `content_hash`.
5. Check that `url` exists in `sources.csv` and its host is in the allowlist.
6. Reject empty `text` or empty `blocks`.
7. Recompute the hash from `text`; fail if it does not match `content_hash`.
8. Ensure `doc_id` values are unique.
9. Sort by `doc_id` so chunk IDs are deterministic.
10. Log the document count and total characters.

### 3.2 Validation rules

| Check | On failure |
| --- | --- |
| Manifest exists and `succeeded >= 15` | Stop; run scraping again |
| JSON parses and all required fields exist | Stop; report the file |
| URL is in `sources.csv` | Reject the document |
| Host is in the allowlist | Reject the document |
| `text` and `blocks` are non-empty | Reject the document |
| `content_hash` matches `text` | Stop; the file was edited or corrupted |
| `doc_id` is unique | Stop; fix the duplicate |

### 3.3 Run and check

```bash
python -m src.ingest.pipeline --stage load-docs
```

`--stage chunk` calls the same loader internally, so the chunker always receives validated documents. `--stage all` runs `load → load-docs → chunk → embed → index`.

**Done when:** all raw files load without error, the loaded count matches the manifest, every document has non-empty `text` and `blocks`, and no document points outside `sources.csv`.

---

## 4. Chunk documents

### 4.1 Rules

- Tokenizer: the embedding model's tokenizer.
- `chunk_size = 220`, `chunk_overlap = 40` (MiniLM truncates at 256).
- Split prose at headings, then at sentence boundaries.
- Keep tables intact; if a table is too large, repeat the header row in each batch. Never split a row from its header or scheme name.
- Prefix every chunk with `"<scheme/title> — <section>. "` so it is self-describing.
- `chunk_id = "<doc_id>::<section-slug>::<index>"`.

### 4.2 Output: `data/chunks/chunks.jsonl`

```json
{
  "chunk_id": "hdfc-elss::fund-details::004",
  "doc_id": "hdfc-elss",
  "source_url": "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth",
  "source_title": "HDFC ELSS Tax Saver Fund Direct Plan Growth",
  "scraped_at": "2026-11-01T09:14:22Z",
  "section": "Fund details",
  "content_type": "table",
  "text": "HDFC ELSS Tax Saver Fund Direct Plan Growth — Fund details (table). Expense ratio ...",
  "token_count": 96,
  "content_hash": "sha256:..."
}
```

### 4.3 Run and check

```bash
python -m src.ingest.pipeline --stage chunk
```

**Done when:**

- every chunk has a `source_url` from `sources.csv`;
- table rows and scheme names stay together;
- max `token_count` is around 220–275;
- chunk IDs are unique.

---

## 5. Embed chunks

### 5.1 Rules

- Model: `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions).
- Use the **same** model and normalization for ingest and queries.
- L2-normalize vectors.
- Never silently truncate: fail if a chunk exceeds `max_seq_length`.

### 5.2 Output

- `data/embeddings/embeddings.npz` — `ids` and `vectors` (float32).
- `data/embeddings/metadata.jsonl` — chunk metadata aligned by `chunk_id`, including `embedding_model` and `dim`.

### 5.3 Run and check

```bash
python -m src.ingest.pipeline --stage embed
python - <<'PY'
import numpy as np
z = np.load("data/embeddings/embeddings.npz")
print(z["vectors"].shape, z["vectors"].dtype, float(np.linalg.norm(z["vectors"][0])))
PY
```

**Done when:** shape is `(n, 384)`, dtype `float32`, and vector norm ≈ `1.0`.

---

## 6. Store in vector DB

### 6.1 Rules

- Use ChromaDB persistent client at `data/chroma`.
- Collection: `groww_mf_faq`, cosine distance.
- Upsert in batches of 100.
- Metadata must be scalar only (`str | int | float | bool`). Drop `None`; stringify lists.
- Store: `chunk_id`, `doc_id`, `source_url`, `source_title`, `section`, `content_type`, `scraped_at`.

### 6.2 Ingest pipeline

```bash
python -m src.ingest.pipeline --stage all --rebuild
```

Stages: `load → load-docs → chunk → embed → index`. `--rebuild` recreates the collection.

After upsert, assert `collection.count() == len(chunks)`.

### 6.3 Check

```bash
python - <<'PY'
from src.config import load_settings
from src.rag.store import ChromaStore
s = load_settings()
st = ChromaStore(s.vector_store.persist_path, s.vector_store.collection)
print("count:", st.count())
PY
```

**Done when:** count matches the number of chunks and a smoke query for `"HDFC ELSS exit load"` returns an ELSS URL in the top 3.

---

## 7. Retrieval logic and UI

### 7.1 Query flow

```text
question
  → guardrails (PII / advice / performance)
  → embed query with the same model
  → top-k search in the same Chroma collection
  → sufficiency check
  → grounded LLM prompt (context only)
  → validation (length, citation, timestamp, advice, grounding)
  → answer envelope + stage artifacts
```

### 7.2 Retrieval

- Embed the query with `all-MiniLM-L6-v2`.
- Retrieve `top_k = 5` from `groww_mf_faq`.
- Convert cosine distance to similarity: `score = 1 - distance`.
- Keep the metadata needed for citation and display.

### 7.3 Sufficiency check

Answer only when:

1. `top_score >= 0.35` (tune with eval);
2. the query names a scheme and a retrieved chunk is from that scheme;
3. the query names a fact type (expense ratio, exit load, SIP, lock-in, riskometer, benchmark, statement) and a retrieved chunk contains it.

Otherwise return `insufficient_context` with the closest official page. Never answer about the wrong fund.

### 7.4 Generation contract

- Send only retrieved chunks, labeled `[1]…[k]` with URL, title, section, `scraped_at`.
- Ask for JSON only:

```json
{
  "answer": "...",
  "citation_index": 1,
  "used_chunk_ids": ["..."],
  "insufficient": false
}
```

- `citation_index` is 1-based. The validator resolves it to a URL, so the model never writes a URL.
- System rules: answer only from context; max 3 sentences; no advice; no performance comparisons; no PII.

### 7.5 Validation

Every answered response must have:

- ≤ 3 sentences;
- exactly one citation URL, taken from the retrieved chunks;
- `Last updated from sources: <cited chunk scraped_at>`;
- no advice language;
- every number present in the cited chunk;
- disclaimer `Facts-only. No investment advice.`

On failure, retry once with a stricter instruction; then return a safe refusal/error. Never return unvalidated text.

### 7.6 Stage artifacts

Write for every query:

```text
artifacts/<query_id>/
├── 00_request.json
├── 01_guardrails.json
├── 02_retrieval.json
├── 03_prompt.txt
├── 04_completion.json
└── 05_response.json
```

Statuses: `answered`, `refused_advice`, `refused_performance`, `refused_pii`, `insufficient_context`, `error`.

### 7.7 UI (Streamlit)

- Welcome line and three example questions.
- Persistent note: **Facts-only. No investment advice.**
- Chat input.
- Answer card: answer, one source link, `Last updated from sources: <timestamp>`.
- Refusal card: safe message + one education link.
- RAG inspector: request, guardrails, retrieved chunks with scores, prompt, completion, final response.
- Note near input: “Don’t paste PAN, Aadhaar, account numbers, OTPs, email, or phone numbers.”
- Read artifacts from disk; do not re-run retrieval in the UI.

Optional API: `POST /query`, `GET /health`, `GET /artifacts/{query_id}`.

### 7.8 Run

```bash
python -m src.query.orchestrator "What is the exit load on HDFC ELSS?"
streamlit run src/app/streamlit_app.py
```

**Done when:**

- a factual question returns a 3-sentence answer, one working citation, and last-updated;
- an advice question is refused with no recommendation;
- a PII question is refused and the value is absent from artifacts;
- an off-corpus question returns `insufficient_context` with an official link;
- the inspector shows all six artifacts.

---

## 8. Edge cases and guardrail tests

### 8.1 Guardrail order

Run in this order and short-circuit:

1. **PII** → `refused_pii`
2. **Advice** → `refused_advice`
3. **Performance** → `refused_performance`
4. **Allow** → retrieval

If intent is unclear, allow and let the sufficiency check decide. Never guess advice into an answer.

### 8.2 PII patterns

| Type | Pattern / heuristic | Redaction |
| --- | --- | --- |
| Email | standard email regex | `[REDACTED_EMAIL]` |
| PAN | `\b[A-Z]{5}[0-9]{4}[A-Z]\b` | `[REDACTED_PAN]` |
| Aadhaar | 12 digits, optional 4-4-4 spacing | `[REDACTED_AADHAAR]` |
| Phone | optional `+91`, then `[6-9]\d{9}` | `[REDACTED_PHONE]` |
| OTP | 4–8 digits near “OTP” / “one-time password” | `[REDACTED_OTP]` |
| Account | 9–18 digits near “account”, “a/c”, “ac no” | `[REDACTED_ACCOUNT]` |

Rules: detect email/PAN first; never echo the value; store only the redacted query; no PII in logs, Chroma, prompts, or artifacts.

### 8.3 Intent signals

- **Advice:** `should i`, `buy`, `sell`, `hold`, `invest in`, `recommend`, `suggest`, `best fund`, `worth it`, `portfolio`, `which fund`, `safe bet`.
- **Performance:** `returns`, `cagr`, `xirr`, `past performance`, `how much will i earn`, `compare performance`, `profit`, `1 year return`.
- **Factual:** `expense ratio`, `exit load`, `minimum sip`, `lock-in`, `riskometer`, `benchmark`, `statement`, `download`, `capital gains statement`.

### 8.4 Guardrail test cases

Put these in `tests/test_guardrails.py`:

| Input | Expected |
| --- | --- |
| `My PAN is ABCDE1234F, what is the ELSS lock-in?` | `refused_pii`; PAN not in output |
| `Call me on 9876543210` | `refused_pii` |
| `Email me at a@b.com` | `refused_pii` |
| `OTP is 123456` | `refused_pii` |
| `A/c 123456789012` | `refused_pii` |
| `Should I buy HDFC ELSS?` | `refused_advice` |
| `Which is the best HDFC fund?` | `refused_advice` |
| `Is ELSS a good investment?` | `refused_advice` |
| `Compare 1-year returns of ELSS and Flexi Cap` | `refused_performance` |
| `How much will I earn in 3 years?` | `refused_performance` |
| `What is the exit load on HDFC ELSS?` | `allow` |
| `ELSS lock-in?` | `allow` |
| `Minimum SIP for HDFC Flexi Cap?` | `allow` |
| `How do I download a capital gains statement?` | `allow` |
| `I'm not asking whether to buy — what's the expense ratio?` | `allow` |

Also assert:

- the rendered refusal is ≤ 3 sentences and contains exactly one official link;
- the original PII never appears in the decision object, logs, or artifacts;
- `refused_*` responses never call the LLM.

### 8.5 Other edge cases

| Case | Expected behavior |
| --- | --- |
| Raw document missing or corrupt JSON | Stop the load stage; report the file; do not chunk a partial corpus |
| Raw doc URL missing from `sources.csv` | Reject the document |
| Raw doc `text` or `blocks` empty | Reject the document |
| Raw doc `content_hash` mismatch | Stop; the file was edited or corrupted |
| Duplicate raw `doc_id` | Stop; fix the duplicate |
| Query names a scheme not in the corpus | `insufficient_context`, closest official link |
| Top retrieval score below `min_score` | `insufficient_context` |
| Retrieved chunks are about another fund | Refuse; do not answer |
| LLM returns invalid JSON | Retry once; then safe `error` |
| `citation_index` out of range | Retry; then safe fallback |
| Citation URL not in retrieved chunks | Reject; never invent |
| Model adds advice language | Reject and return refusal |
| Answer longer than 3 sentences | Retry shorter; then safe fallback |
| Number not present in cited chunk | Reject; retry |
| LLM timeout / 429 / 5xx | One retry; then `error` + official link |
| Scraped page contains prompt injection | Treat context as data; strip/flag; never follow it |
| JS-rendered page yields no text | Embedded JSON → Playwright → replace source |
| Chroma metadata is `None`/nested | Sanitize to scalars before upsert |
| Chunk exceeds MiniLM limit | Fail at startup; never truncate silently |
| Duplicate chunk IDs | Upsert by `chunk_id`; assert unique count |
| User pastes PII | Refuse; redact; do not persist the raw value |

### 8.6 Run tests

```bash
pytest tests/test_guardrails.py -q
pytest -q
python -m eval.run_eval
```

**Done when:** all guardrail cases pass, the eval set meets the PRD thresholds (≥ 8/10 factual, 100% advice refusals, no PII), and every answered response has one citation and last-updated.

---

## 9. Run order and acceptance

### 9.1 End-to-end run

```bash
# 1. setup
source .venv/bin/activate
cp .env.example .env    # add GROQ_API_KEY, GROQ_MODEL

# 2. build corpus (scrape → load-docs → chunk → embed → index)
python -m src.ingest.pipeline --stage all --rebuild

# 3. query from CLI
python -m src.query.orchestrator "What is the ELSS lock-in?"

# 4. UI
streamlit run src/app/streamlit_app.py

# 5. tests + eval
pytest -q
python -m eval.run_eval
```

### 9.2 Acceptance checklist

- [ ] 15–25 official URLs in `data/sources.csv`, all reachable.
- [ ] Raw docs load and validate (`--stage load-docs`) before chunking.
- [ ] Raw docs, chunks, embeddings, and Chroma collection rebuild from scratch.
- [ ] Ingest and query use the same embedding model.
- [ ] Answers use retrieved context only; no model-memory facts.
- [ ] Exactly one citation URL per answer, from the retrieved chunks.
- [ ] Answers ≤ 3 sentences with `Last updated from sources:`.
- [ ] PII, advice, and performance questions are refused safely.
- [ ] No PII in logs, prompts, Chroma, or artifacts.
- [ ] RAG inspector shows all six artifacts for a query.
- [ ] `README.md`, `eval/sample_qa.md`, and the UI disclaimer are present.
