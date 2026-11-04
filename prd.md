# PRD: Groww Mutual Fund FAQ Assistant

**Product:** Growchatbot  
**Status:** Draft  
**Owner:** Product (Shivani)  
**Source:** `doc/problemstatment.txt`  
**Date:** 2026-11-01

---

## 1. Summary

Build a small, facts-only FAQ assistant for the Groww app that answers questions about a limited set of HDFC mutual fund schemes (expense ratio, exit load, minimum SIP, ELSS lock-in, riskometer, benchmark, and how to download statements). Answers must come only from official public pages, include one source link, and never give investment advice.

This is a **RAG demo**. Each pipeline stage (load, chunk, embed, retrieve, generate) must persist its outputs so the stages can be inspected, not just the final answer.

---

## 2. Problem

Retail users and support/content teams repeatedly ask the same scheme facts. Today those answers are scattered across AMC pages, scheme pages, and educational help content. Users also get opinionated “should I buy/sell?” questions mixed with factual ones, which this product must refuse.

---

## 3. Goals and non-goals

### Goals

- Answer factual MF scheme questions accurately from a small, cited corpus.
- Show **one clear citation URL** on every answer.
- Refuse advice, performance comparisons, and PII collection with a polite facts-only message plus an educational link.
- Make the RAG pipeline inspectable: store artifacts for each stage.
- Ship a working prototype with a tiny UI, README, source list, and sample Q&A.

### Non-goals

- Portfolio construction, buy/sell/hold advice, or personalized recommendations.
- Computing or ranking returns / performance.
- Full Groww product search, all AMCs, or all schemes.
- Login, account-linked data, or any personal holdings.
- Screenshots or data from Groww’s private backend.
- Third-party blogs as sources.

---

## 4. Users

| Persona | Need |
| --- | --- |
| Retail user comparing schemes | Fast, sourced facts (expense ratio, SIP min, lock-in, riskometer, etc.) |
| Support / content team | Repeatable answers to the same MF FAQs without giving advice |

---

## 5. In-scope corpus (v1)

Scrape and store these **public Groww pages** (and additional official HDFC AMC, AMFI, and SEBI URLs as needed to build a source list of at least 15; the implemented corpus has 41 sources):

| # | Page | URL |
| --- | --- | --- |
| 1 | AMC overview — HDFC Mutual Fund | https://groww.in/mutual-funds/amc/hdfc-mutual-funds |
| 2 | Large Cap — HDFC Large Cap Fund Direct Growth | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth |
| 3 | Flexi Cap — HDFC Flexi Cap Direct Plan Growth | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth |
| 4 | ELSS — HDFC ELSS Tax Saver Fund Direct Plan Growth | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth |
| 5 | Mid Cap — HDFC Mid Cap Fund Direct Growth | https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth |

**Allowed extra sources (public only):** official Groww help/education pages, HDFC AMC scheme/product pages and explicitly listed PDFs, SEBI/AMFI public pages needed for lock-in, statements, or “what is riskometer” type facts.

**Target source list size:** at least 15 URLs, delivered as CSV or Markdown. The implemented corpus has 41 official URLs.

---

## 6. Supported questions

The assistant answers **factual** queries such as:

- Expense ratio of [scheme]?
- ELSS lock-in?
- Minimum SIP?
- Exit load?
- Riskometer / benchmark?
- How to download a capital-gains statement?

Every answer:

1. States the fact in **≤ 3 sentences**.
2. Includes **one citation link**.
3. Includes `Last updated from sources: <timestamp or scrape date>`.

### Must refuse

Opinionated or portfolio questions (e.g. “Should I buy/sell?”). Response: polite, facts-only refusal + a relevant educational link. No advice language.

Performance questions: **do not compute or compare returns**. Point to the official factsheet/source page.

---

## 7. Product experience

Tiny UI:

- Welcome line.
- Three example questions.
- Persistent note: **“Facts-only. No investment advice.”**
- Chat input for a query.
- Answer with citation + last-updated line.
- Optional (demo): view of RAG stage artifacts (loaded docs, chunks, retrieved chunks, prompt, final answer).

No capture of PAN, Aadhaar, account numbers, OTPs, emails, or phone numbers. If the user pastes PII, refuse, do not store it, and ask them to rephrase without personal data.

---

## 8. Architecture (phased RAG)

Implement in explicit phases. **Persist each stage’s data** so the demo can show it.

| Phase | What happens | Stored artifact |
| --- | --- | --- |
| 1. Data loading | Scrape public pages; normalize text + URL + scrape time | Raw documents |
| 2. Data chunking | Chunk by content type (scheme tables vs long FAQ prose). Agent may choose strategy (e.g. heading-aware + table-preserving chunks) | Chunks with source URL |
| 3. Data embedding | Embed with `sentence-transformers/all-MiniLM-L6-v2` | Embedding vectors + metadata |
| 4. Vector store | Persist in **ChromaDB** | Collection in vector DB |
| 5. Retrieval | Embed query with the **same** embedding model; retrieve from the **same** Chroma collection | Top-k chunks + scores |
| 6. Generation | LLM answers from retrieved chunks only; cite one URL; refuse if not factual / not in corpus | Prompt + completion |

Retrieval must not invent facts from the LLM’s prior knowledge. If retrieved context is insufficient, say so and link the closest official page.

---

## 9. Configuration

Put model and pipeline choices in a **config file** (changeable without code edits). Put secrets in `.env`.

| Setting | Default / requirement |
| --- | --- |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2` (ingest + query) |
| Vector DB | ChromaDB |
| LLM provider (v1) | Groq |
| LLM model | From `.env` (intended: Qwen via Groq, e.g. `qwen/qwen3-32b` or the Groq Qwen id specified in env; do not hardcode) |
| API keys | Groq (and later Gemini, OpenAI, Anthropic, Mistral) in `.env` only |

Config should allow swapping:

- Embedding model name
- Chroma collection / persist path
- LLM provider
- LLM model name
- Chunk size / overlap (if applicable)
- Top-k retrieval

Future providers (config-ready, not required for v1 demo): Gemini, OpenAI, Anthropic, Mistral.

---

## 10. Constraints and compliance

| Constraint | Rule |
| --- | --- |
| Public sources only | No app-backend screenshots; no third-party blogs as citations |
| No PII | Do not accept or store PAN, Aadhaar, account numbers, OTPs, emails, phones |
| No performance claims | Do not compute/compare returns; link official factsheet |
| Clarity | ≤ 3 sentences; `Last updated from sources:` on answers |
| No advice | Refuse buy/sell/portfolio opinion |

**UI disclaimer (required deliverable):** facts-only, no investment advice.

---

## 11. Functional requirements

1. Ingest the listed AMC + scheme pages and additional official URLs into persisted raw docs.
2. Chunk, embed, and upsert into ChromaDB with source URL metadata.
3. On query: retrieve relevant chunks; generate a grounded answer or a refusal.
4. Always return exactly one citation URL for answered questions.
5. Refuse advice / performance computation / PII with a safe template.
6. Surface stage artifacts for the RAG demo.
7. Keep embedding model and vector store identical between ingest and query.
8. Read LLM model and API keys from `.env`; read tunables from config.

---

## 12. Deliverables

1. Working prototype (hosted app/notebook) **or** a ≤ 3-minute demo video if hosting is not possible.
2. Source list (CSV or MD) of the official URLs used (implemented: 41).
3. README: setup steps, scope (AMC + schemes), known limits.
4. Sample Q&A file: 5–10 queries with assistant answers + links.
5. Disclaimer snippet used in the UI.

---

## 13. Skills this exercise tests

- **W1 — Thinking like a model:** identify the exact fact; answer vs refuse.
- **W2 — LLMs & prompting:** instruction style, concise phrasing, polite refusals, citation wording.
- **W3 — RAG only:** small-corpus retrieval with accurate citations from AMC/SEBI/AMFI (and official Groww public) pages.

---

## 14. Success criteria

- ≥ 8/10 sample factual questions answered correctly with a working source link.
- 100% of advice-style questions refused without recommendations.
- No PII written to logs, vector DB, or stage artifacts.
- Answers stay ≤ 3 sentences and include last-updated + one citation.
- A reviewer can inspect load → chunk → embed → retrieve → generate artifacts for one query.
- README is enough to run ingest + chat locally.

---

## 15. Out of scope for later

- Multi-AMC coverage beyond HDFC v1 list.
- Streaming UI polish, auth, analytics, production eval harness.
- Live holdings, tax computation, or capital-gains numbers from a user account.

---

## 16. Open items

- Confirm the exact Groq model id in `.env` (`qwen/qwen3.8-27b` in the problem statement may not match Groq’s catalog).
- Corpus extended to 41 official URLs (Groww, HDFC AMC, AMFI, SEBI); `mid_cap` and `investor.sebi.gov.in` rows are marked `PATTERN_INFERRED_VERIFY`.
- Confirm demo surface: local Streamlit/FastAPI app vs notebook vs video.
- Confirm chunking strategy after inspecting page structure (tables vs narrative).
