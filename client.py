#!/usr/bin/env python3
"""
oxigraph_client.py — Thin Python client for the local Oxigraph SPARQL endpoint.

Used by Chief (Cipher), Quant, and any other OpenClaw agent that needs to
read/write the shared knowledge graph.

Auto-detects environment:
  - Local host (Chief/Cipher on Mac mini): uses 127.0.0.1:9876
  - Docker container (Quant): uses host.docker.internal:9876
  - Override: set OXI_URL env var

Usage:
    from oxigraph_client import OxigraphClient

    kg = OxigraphClient()  # auto-detects URL
    kg.update("INSERT DATA { <http://ex.org/alice> <http://ex.org/name> \"Alice\" }")
    results = kg.query("SELECT ?s WHERE { ?s ?p ?o }")
    for row in results:
        print(row.s, row.p, row.o)
"""

import os
import json
import socket
import urllib.request
import urllib.parse
from typing import Optional, List, Dict, Any


def _detect_url():
    """Auto-detect the right URL based on environment."""
    explicit = os.environ.get("OXI_URL")
    if explicit:
        return explicit
    # Check if we're in a Docker container by looking for /.dockerenv or hostname
    in_docker = os.path.exists("/.dockerenv") or os.path.exists("/proc/1/cgroup")
    if in_docker:
        return "http://host.docker.internal:9876"
    return "http://127.0.0.1:9876"


DEFAULT_URL = _detect_url()
DEFAULT_TOKEN = os.environ.get("OXI_AUTH", "oxigraph-local-dev")


def _default_url():
    """Resolve URL fresh each call (env may change)."""
    return os.environ.get("OXI_URL") or _detect_url()


def _default_token():
    return os.environ.get("OXI_AUTH", DEFAULT_TOKEN)


class OxigraphClient:
    def __init__(self, url: str = None, token: str = None, timeout: float = 30.0):
        self.url = (url or _default_url()).rstrip("/")
        self.token = token or _default_token()
        self.timeout = timeout

    # ── Low-level HTTP ────────────────────────────────────────────────────
    def _request(self, method: str, path: str, *, body: bytes = b"",
                 content_type: Optional[str] = None,
                 extra_headers: Optional[Dict[str, str]] = None,
                 query_string: str = "") -> bytes:
        url = f"{self.url}{path}"
        if query_string:
            url += "?" + query_string
        headers = {"Accept": "*/*"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if content_type:
            headers["Content-Type"] = content_type
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(url, data=body if body else None,
                                     method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            raise OxigraphError(f"HTTP {e.code}: {e.read().decode()}")
        except urllib.error.URLError as e:
            raise OxigraphError(f"Connection failed: {e}")

    # ── Health ────────────────────────────────────────────────────────────
    def health(self) -> Dict[str, Any]:
        return json.loads(self._request("GET", "/health"))

    def count(self) -> int:
        return self.health().get("quad_count", 0)

    # ── Query ─────────────────────────────────────────────────────────────
    def query(self, sparql: str, format: str = "json") -> Dict[str, Any]:
        """Run a SPARQL SELECT/ASK/CONSTRUCT. Returns parsed JSON dict for SELECT/ASK,
        or raw text for CONSTRUCT/DESCRIBE."""
        if format == "json":
            body = self._request(
                "GET", "/sparql",
                query_string=urllib.parse.urlencode({"query": sparql}),
            )
            return json.loads(body)
        else:
            # For other formats return raw text
            return self._request(
                "GET", "/sparql",
                query_string=urllib.parse.urlencode({"query": sparql, "format": format}),
            ).decode()

    def select(self, sparql: str) -> List[Dict[str, str]]:
        """Run a SPARQL SELECT and return rows as list of dicts (var -> URI/literal)."""
        res = self.query(sparql, format="json")
        return res.get("results", {}).get("bindings", [])

    def ask(self, sparql: str) -> bool:
        """Run a SPARQL ASK and return boolean."""
        res = self.query(sparql, format="json")
        return res.get("boolean", False)

    def construct(self, sparql: str, format: str = "turtle") -> str:
        """Run a SPARQL CONSTRUCT and return the RDF text."""
        return self.query(sparql, format=format)

    # ── Update ────────────────────────────────────────────────────────────
    def update(self, sparql_update: str) -> bool:
        """Run a SPARQL Update (INSERT/DELETE/CLEAR/etc.)."""
        self._request("POST", "/update", body=sparql_update.encode(),
                      content_type="application/sparql-update")
        return True

    def insert(self, subject: str, predicate: str, obj: str, is_literal: bool = False) -> bool:
        """Convenience: insert a single triple."""
        def fmt(v, lit):
            if lit:
                return f'"{v.replace(chr(34), chr(92)+chr(34))}"'
            return f"<{v}>"
        s, p = f"<{subject}>", f"<{predicate}>"
        o = fmt(obj, is_literal)
        return self.update(f"INSERT DATA {{ {s} {p} {o} . }}")

    def clear(self, confirm: bool = False) -> bool:
        if not confirm:
            raise OxigraphError("clear() requires confirm=True")
        self._request("POST", "/clear?confirm=yes", body=b"")
        return True

    # ── Bulk upload ───────────────────────────────────────────────────────
    def upload(self, data: bytes, format: str = "turtle") -> Dict[str, Any]:
        """Bulk upload RDF data."""
        rdf_fmt = {"turtle": "turtle", "ttl": "ttl", "nt": "nt", "ntriples": "ntriples",
                   "nq": "nq", "nquads": "nquads", "trig": "trig",
                   "rdf": "rdfxml", "rdfxml": "rdfxml", "jsonld": "jsonld"}.get(format, format)
        result = self._request("POST", f"/upload?format={rdf_fmt}",
                               body=data, content_type="text/plain")
        return json.loads(result)

    def dump(self, format: str = "turtle") -> str:
        """Dump entire store. Note: oxigraph requires dataset format (nquads/trig)."""
        return self._request("GET", f"/dump?format={format}").decode()


class OxigraphError(Exception):
    pass


# ─── Convenience: use the local store directly (no HTTP) ─────────────────────
def local_store(path: str = "/Users/jasonjia/.openclaw/workspace/oxigraph/data/oxigraph.db"):
    """Return a pyoxigraph.Store object bound to the local DB file.
    Useful for batch operations / bulk loads without HTTP overhead."""
    from pyoxigraph import Store
    return Store(path)


if __name__ == "__main__":
    # Self-test
    c = OxigraphClient()
    print(f"URL: {c.url}")
    print("Health:", c.health())
    print("Triples:", c.count())
    # Demo insert
    c.update("""
    PREFIX ex: <http://example.org/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    INSERT DATA {
      ex:demo2 a ex:DemoThing ;
              rdfs:label "Oxigraph client working from CLI" .
    }
    """)
    print("After insert:", c.count())
    rows = c.select("""PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?s ?l WHERE { ?s rdfs:label ?l } LIMIT 10""")
    for r in rows:
        print("  -", r.get("s", {}).get("value"), "→", r.get("l", {}).get("value"))