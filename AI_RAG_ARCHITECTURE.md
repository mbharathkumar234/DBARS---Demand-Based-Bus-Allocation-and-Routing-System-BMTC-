# DBARS AI — Retrieval Architecture

Two independent indices, both FAISS `IndexFlatIP` over 384-dimensional
normalized vectors, each paired with a BM25 lexical index and fused by
Reciprocal Rank Fusion.

## 1. Ingestion

### Code index — `app/ai/ingestion/pipeline.py`

Walks the repository and keeps only source files that pass
`is_path_safe_to_index()`. Measured on the current tree:

| | |
|---|---|
| Files discovered | 29,938 |
| Files indexed | 183 |
| Files excluded | 29,755 |
| Chunks created | 1,078 |

The exclusion ratio is dominated by `node_modules`, `.venv`, `android/` and
build output. See `AI_SECURITY.md` for the secret-exclusion rules.

### Chunking is symbol-aware, not fixed-width

`app/ai/ingestion/code_parser.py` parses Python with the `ast` module and emits
one chunk per meaningful unit:

- a module chunk (docstring + imports),
- a class-overview chunk per `ClassDef`,
- a chunk per method and per top-level `FunctionDef` / `AsyncFunctionDef`.

Each chunk carries `file`, `language`, `module`, `symbol`, `type`,
`start_line`, `end_line` and `docstring`. That metadata is what makes citations
point at `predictor.py:412-455` rather than at "chunk 87", and it is why a
question about a function retrieves that function rather than a window that
happens to straddle two unrelated definitions.

TypeScript/TSX files are chunked by declaration with a regex parser, since no
TS AST is available in-process.

### Documentation index — `app/ai/ingestion/doc_pipeline.py`

23 files, 326 chunks, split on Markdown headings so a chunk is a section and
its heading path survives as `section` metadata for citation.

## 2. Embeddings — `app/ai/rag/embeddings.py`

Two providers, selected by `AI_EMBEDDING_PROVIDER`:

| Provider | Default | Notes |
|---|---|---|
| `DeterministicLocalEmbeddings` | **yes** | MD5/SHA-256 hashed word and character-3-gram features projected to 384 dimensions |
| `SentenceTransformerEmbeddings` | opt-in | Real semantic embeddings (`all-MiniLM-L6-v2` by default) |

**Be precise about what the default gives you.** Hashed n-grams are a *lexical*
signal. Two phrasings of the same idea — "how is the fare computed" and "where
is pricing calculated" — do not land near each other the way true sentence
embeddings would. The dense half of retrieval therefore behaves like a fuzzy
keyword index, not a semantic one. Calling it "semantic search" would overstate
it.

### Measured: the semantic upgrade did not improve retrieval

Both providers were built over identical content (1,580 code chunks, 326 doc
chunks) and scored on 10 "where is X implemented" questions, counting whether
the correct implementation file appeared in the top 6:

| Provider | Alone | With query expansion |
|---|---:|---:|
| `DeterministicLocalEmbeddings` (hashed n-grams) | 5/10 | **8/10** |
| `SentenceTransformer` (`all-MiniLM-L6-v2`) | 4/10 | **8/10** |

Identical with expansion, and slightly *worse* without it. The cost is not
identical: MiniLM adds **12s** to startup, **450 MB** resident, and **15 ms**
per query.

The reason is that `all-MiniLM-L6-v2` is trained on natural-language sentences,
not source code. Code chunks are identifiers, signatures and type annotations —
out of distribution for it. Meanwhile these questions carry literal tokens that
appear in the target files ("fare" → `fares.py`, "crew" → `crew.py`), which is
exactly what a lexical signal catches, and the BM25 half of the hybrid was
already supplying that. Swapping the vector half changed little.

A code-trained embedding model would be the thing to try next; a
general-purpose sentence model is not the upgrade it looks like.

The deterministic provider remains the default because it requires no model
download and makes indexing reproducible offline. To switch:

```bash
export AI_EMBEDDING_PROVIDER=sentence-transformers
python -m app.ai.ingestion.pipeline     # indices MUST be rebuilt
```

Both providers are 384-dimensional, so a mismatch would **not** raise — it
would quietly return wrong neighbours. `VectorStore.save()` therefore writes
`embedding_provider.json` next to the index, and `VectorStore.load()` logs a
warning when the active provider differs from the one that built it.

## 3. Lexical retrieval — `app/ai/rag/lexical_search.py`

A real BM25 implementation (`k1=1.5`, `b=0.75`) with
`idf = log(1 + (N - df + 0.5) / (df + 0.5))`, built over the same chunk
metadata as the vector index and constructed lazily on first use.

BM25 carries the load the hashed vectors cannot: exact symbol matches.
A query naming `require_role` or `BMTCBusPredictor` finds that symbol because
the term matches, regardless of embedding quality.

## 4. Fusion — `app/ai/rag/hybrid_retriever.py`

Vector and lexical rankings are combined by Reciprocal Rank Fusion:

```
score(d) = Σ  1 / (rrf_k + rank_i(d))        rrf_k = 60
```

RRF is rank-based, so the two systems' incomparable score scales never need
calibration, and a document ranked highly by either retriever surfaces.

`QueryRouter.route_query()` picks the target index from the query, with a regex
fast path for identifier-shaped queries (`require_role`, `create_app`,
`predict`, `route_rank_score`, `hash_password`, `BMTCBusPredictor`), which are
routed to the code index directly.

## 5. Citations

Every retrieved chunk becomes a `Citation` carrying `source_type`, `title`,
`path`, `symbol`, `start_line`, `end_line` and a snippet. Answers are rejected
by the grounding verifier when they assert file- or symbol-level facts with no
supporting citation — see `AI_SECURITY.md`.

## 6. Rebuilding

```bash
cd backend
python -m app.ai.ingestion.pipeline        # code index
python -m app.ai.ingestion.doc_pipeline    # documentation index
```

Artifacts are written to `backend/artifacts/ai_indices/{code_index,doc_index}/`
as `index.faiss`, `metadata.json`, `embedding_provider.json` and an ingestion
report.
