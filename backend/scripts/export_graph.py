"""Write the compiled LangGraph as Mermaid to docs/graph.mmd (and print it).

Usage (from backend/): python -m scripts.export_graph
"""

from pathlib import Path

from app.graph.builder import build_graph

OUT = Path(__file__).resolve().parents[2] / "docs" / "graph.mmd"

if __name__ == "__main__":
    mermaid = build_graph().get_graph().draw_mermaid()
    OUT.write_text(mermaid)
    print(mermaid)
    print(f"Written to {OUT}")
