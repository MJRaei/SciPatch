"""Lab automation and chemical safety checks from Catalyze.

Wraps the deterministic parts of Catalyze (github.com/srustisain/mit-catalyze, a
2025 LLM Hackathon project): validating Opentrons liquid-handling protocols by
simulation (its deck-slot pre-check, run-log analysis, and fix suggestions, around
Opentrons' own simulator), and looking up compounds in PubChem. Catalyze's
OpenAI agents and web interface are left out; the calling agent writes the
protocols and the safety advice. Hazard data are read from PubChem's GHS
Classification records (Catalyze requested a PubChem property that does not
exist and fell back to a five-compound table).
"""

from __future__ import annotations

import functools
import json
import os
import re
import sys
import tempfile
import time
import warnings
from pathlib import Path
from typing import Literal

import requests

PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUG_VIEW = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"
HARMONISED = "Regulation (EC) No 1272/2008"
Robot = Literal["auto", "ot2", "flex"]


@functools.cache
def _source() -> Path:
    warnings.filterwarnings("ignore")
    # Keep Opentrons' settings and calibration files out of the user's home folder.
    os.environ.setdefault(
        "OT_API_CONFIG_DIR", str(Path(tempfile.gettempdir()) / "scipatch-opentrons")
    )
    root = Path(os.environ["SCIPATCH_SOURCE_DIR"])
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def _robot(code: str) -> str:
    match = re.search(r"""["']robotType["']\s*:\s*["']([^"']+)["']""", code)
    return "flex" if match and match.group(1).lower() == "flex" else "ot2"


def simulate_protocol(protocol: str, robot: Robot = "auto", runlog_lines: int = 200) -> dict:
    """Simulate an Opentrons Python protocol (OT-2 or Flex) and report problems.

    Args:
        protocol: Opentrons Python API protocol file (.py) with a run(protocol)
            function.
        robot: "ot2", "flex", or "auto" (from requirements["robotType"]).
        runlog_lines: Maximum number of run-log lines to return.

    Returns:
        Whether the simulation succeeded; errors and warnings with suggested
        fixes; the robot and API level; counts of steps and tips used; total
        volumes aspirated and dispensed (µL); labware and pipettes loaded; and the
        run log (one line per command, with flow rates and locations).
    """
    _source()
    from src.clients.opentrons_validator import OpentronsValidator

    path = Path(protocol)
    if not path.is_file():
        raise ValueError(f"Protocol file {protocol!r} not found.")
    code = path.read_text(encoding="utf-8")
    platform = _robot(code) if robot == "auto" else robot
    validator = OpentronsValidator()
    started = time.perf_counter()
    errors, warnings_found = validator._validate_deck_slots(code, platform)
    result = {"protocol": path.name, "robot": platform}
    if errors:
        result.update(
            success=False,
            errors=errors,
            warnings=warnings_found,
            suggestions=[
                f"Use correct deck slot naming for {platform.upper()}",
                "Check all load_labware() calls for proper slot format",
            ],
        )
        return result
    from opentrons.simulate import format_runlog, simulate

    try:
        with open(path, encoding="utf-8") as handle:
            runlog, _ = simulate(handle, file_name=path.name)
    except Exception as exc:
        message = _clean_error(exc)
        result.update(
            success=False,
            errors=[message],
            warnings=[],
            suggestions=validator._generate_error_suggestions(message)
            + validator._generate_suggestions([message], []),
            seconds=round(time.perf_counter() - started, 2),
        )
        return result
    errors, warnings_found = validator._analyze_runlog(runlog)
    text = format_runlog(runlog)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    volumes = {
        kind: round(sum(float(v) for v in re.findall(rf"{kind} ([\d.]+) uL", text)), 3)
        for kind in ("Aspirating", "Dispensing")
    }
    result.update(
        success=not errors,
        errors=errors,
        warnings=warnings_found,
        suggestions=validator._generate_suggestions(errors, warnings_found),
        api_level=_api_level(code),
        steps=len(lines),
        tips_used=sum(1 for line in lines if line.startswith("Picking up tip")),
        aspirated_ul=volumes["Aspirating"],
        dispensed_ul=volumes["Dispensing"],
        labware=sorted(set(re.findall(r"load_labware\(\s*['\"]([^'\"]+)['\"]", code))),
        pipettes=sorted(set(re.findall(r"load_instrument\(\s*['\"]([^'\"]+)['\"]", code))),
        runlog=lines[:runlog_lines],
        runlog_truncated=len(lines) > runlog_lines,
        seconds=round(time.perf_counter() - started, 2),
    )
    return result


def _api_level(code: str) -> str | None:
    match = re.search(r"""["']apiLevel["']\s*:\s*["']([\d.]+)["']""", code)
    return match.group(1) if match else None


def _clean_error(exc: Exception) -> str:
    text = str(exc)
    detail = re.search(r"detail='([^']+)'", text)
    if detail:
        return detail.group(1)
    return text.strip().splitlines()[-1] if text.strip() else type(exc).__name__


def labware(search: str = "", limit: int = 25) -> dict:
    """Opentrons standard labware: load names and geometry for protocols.

    Args:
        search: Words to match in the load name, display name, or brand (e.g.
            "96 flat corning", "tiprack 200", "reservoir").
        limit: Maximum number of results.

    Returns:
        For each matching definition: load name (for load_labware), display name,
        category, brand, number of wells, well volume (µL), footprint (mm), and
        whether it is a tip rack.
    """
    _source()
    import opentrons_shared_data

    folder = Path(opentrons_shared_data.__file__).parent / "data" / "labware" / "definitions" / "2"
    words = [w.lower() for w in search.split()]
    rows = []
    for definition in sorted(folder.iterdir()):
        versions = sorted(definition.glob("*.json"), key=lambda p: int(p.stem))
        if not versions:
            continue
        data = json.loads(versions[-1].read_text(encoding="utf-8"))
        haystack = " ".join(
            [definition.name, data["metadata"]["displayName"], data["brand"]["brand"]]
        ).lower()
        if not all(w in haystack for w in words):
            continue
        wells = data.get("wells", {})
        volumes = {w["totalLiquidVolume"] for w in wells.values()}
        rows.append(
            {
                "load_name": data["parameters"]["loadName"],
                "display_name": data["metadata"]["displayName"],
                "category": data["metadata"]["displayCategory"],
                "brand": data["brand"]["brand"],
                "wells": len(wells),
                "well_volume_ul": volumes.pop() if len(volumes) == 1 else sorted(volumes),
                "footprint_mm": [
                    data["dimensions"]["xDimension"],
                    data["dimensions"]["yDimension"],
                    data["dimensions"]["zDimension"],
                ],
                "tip_rack": bool(data["parameters"].get("isTiprack")),
                "version": int(versions[-1].stem),
            }
        )
    return {"search": search, "count": len(rows), "labware": rows[:limit]}


def _get(url: str) -> dict:
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=30)
        except requests.RequestException as exc:
            if attempt == 2:
                raise RuntimeError(f"PubChem could not be reached: {exc}") from exc
            time.sleep(1 + attempt)
            continue
        if response.status_code in (400, 404):  # unknown or unparsable identifier
            return {}
        if response.status_code == 503 and attempt < 2:  # PubChem throttling
            time.sleep(1 + attempt)
            continue
        if not response.ok:
            raise RuntimeError(f"PubChem returned HTTP {response.status_code} for {url}")
        return response.json()
    return {}


_SMILES_ONLY = re.compile(r"(?:Cl|Br|[BCNOPSFI]|[cnops]|\d)+")
_CAS = re.compile(r"\d{2,7}-\d{2}-\d")


def _kind(compound: str, identifier: str) -> str:
    if identifier != "auto":
        return identifier
    text = compound.strip()
    if text.isdigit():
        return "cid"
    if _CAS.fullmatch(text):
        return "cas"
    if any(ch in text for ch in "=#()[]@/\\") or _SMILES_ONLY.fullmatch(text):
        return "smiles"
    return "name"


def _cid(compound: str, identifier: str) -> int | None:
    kind = _kind(compound, identifier)
    if kind == "cid":
        return int(compound)
    namespace = "smiles" if kind == "smiles" else "name"  # PubChem resolves CAS numbers as names
    quoted = requests.utils.quote(compound.strip(), safe="")
    data = _get(f"{PUG}/compound/{namespace}/{quoted}/cids/JSON")
    cids = data.get("IdentifierList", {}).get("CID", [])
    return int(cids[0]) if cids and cids[0] else None


def _ghs(cid: int) -> list[dict]:
    data = _get(f"{PUG_VIEW}/data/compound/{cid}/JSON?heading=GHS+Classification")
    record = data.get("Record", {})
    sources = {ref["ReferenceNumber"]: ref for ref in record.get("Reference", [])}
    entries: dict[int, dict] = {}

    def walk(section):
        for info in section.get("Information", []):
            reference = info.get("ReferenceNumber")
            value = info.get("Value", {}).get("StringWithMarkup", [])
            entry = entries.setdefault(
                reference,
                {
                    "source": sources.get(reference, {}).get("SourceName"),
                    "pictograms": [],
                    "signal": None,
                    "hazard_statements": [],
                    "precautionary_codes": [],
                },
            )
            name = info.get("Name", "")
            strings = [s.get("String", "") for s in value]
            if name == "Pictogram(s)":
                entry["pictograms"] = [
                    m["Extra"] for s in value for m in s.get("Markup", []) if m.get("Extra")
                ]
            elif name == "Signal":
                entry["signal"] = strings[0] if strings else None
            elif name == "GHS Hazard Statements":
                for text in strings:
                    match = re.match(r"(H\d{3}[A-Za-z+H\d]*)\s*(?:\(([\d.]+)%\))?:?\s*(.*)", text)
                    if match:
                        entry["hazard_statements"].append(
                            {
                                "code": match.group(1),
                                "text": match.group(3).strip(),
                                "percent_of_reports": float(match.group(2))
                                if match.group(2)
                                else None,
                            }
                        )
            elif name == "Precautionary Statement Codes":
                entry["precautionary_codes"] = re.findall(r"P\d{3}(?:\+P\d{3})*", " ".join(strings))
            elif name == "ECHA C&L Notifications Summary":
                entry["summary"] = " ".join(strings)
        for child in section.get("Section", []):
            walk(child)

    walk(record)
    rows = [e for e in entries.values() if e["hazard_statements"] or e["signal"]]
    rows.sort(key=lambda e: (HARMONISED not in (e["source"] or ""), e["source"] or ""))
    return rows


def chemical_safety(
    compound: str, identifier: Literal["auto", "name", "smiles", "cas", "cid"] = "auto"
) -> dict:
    """Identity, properties, and GHS hazard classification of a compound from PubChem.

    Args:
        compound: Name, CAS number, SMILES, or PubChem CID.
        identifier: What compound is; "auto" treats digits as a CID, 123-45-6 as a
            CAS number, and strings of SMILES symbols only (CCO, c1ccccc1,
            CC(=O)O) as SMILES, and anything else as a name. Use "name" for names
            that look like SMILES (PubChem name search ignores case: "CO" finds cobalt).

    Returns:
        PubChem CID, IUPAC name, formula, molecular weight, SMILES, InChIKey,
        XLogP; the GHS classification from each source (pictograms, signal word,
        hazard statements with the share of company reports, precautionary
        codes), with the EU harmonised classification (Regulation (EC) No
        1272/2008, Annex VI) first when it exists; and all hazard codes found.
    """
    if not compound.strip():
        raise ValueError("Give a compound name, CAS number, SMILES, or CID.")
    cid = _cid(compound, identifier)
    if cid is None:
        raise ValueError(f"PubChem has no compound matching {compound!r}.")
    fields = "IUPACName,MolecularFormula,MolecularWeight,SMILES,InChIKey,XLogP"
    properties = _get(f"{PUG}/compound/cid/{cid}/property/{fields}/JSON")
    props = properties.get("PropertyTable", {}).get("Properties", [{}])[0]
    classifications = _ghs(cid)
    codes = sorted({h["code"] for c in classifications for h in c["hazard_statements"]})
    harmonised = next((c for c in classifications if HARMONISED in (c["source"] or "")), None)
    return {
        "query": compound,
        "cid": cid,
        "iupac_name": props.get("IUPACName"),
        "formula": props.get("MolecularFormula"),
        "molecular_weight": float(props["MolecularWeight"])
        if props.get("MolecularWeight")
        else None,
        "smiles": props.get("SMILES"),
        "inchikey": props.get("InChIKey"),
        "xlogp": props.get("XLogP"),
        "eu_harmonised_hazard_codes": sorted({h["code"] for h in harmonised["hazard_statements"]})
        if harmonised
        else None,
        "hazard_codes": codes,
        "classifications": classifications,
        "pubchem_url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
        "note": None
        if classifications
        else "PubChem lists no GHS classification for this compound.",
    }
