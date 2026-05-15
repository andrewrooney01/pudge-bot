from config import ARTIFACTS_DIR, ONTOLOGY_DIR

_ORDER = ["identity.md", "values.md", "principles.md", "worldview.md", "goals.md", "inspirations.md"]


def load() -> str:
    """Return all ontology files as a single prompt-ready string."""
    sections = []

    for fname in _ORDER:
        path = ONTOLOGY_DIR / fname
        if path.exists():
            text = path.read_text().strip()
            if text:
                title = fname.replace(".md", "").title()
                sections.append(f"### {title}\n{text}")

    if ARTIFACTS_DIR.exists():
        for artifact in sorted(ARTIFACTS_DIR.glob("*.md")):
            text = artifact.read_text().strip()
            if text:
                sections.append(f"### Artifact: {artifact.stem}\n{text}")

    return "\n\n---\n\n".join(sections)
