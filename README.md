# openclaw-knowledge-graph

A lightweight, persistent RDF/SPARQL knowledge graph service for [OpenClaw](https://github.com/openclaw/openclaw) agents and any other Python-based agent system.

Built on [Oxigraph](https://github.com/oxigraph/oxigraph) (Rust SPARQL engine, MIT licensed).

## Why?

Most "agent memory" is either:
- **Flat text** (`MEMORY.md`) — fast but unstructured, no querying
- **Vector stores** — good for semantic similarity, bad for exact relationships
- **Neo4j + pgvector stacks** — powerful but heavy (two services, GBs of RAM)

This project is the middle ground: a single Rust binary, a single RocksDB file, full SPARQL 1.1 query/update, 1 ms response times for small graphs. Lets you store facts as `(subject, predicate, object)` triples and ask arbitrary questions about them.

## What it does

- Exposes an HTTP SPARQL endpoint on `http://127.0.0.1:9876`
- Persists data to a local RocksDB file
- Auto-detects when running in Docker (`host.docker.internal`) vs on the host
- Bearer-token auth on write endpoints (`/update`, `/upload`, `/clear`)
- Python client with 1-line setup: `from oxigraph_client import OxigraphClient`

## Install

```bash
pip install pyoxigraph requests
```

## Run the server

```bash
# Background via launchd (macOS, recommended)
curl -sSL https://raw.githubusercontent.com/openclaw/openclaw-knowledge-graph/main/launchd/install.sh | bash

# Or run directly
python3 server.py
```

Default: `http://127.0.0.1:9876`. Logs to `/tmp/openclaw/oxigraph.out.log`.

## API

| Method | Path | Purpose | Auth |
|--------|------|---------|------|
| `GET`    | `/health` | status + triple count | no |
| `GET`    | `/sparql?query=...` | SPARQL SELECT/ASK/CONSTRUCT | no |
| `POST`   | `/sparql` | SPARQL Query (long body) | yes |
| `POST`   | `/update` | SPARQL Update (INSERT/DELETE DATA, etc.) | yes |
| `POST`   | `/upload?format=...` | bulk RDF load (turtle/nt/nq/trig/rdfxml/jsonld) | yes |
| `GET`    | `/dump?format=...` | full graph dump | no |
| `POST`   | `/clear?confirm=yes` | wipe all data | yes |

Auth: `Authorization: Bearer <OXI_AUTH>` (default `oxigraph-local-dev`).

## Python client

```python
from oxigraph_client import OxigraphClient

kg = OxigraphClient()  # auto-detects host vs Docker

# Insert facts
kg.update("""
PREFIX ex: <http://example.org/>
INSERT DATA {
  ex:alice ex:name "Alice" ;
          ex:knows ex:bob .
}
""")

# Query
for row in kg.select("SELECT ?o WHERE { <http://example.org/alice> <http://example.org/name> ?o }"):
    print(row["o"]["value"])  # "Alice"

# Cross-graph queries
results = kg.query("""
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?s ?label WHERE {
  ?s rdfs:label ?label
  FILTER(CONTAINS(?label, "Alice"))
}
""")
```

See [`demo_cross_agent.py`](demo_cross_agent.py) for a complete example of cross-agent knowledge sharing.

## Configuration

| Env var       | Default                                       | Purpose                  |
|---------------|-----------------------------------------------|--------------------------|
| `OXI_HOST`    | `127.0.0.1`                                   | bind address             |
| `OXI_PORT`    | `9876`                                        | listen port              |
| `OXI_AUTH`    | `oxigraph-local-dev`                          | bearer token             |
| `OXI_DATA_DIR`| `./data`                                      | DB location              |

## Use cases

- **Agent shared memory** — multiple agents (e.g. a research agent + a trading agent) sharing facts via the same store
- **Research knowledge bases** — papers, citations, claims, evidence with provenance
- **Personal note graphs** — Obsidian-style notes with proper query support
- **Decision lineage** — store every agent decision with inputs, reasoning, outputs
- **Local-first RAG** — combine with a vector store for hybrid retrieval

## Roadmap

- [ ] MCP (Model Context Protocol) adapter — expose Oxigraph as an MCP server
- [ ] WebSocket subscription for real-time updates
- [ ] Authentication improvements (mTLS, OAuth)
- [ ] Cluster mode (multiple servers, one logical graph)
- [ ] Snapshot/restore via S3-compatible storage

## License

MIT — see [`LICENSE`](LICENSE).

## Credits

- [Oxigraph](https://github.com/oxigraph/oxigraph) — Rust SPARQL engine
- [OpenClaw](https://github.com/openclaw/openclaw) — agent runtime this is built for