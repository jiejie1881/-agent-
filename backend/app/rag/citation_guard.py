"""Validate explicit chunk-ID citations, not natural-language entailment.

Only citations syntactically marked with brackets or 'Chunk ID:' are checked.
Source/section prose is retained for compatibility and is not semantically
verified here. IDs must resolve to exactly one current authorized tool result.
"""
import re


_CITATION = re.compile(
    r'\[\s*(?:chunk(?:\s+id)?\s*[:：]\s*)?([0-9a-f]{8,})(?:\.{3}|…)?\s*\]'
    r'|\bchunk\s+id\s*[:：]\s*([0-9a-f]{8,})(?:\.{3}|…)?(?![0-9a-f])', re.IGNORECASE)


def validate_chunk_citations(content, authorized_ids):
    """Return citation-to-ID resolution; fail closed on unknown/ambiguous IDs.

    The caller must revalidate its authorization immediately before this call.
    No model call, I/O, fuzzy repair or similarity threshold is involved.
    """
    ids = set(authorized_ids)
    # Explicitly labelled malformed IDs must not disappear from the hex-only
    # matcher and be mistaken for an answer containing no invalid citations.
    explicit = re.findall(r'\[\s*chunk(?:\s+id)?\s*[:：]\s*([^\]]*)\]', content, re.IGNORECASE)
    explicit += re.findall(r'\bchunk\s+id\s*[:：]\s*([^\s\],;。]+)', content, re.IGNORECASE)
    if any(not re.fullmatch(r'[0-9a-f]{8,64}(?:\.{3}|…)?', token.strip(), re.IGNORECASE)
           for token in explicit):
        raise ValueError('Malformed explicit knowledge citation')
    resolved = {}
    for match in _CITATION.finditer(content):
        citation = next(value for value in match.groups() if value is not None).lower()
        matches = {identifier for identifier in ids if identifier.lower().startswith(citation)}
        if len(citation) > 64 or len(matches) != 1:
            raise ValueError('Unverified or ambiguous knowledge citation')
        resolved[citation] = matches.pop()
    return resolved
