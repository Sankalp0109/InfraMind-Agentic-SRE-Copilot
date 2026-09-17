"""Parse a postmortem markdown file into metadata + heading-based chunks.

Chunking by heading (## sections), not fixed-size windows, per the build
plan — a postmortem's Root Cause section and its Timeline are semantically
distinct and usually a different length; splitting by heading keeps each
chunk topically coherent instead of an arbitrary token-count cut that could
land mid-sentence or mix two sections together.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
_H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_H2_SPLIT_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


@dataclass
class Chunk:
    text: str  # includes the postmortem title for context, not just the raw section
    metadata: dict


def parse_postmortem(path: Path) -> list[Chunk]:
    raw = path.read_text()
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        raise ValueError(f"{path}: missing YAML frontmatter (expected leading '---' block)")

    frontmatter = yaml.safe_load(match.group(1)) or {}
    body = match.group(2)

    h1_match = _H1_RE.search(body)
    title = h1_match.group(1).strip() if h1_match else path.stem

    base_metadata = {
        "source_file": path.name,
        "title": title,
        **{k: str(v) for k, v in frontmatter.items()},
    }

    # Split on H2 headings; the first piece (before any "## ") is the H1
    # title line plus anything before the first section, which carries no
    # independently useful content, so it's dropped rather than chunked.
    parts = _H2_SPLIT_RE.split(body)[1:]  # [heading, content, heading, content, ...]

    chunks = []
    for heading, content in zip(parts[0::2], parts[1::2]):
        heading = heading.strip()
        content = content.strip()
        chunk_text = f"{title}\n\n## {heading}\n{content}"
        chunks.append(Chunk(text=chunk_text, metadata={**base_metadata, "section": heading}))

    return chunks


def load_all_chunks(postmortems_dir: Path) -> list[Chunk]:
    chunks = []
    for path in sorted(postmortems_dir.glob("*.md")):
        chunks.extend(parse_postmortem(path))
    return chunks
