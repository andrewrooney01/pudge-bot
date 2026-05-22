from config import ARTIFACTS_DIR, ONTOLOGY_DIR

_ORDER = ["identity.md", "values.md", "principles.md", "worldview.md", "goals.md", "inspirations.md"]

# Book-length reference artifacts — loaded for Q&A but excluded from the
# daily insights prompt (too large for a CLI subprocess call).
_REFERENCE_BOOKS = {
    "complete_confidence",
    "beginning_of_infinity",
    "rational_optimist",
}


def load(include_books: bool = True) -> str:
    """Return all ontology files as a single prompt-ready string.

    Args:
        include_books: If False, skip large book reference artifacts.
                       Use False for the insights pipeline; True for Q&A.
    """
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
            if not include_books and artifact.stem in _REFERENCE_BOOKS:
                continue
            text = artifact.read_text().strip()
            if text:
                sections.append(f"### Artifact: {artifact.stem}\n{text}")

    return "\n\n---\n\n".join(sections)
