"""Find the right tool function for a plain-language request.

Each function of each installed tool is one searchable document, built from
the tool's name, summary, domains and tags, and the function's name, docs, and
parameters. Documents are ranked with BM25. Words also match their close
relatives by shared prefix ("relaxation" ~ "relax", "energies" ~ "energy"), so
agents and people need not guess exact vocabulary. Scores are scaled by each
tool's maturity, so among similar matches better-established tools come first.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from scipatch.manifest import Manifest
from scipatch.maturity import WEIGHTS
from scipatch.registry import InstalledTool
from scipatch.schema import type_label

_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    """
    a an and are as at be by can do does for from how i in is it me my of on or
    the this that to use using want what which with you your
    """.split()
)
_K1 = 1.5
_B = 0.75
_FUZZY_WEIGHT = 0.6
_MIN_FUZZY_PREFIX = 4


#: Element names, so "gold" finds tools that only mention "Au".
_ELEMENTS = dict(
    pair.split(":")
    for pair in """
    hydrogen:h helium:he lithium:li beryllium:be boron:b carbon:c nitrogen:n oxygen:o
    fluorine:f neon:ne sodium:na magnesium:mg aluminum:al aluminium:al silicon:si
    phosphorus:p sulfur:s sulphur:s chlorine:cl argon:ar potassium:k calcium:ca
    scandium:sc titanium:ti vanadium:v chromium:cr manganese:mn iron:fe cobalt:co
    nickel:ni copper:cu zinc:zn gallium:ga germanium:ge arsenic:as selenium:se
    bromine:br krypton:kr rubidium:rb strontium:sr yttrium:y zirconium:zr niobium:nb
    molybdenum:mo technetium:tc ruthenium:ru rhodium:rh palladium:pd silver:ag
    cadmium:cd indium:in tin:sn antimony:sb tellurium:te iodine:i xenon:xe cesium:cs
    caesium:cs barium:ba lanthanum:la cerium:ce praseodymium:pr neodymium:nd
    samarium:sm europium:eu gadolinium:gd terbium:tb dysprosium:dy holmium:ho
    erbium:er thulium:tm ytterbium:yb lutetium:lu hafnium:hf tantalum:ta tungsten:w
    rhenium:re osmium:os iridium:ir platinum:pt gold:au mercury:hg thallium:tl lead:pb
    bismuth:bi uranium:u plutonium:pu
    """.split()
)


def tokenize(text: str) -> list[str]:
    words = _TOKEN.findall(text.lower().replace("_", " ").replace("-", " "))
    return [word for word in words if word not in _STOPWORDS]


def _expand_query(words: list[str]) -> list[str]:
    return words + [_ELEMENTS[word] for word in words if word in _ELEMENTS]


@dataclass(frozen=True)
class SearchHit:
    tool: str
    function: str
    score: float


def _document(tool: InstalledTool, function_index: int) -> list[str]:
    manifest = tool.manifest
    function = tool.functions[function_index]
    parts: list[str] = [
        # Names count double: they are the strongest signal.
        manifest.name, manifest.name, function.name, function.name,
        manifest.title or "", manifest.summary, manifest.description or "",
        " ".join(manifest.domains), " ".join(manifest.tags),
        function.summary, function.description,
    ]  # fmt: skip
    for name, schema in function.properties.items():
        parts.append(name)
        parts.extend(str(schema.get(key, "")) for key in ("description", "x-kind", "x-unit"))
    parts.append(str(function.returns.get("description", "")))
    parts.extend(function.outputs)
    return tokenize(" ".join(parts))


def catalog_document(manifest: Manifest) -> list[str]:
    """Words describing a tool that is not installed yet (from its manifest only)."""
    functions = manifest.exported_names or []
    parts = [
        manifest.name, manifest.name, manifest.title or "", manifest.summary,
        manifest.description or "", " ".join(manifest.domains), " ".join(manifest.tags),
        " ".join(functions),
    ]  # fmt: skip
    return tokenize(" ".join(parts))


def _shared_prefix(a: str, b: str) -> int:
    length = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        length += 1
    return length


def _related(query_word: str, vocabulary: set[str]) -> dict[str, float]:
    """Vocabulary words matching ``query_word``, with a weight (1.0 = exact)."""
    matches = {query_word: 1.0} if query_word in vocabulary else {}
    if len(query_word) < _MIN_FUZZY_PREFIX:
        return matches
    for word in vocabulary:
        if word == query_word or len(word) < _MIN_FUZZY_PREFIX:
            continue
        shared = _shared_prefix(query_word, word)
        if shared >= _MIN_FUZZY_PREFIX and shared >= 0.75 * min(len(word), len(query_word)):
            matches[word] = _FUZZY_WEIGHT
    return matches


class ToolIndex:
    """BM25 index over the functions of a set of tools."""

    def __init__(self, tools: list[InstalledTool]) -> None:
        self._index(
            (
                ((tool.name, function.name), _document(tool, index))
                for tool in tools
                for index, function in enumerate(tool.functions)
            ),
            {tool.name: WEIGHTS[tool.maturity] for tool in tools},
        )

    @classmethod
    def of_documents(
        cls,
        documents: Iterable[tuple[tuple[str, str], list[str]]],
        weights: dict[str, float] | None = None,
    ) -> ToolIndex:
        """An index over any (tool, function) keyed documents, e.g. catalog tools.

        ``weights`` scales the scores of each tool's documents (default 1).
        """
        index = cls.__new__(cls)
        index._index(documents, weights)
        return index

    def _index(
        self,
        documents: Iterable[tuple[tuple[str, str], list[str]]],
        weights: dict[str, float] | None = None,
    ) -> None:
        self._weights = weights or {}
        self._keys: list[tuple[str, str]] = []
        self._docs: list[Counter[str]] = []
        self._lengths: list[int] = []
        for key, tokens in documents:
            self._keys.append(key)
            self._docs.append(Counter(tokens))
            self._lengths.append(len(tokens))
        self._average = sum(self._lengths) / len(self._lengths) if self._lengths else 0.0
        frequency: Counter[str] = Counter()
        for doc in self._docs:
            frequency.update(doc.keys())
        total = len(self._docs)
        self._idf = {
            word: math.log(1 + (total - count + 0.5) / (count + 0.5))
            for word, count in frequency.items()
        }

    def __len__(self) -> int:
        return len(self._keys)

    def search(self, query: str, limit: int = 10) -> list[SearchHit]:
        """Best-matching functions first. An empty query lists every function."""
        words = tokenize(query)
        if not words:
            return [SearchHit(tool, function, 0.0) for tool, function in self._keys[:limit]]
        vocabulary = set(self._idf)
        expanded = [_related(word, vocabulary) for word in _expand_query(words)]
        hits = []
        for index, doc in enumerate(self._docs):
            score = 0.0
            norm = _K1 * (1 - _B + _B * self._lengths[index] / (self._average or 1))
            for matches in expanded:
                best = 0.0
                for word, weight in matches.items():
                    count = doc.get(word, 0)
                    if count:
                        tf = count * (_K1 + 1) / (count + norm)
                        best = max(best, weight * self._idf[word] * tf)
                score += best
            if score > 0:
                tool, function = self._keys[index]
                score *= self._weights.get(tool, 1.0)
                hits.append(SearchHit(tool, function, round(score, 4)))
        hits.sort(key=lambda hit: (-hit.score, hit.tool, hit.function))
        return hits[:limit]


def describe_inputs(properties: dict[str, dict[str, Any]], required: list[str]) -> str:
    """One-line summary of parameters, e.g. ``structure (structure, required), fmax=0.05``."""
    parts = []
    for name, schema in properties.items():
        extras = [type_label(schema)]
        if name in required:
            extras.append("required")
        label = f"{name} ({', '.join(extras)})"
        if "default" in schema:
            label += f"={schema['default']!r}"
        parts.append(label)
    return ", ".join(parts)
