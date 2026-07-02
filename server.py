#!/usr/bin/env python3
"""
Oxigraph SPARQL Endpoint — lightweight knowledge graph for OpenClaw agents.

Exposes a pyoxigraph.Store via HTTP so Chief, Quant, and other agents can
query / update a shared RDF triple store.

Endpoints:
  GET  /health              — health check + stats
  GET  /sparql?query=...   — SPARQL Query (SELECT/CONSTRUCT/ASK)
  POST /sparql              — same, with body=query (auth-protected)
  POST /update              — SPARQL Update (auth-protected)
  POST /upload?format=turtle|nquads|trig|ntriples|rdfxml — bulk load (auth-protected)
  GET  /dump?format=...     — full graph dump
  POST /clear               — wipe all data (auth-protected)

Auth: Bearer token via OXI_AUTH env (default: oxigraph-local-dev)
"""

import os
import io
import json
import logging
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import threading

from pyoxigraph import (
    Store, RdfFormat, QueryResultsFormat,
    QuerySolutions, QueryBoolean, QueryTriples,
)

# ─── Config ────────────────────────────────────────────────────────────────────
DATA_DIR = Path(os.environ.get("OXI_DATA_DIR", "/Users/jasonjia/.openclaw/workspace/oxigraph/data"))
HOST = os.environ.get("OXI_HOST", "127.0.0.1")
PORT = int(os.environ.get("OXI_PORT", "9876"))
AUTH_TOKEN = os.environ.get("OXI_AUTH", "oxigraph-local-dev")
LOG_LEVEL = os.environ.get("OXI_LOG", "INFO")

DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "oxigraph.db"

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("oxigraph")

# ─── Store ─────────────────────────────────────────────────────────────────────
_store_lock = threading.RLock()
_store = Store(DB_PATH.as_posix())
log.info(f"Loaded store at {DB_PATH}")

# Format mapping
RDF_FORMATS = {
    "turtle":      RdfFormat.TURTLE,
    "ttl":         RdfFormat.TURTLE,
    "nt":          RdfFormat.N_TRIPLES,
    "ntriples":    RdfFormat.N_TRIPLES,
    "nq":          RdfFormat.N_QUADS,
    "nquads":      RdfFormat.N_QUADS,
    "trig":        RdfFormat.TRIG,
    "rdf":         RdfFormat.RDF_XML,
    "rdfxml":      RdfFormat.RDF_XML,
    "xml":         RdfFormat.RDF_XML,
    "jsonld":      RdfFormat.JSON_LD,
    "n3":          RdfFormat.N3,
}

QUERY_RESULT_FORMATS = {
    "json":   QueryResultsFormat.JSON,
    "xml":    QueryResultsFormat.XML,
    "csv":    QueryResultsFormat.CSV,
    "tsv":    QueryResultsFormat.TSV,
    "tuple":  QueryResultsFormat.TSV,
}


def _check_auth(headers) -> bool:
    auth = headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    return auth[7:] == AUTH_TOKEN


def _ct(format_str: str):
    table = {
        "json":    "application/sparql-results+json",
        "xml":     "application/sparql-results+xml",
        "csv":     "text/csv",
        "tsv":     "text/tab-separated-values",
        "tuple":   "text/tab-separated-values",
        "turtle":  "text/turtle",
        "ttl":     "text/turtle",
        "n3":      "text/n3",
        "nt":      "application/n-triples",
        "ntriples":"application/n-triples",
        "nq":      "application/n-quads",
        "nquads":  "application/n-quads",
        "rdf":     "application/rdf+xml",
        "rdfxml":  "application/rdf+xml",
        "jsonld":  "application/ld+json",
        "trig":    "application/trig",
    }
    return table.get(format_str, "application/octet-stream")


def _count_triples() -> int:
    return sum(1 for _ in _store.quads_for_pattern(None, None, None, None))


def _exec_query(query: str, result_format="json"):
    fmt = QUERY_RESULT_FORMATS.get(result_format, QueryResultsFormat.JSON)
    res = _store.query(query)
    buf = io.BytesIO()
    if isinstance(res, QuerySolutions):
        res.serialize(buf, fmt)
        return buf.getvalue(), _ct(result_format)
    elif isinstance(res, QueryBoolean):
        # Boolean serializes to JSON only
        res.serialize(buf, QueryResultsFormat.JSON)
        return buf.getvalue(), _ct("json")
    elif isinstance(res, QueryTriples):
        # Pick RDF format based on result_format or default to turtle
        rdf_fmt = RDF_FORMATS.get(result_format, RdfFormat.TURTLE)
        res.serialize(buf, rdf_fmt)
        return buf.getvalue(), _ct(result_format if result_format in RDF_FORMATS else "turtle")
    else:
        return b"", "text/plain"


def _exec_update(update: str):
    with _store_lock:
        _store.update(update)


# ─── HTTP handler ─────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    server_version = "OxigraphHTTP/0.5"

    def log_message(self, fmt, *args):
        log.debug("%s - %s", self.address_string(), fmt % args)

    def _send(self, status, body, content_type="application/json", extra_headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, indent=2).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization,Content-Type")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status, msg):
        self._send(status, {"error": str(msg)})

    def do_OPTIONS(self):
        self._send(204, b"", extra_headers={
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
            "Access-Control-Max-Age": "86400",
        })

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)

        if u.path == "/health":
            with _store_lock:
                size = _count_triples()
            return self._send(200, {
                "status": "ok",
                "store_path": DB_PATH.as_posix(),
                "quad_count": size,
                "version": "0.5.9",
            })

        if u.path == "/sparql":
            query = qs.get("query", [""])[0]
            if not query:
                return self._send_error(400, "Missing ?query=")
            fmt = qs.get("format", ["json"])[0]
            try:
                body, ct = _exec_query(query, fmt)
                return self._send(200, body, content_type=ct)
            except Exception as e:
                log.exception("query failed")
                return self._send_error(400, f"Query error: {e}")

        if u.path == "/dump":
            fmt_str = qs.get("format", ["nquads"])[0]
            # Store.dump requires a dataset-supporting format
            if fmt_str not in ("trig", "nquads", "nq", "jsonld"):
                # Default to nquads for non-dataset formats
                fmt_str = "nquads"
            rdf_fmt = RDF_FORMATS.get(fmt_str, RdfFormat.N_QUADS)
            try:
                buf = io.BytesIO()
                _store.dump(buf, rdf_fmt)
                return self._send(200, buf.getvalue(), content_type=_ct(fmt_str))
            except Exception as e:
                log.exception("dump failed")
                return self._send_error(400, f"Dump error: {e}")

        return self._send_error(404, "Not found")

    def do_POST(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length > 0 else b""

        if u.path == "/sparql":
            if not _check_auth(self.headers):
                return self._send_error(401, "Missing/invalid Authorization")
            content_type = self.headers.get("Content-Type", "")
            query = ""
            fmt = "json"
            if "application/sparql-query" in content_type:
                query = body.decode()
            elif "application/x-www-form-urlencoded" in content_type:
                form = parse_qs(body.decode())
                query = form.get("query", [""])[0]
                fmt = form.get("format", ["json"])[0]
            else:
                query = qs.get("query", [""])[0]
                fmt = qs.get("format", ["json"])[0]
            if not query:
                return self._send_error(400, "Missing query")
            try:
                out, ct = _exec_query(query, fmt)
                return self._send(200, out, content_type=ct)
            except Exception as e:
                log.exception("query failed")
                return self._send_error(400, f"Query error: {e}")

        if u.path == "/update":
            if not _check_auth(self.headers):
                return self._send_error(401, "Missing/invalid Authorization")
            content_type = self.headers.get("Content-Type", "")
            if "application/sparql-update" in content_type:
                update = body.decode()
            elif "application/x-www-form-urlencoded" in content_type:
                form = parse_qs(body.decode())
                update = form.get("update", [""])[0]
            else:
                return self._send_error(400, "Content-Type must be application/sparql-update")
            try:
                _exec_update(update)
                return self._send(200, {"status": "ok"})
            except Exception as e:
                log.exception("update failed")
                return self._send_error(400, f"Update error: {e}")

        if u.path == "/upload":
            if not _check_auth(self.headers):
                return self._send_error(401, "Missing/invalid Authorization")
            fmt_str = qs.get("format", ["turtle"])[0]
            rdf_fmt = RDF_FORMATS.get(fmt_str)
            if not rdf_fmt:
                return self._send_error(400, f"Unknown format: {fmt_str}")
            try:
                _store.bulk_load(body, rdf_fmt)
                return self._send(200, {"status": "ok", "bytes": len(body)})
            except Exception as e:
                log.exception("upload failed")
                return self._send_error(400, f"Upload error: {e}")

        if u.path == "/clear":
            if not _check_auth(self.headers):
                return self._send_error(401, "Missing/invalid Authorization")
            if qs.get("confirm", [""])[0] != "yes":
                return self._send_error(400, "Add ?confirm=yes to clear all data")
            with _store_lock:
                _store.clear()
            log.warning("STORE CLEARED")
            return self._send(200, {"status": "cleared"})

        return self._send_error(404, "Not found")


# ─── Main ──────────────────────────────────────────────────────────────────────
def main():
    log.info(f"Oxigraph server starting on http://{HOST}:{PORT}")
    log.info(f"Data dir: {DATA_DIR}")
    log.info(f"Auth: {'enabled (token prefix: ' + AUTH_TOKEN[:8] + '...)' if AUTH_TOKEN else 'DISABLED'}")
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    log.info("Ready.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down...")
        srv.shutdown()


if __name__ == "__main__":
    main()