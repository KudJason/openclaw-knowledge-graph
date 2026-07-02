#!/usr/bin/env python3
"""
demo_cross_agent.py — Demonstrate cross-agent knowledge graph usage.

Shows how Chief (research) and Quant (trading) can share knowledge via
the Oxigraph SPARQL endpoint.

Chief writes research findings → Quant queries them for context.
Quant writes trade signals → Chief queries them for analysis.
"""

from client import OxigraphClient

KG = OxigraphClient()

# ── Schema prefixes (use full IRIs in queries for portability) ──────────────
EX = "http://example.org/kg/"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OWL = "http://www.w3.org/2002/07/owl#"


def reset_demo(confirm=False):
    """Wipe the demo namespace only."""
    if not confirm:
        print("Pass confirm=True to reset")
        return
    KG.update(f"""
    PREFIX ex: <{EX}>
    DELETE WHERE {{ ?s ?p ?o }}
    """)


def chief_writes_research():
    """Chief (research analyst) writes a research finding."""
    print("\n=== Chief writes research ===")
    KG.update(f"""
    PREFIX ex: <{EX}>
    PREFIX rdfs: <{RDFS}>
    PREFIX owl: <{OWL}>
    INSERT DATA {{
      ex:ResearchFinding:001 a ex:ResearchFinding ;
        rdfs:label "Oil price impact on CNOOC stock" ;
        ex:topic "oil-prices" ;
        ex:subjectStock <http://example.org/stocks/cnooc> ;
        ex:confidence 0.78 ;
        ex:direction "bullish" ;
        ex:publishedAt "2026-07-03" .
    }}
    """)
    print("  -> Inserted ResearchFinding:001")


def quant_writes_signal():
    """Quant writes a trading signal based on Chief's research."""
    print("\n=== Quant writes signal referencing Chief's research ===")
    KG.update(f"""
    PREFIX ex: <{EX}>
    PREFIX rdfs: <{RDFS}>
    INSERT DATA {{
      ex:Signal:2026-07-03:cnooc a ex:TradeSignal ;
        rdfs:label "Buy CNOOC" ;
        ex:action "BUY" ;
        ex:stock <http://example.org/stocks/cnooc> ;
        ex:confidence 0.65 ;
        ex:generatedBy "Quant" ;
        ex:basis ex:ResearchFinding:001 ;
        ex:timestamp "2026-07-03T00:00:00Z" .
    }}
    """)
    print("  -> Inserted Signal:2026-07-03:cnooc (basis: ResearchFinding:001)")


def chief_queries_quant():
    """Chief queries what signals Quant generated from its research."""
    print("\n=== Chief queries signals generated from its research ===")
    rows = KG.select(f"""
    PREFIX ex: <{EX}>
    PREFIX rdfs: <{RDFS}>
    SELECT ?signal ?action ?stock ?confidence WHERE {{
      ?signal ex:basis ex:ResearchFinding:001 ;
              ex:action ?action ;
              ex:stock ?stock ;
              ex:confidence ?confidence .
    }}
    """)
    for r in rows:
        print(f"  -> {r.get('signal',{}).get('value')}: "
              f"{r.get('action',{}).get('value')} "
              f"{r.get('stock',{}).get('value')} "
              f"(conf={r.get('confidence',{}).get('value')})")


def quant_queries_chief():
    """Quant queries Chief's research before generating a new signal."""
    print("\n=== Quant queries Chief's recent research on stocks ===")
    rows = KG.select(f"""
    PREFIX ex: <{EX}>
    PREFIX rdfs: <{RDFS}>
    SELECT ?finding ?topic ?stock ?direction ?conf WHERE {{
      ?finding a ex:ResearchFinding ;
               ex:topic ?topic ;
               ex:subjectStock ?stock ;
               ex:direction ?direction ;
               ex:confidence ?conf .
    }} ORDER BY DESC(?conf)
    """)
    for r in rows:
        stock_short = r.get('stock', {}).get('value', '').split('/')[-1]
        print(f"  -> {r.get('finding',{}).get('value').split('/')[-1]}: "
              f"{r.get('topic',{}).get('value')} → "
              f"{r.get('direction',{}).get('value')} "
              f"({stock_short}, "
              f"conf={r.get('conf',{}).get('value')})")


if __name__ == "__main__":
    print(f"Connected to: {KG.url}")
    print(f"Total triples: {KG.count()}")
    reset_demo(confirm=True)
    chief_writes_research()
    quant_writes_signal()
    chief_queries_quant()
    quant_queries_chief()
    print("\nDone.")