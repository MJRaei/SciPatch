"""Doping of 2D and layered materials: experiments and cause-effect relationships from papers.

Wraps the knowledge base of ARIA (github.com/yicao-elina/LLM4Chem-Explainable-synthesis):
440 doping and intercalation studies of graphene, transition-metal dichalcogenides,
topological insulators, and other layered materials, and 1,443 cause -> effect ->
property relationships with quoted mechanisms, extracted from 200+ papers by an LLM.
ARIA's Gemini reasoning and web interface are not used: the calling agent reasons
over the records. Everything runs offline.
"""

from __future__ import annotations

import functools
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

#: Relationship confidence levels, strongest first (others sort last).
_CONFIDENCE = ["experimentally proven", "strongly suggested", "hypothesized", "correlation only"]
_EMPTY = {None, "", "not reported", "none", "n/a", "null", "unknown"}


@functools.cache
def _data() -> dict[str, list[dict[str, Any]]]:
    path = Path(os.environ["MOTEL_SOURCE_DIR"]) / "outputs" / "combined_doping_data.json"
    with open(path, encoding="utf-8") as handle:
        data: dict[str, list[dict[str, Any]]] = json.load(handle)
    return data


def _paper(source_file: str | None) -> str | None:
    """The paper's title from the knowledge base's file name for it (LaTeX removed)."""
    if not source_file:
        return None
    title = re.sub(r"\.txt$", "", source_file).replace("\n", " ")
    # Formulas: T$_{d}$-WTe$_{2}$ -> Td-WTe2, La{_1}Sr{_2}... -> La1Sr2...
    title = re.sub(r"\$([^$]*)\$", lambda m: re.sub(r"^rm|[_{}^\\ ]", "", m.group(1)), title)
    title = re.sub(r"\{_\{?([^{}]*)\}?\}", r"\1", title)
    title = re.sub(r"\{(\w+)\}", r"\1", title)
    return " ".join(title.replace("_", " ").split())


def _pruned(value: Any) -> Any:
    """``value`` without empty fields, so records show only what the paper reported."""
    if isinstance(value, dict):
        kept = {key: _pruned(item) for key, item in value.items()}
        return {key: item for key, item in kept.items() if item not in (None, {}, [])} or None
    if isinstance(value, list):
        return [item for item in map(_pruned, value) if item is not None] or None
    if isinstance(value, str) and value.strip().lower() in _EMPTY:
        return None
    return value


def _words(text: str | None) -> list[str]:
    return [word.lower() for word in (text or "").split()]


def _contains_all(record: Any, words: list[str]) -> bool:
    text = json.dumps(record, ensure_ascii=False).lower()
    return all(word in text for word in words)


def _experiment_view(record: dict[str, Any]) -> dict[str, Any]:
    conditions = dict(record.get("synthesis_conditions") or {})
    view = {
        "host": record.get("host_material"),
        "dopant": _pruned(record.get("dopant")),
        "method": _pruned(conditions.pop("method", None)),
        "conditions": _pruned(conditions),
        "outcome": _pruned(record.get("doping_outcome")),
        "property_changes": _pruned(record.get("property_changes")),
        "evidence": _pruned(record.get("characterization_evidence")),
        "paper": _paper(record.get("source_file")),
    }
    return {key: value for key, value in view.items() if value is not None}


def find_doping(
    host: str | None = None,
    dopant: str | None = None,
    method: str | None = None,
    keywords: str | None = None,
    count: int = 20,
) -> dict:
    """Doping and intercalation studies of layered materials matching the filters.

    Args:
        host: Host material, matched as part of its name, e.g. "MoS2", "graphene".
        dopant: Dopant element symbol, e.g. "Li", "N", "Co".
        method: Method, matched as part of its name, e.g. "intercalation", "CVD".
        keywords: Words that must all appear somewhere in the record, e.g.
            "superconductivity" or "band gap".
        count: How many studies to return.

    Returns:
        The number of matching studies and, most completely reported first: host,
        dopant (element, concentration, precursor), method, conditions (temperature
        in °C, time in hours, atmosphere, ...), outcome (dopant site, structural
        changes, phase transitions), property changes, characterization evidence,
        and the paper's title. Fields a paper did not report are left out.
    """
    if not any((host, dopant, method, keywords)):
        raise ValueError("Give at least one of host, dopant, method, or keywords.")
    if count < 1:
        raise ValueError("count must be at least 1.")
    words = _words(keywords)
    matches = []
    for record in _data()["doping_experiments"]:
        if host and host.lower() not in str(record.get("host_material") or "").lower():
            continue
        element = str((record.get("dopant") or {}).get("element") or "")
        if dopant and dopant.lower() != element.lower():
            continue
        found = str((record.get("synthesis_conditions") or {}).get("method") or "")
        if method and method.lower() not in found.lower():
            continue
        if words and not _contains_all(record, words):
            continue
        matches.append(_experiment_view(record))
    matches.sort(key=lambda view: -len(json.dumps(view)))  # most completely reported first
    return {"total": len(matches), "studies": matches[:count]}


def find_mechanisms(keywords: str, count: int = 20) -> dict:
    """Cause-effect relationships from papers about doping, with the authors' mechanism.

    Args:
        keywords: Words that must all appear in the cause, effect, affected property,
            or quoted mechanism, e.g. "Li intercalation" or "charge transfer band gap".
        count: How many relationships to return.

    Returns:
        The number of matches and, best supported first: the cause, its effect on the
        doping, the affected property, the authors' mechanism (a quote, when the
        paper gives one), the confidence the paper supports ("experimentally proven",
        "strongly suggested", "hypothesized", ...), and the paper's title.
    """
    words = _words(keywords)
    if not words:
        raise ValueError("Give keywords, e.g. 'Li intercalation'.")
    if count < 1:
        raise ValueError("count must be at least 1.")
    matches = []
    for relation in _data()["causal_relationships"]:
        fields = [
            relation.get(key)
            for key in (
                "cause_parameter",
                "effect_on_doping",
                "affected_property",
                "mechanism_quote",
            )
        ]
        if not _contains_all(fields, words):
            continue
        matches.append(
            {
                "cause": relation.get("cause_parameter"),
                "effect": relation.get("effect_on_doping"),
                "property": relation.get("affected_property"),
                "mechanism": relation.get("mechanism_quote"),
                "confidence": relation.get("confidence_level"),
                "paper": _paper(relation.get("source_file")),
            }
        )

    def strength(match: dict[str, Any]) -> int:
        level = str(match["confidence"] or "").lower()
        return _CONFIDENCE.index(level) if level in _CONFIDENCE else len(_CONFIDENCE)

    matches.sort(key=lambda match: (strength(match), match["mechanism"] is None))
    return {"total": len(matches), "relationships": matches[:count]}


def overview() -> dict:
    """What the knowledge base covers: studies, papers, and the most common hosts and dopants.

    Returns:
        Numbers of studies, relationships, and papers; the 20 most studied host
        materials, dopant elements, and methods; and relationships by confidence.
    """
    data = _data()
    studies = data["doping_experiments"]
    relations = data["causal_relationships"]
    papers = {record.get("source_file") for record in [*studies, *relations]} - {None}

    def common(values: list[Any]) -> list[dict[str, Any]]:
        counts = Counter(value for value in values if value)
        return [{"name": name, "studies": n} for name, n in counts.most_common(20)]

    return {
        "studies": len(studies),
        "relationships": len(relations),
        "papers": len(papers),
        "hosts": common([record.get("host_material") for record in studies]),
        "dopants": common([(record.get("dopant") or {}).get("element") for record in studies]),
        "methods": common(
            [(record.get("synthesis_conditions") or {}).get("method") for record in studies]
        ),
        "confidence": dict(Counter(relation.get("confidence_level") for relation in relations)),
    }
