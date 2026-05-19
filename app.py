# app.py — Clinical Precision Dashboard · Drug Repurposing Backend
# Optimised for Render.com free tier (512 MB RAM, single gunicorn worker)
# IMPORTANT: set WEB_CONCURRENCY=1 in Render environment variables.
#            Two workers × RDKit ≈ 240 MB → OOM crash.
# Author: Dr. Luqman Bin Fahad, Doctor of Pharmacy

import math
import os
import re
import time
import logging
import threading
from datetime import datetime
from urllib.parse import quote

import requests
from cachetools import LRUCache
from flask import Flask, render_template, request, jsonify
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

try:
    from rdkit import Chem, DataStructs
    from rdkit.Chem import rdMolDescriptors
    RDKIT_AVAILABLE = True
except ImportError:
    RDKIT_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)

# ── LRU Caches ────────────────────────────────────────────────────────────────
# maxsize is entry count, not bytes.
# Estimated per-entry size: pubchem ~1 KB, chembl ~6 KB, ct ~10 KB, ot ~2 KB,
# score ~300 B, interact ~1 KB, cas ~30 B.
# Total ceiling at capacity: ≈ 3.5 MB — negligible vs 512 MB budget.
_lock           = threading.Lock()
_pubchem_cache  = LRUCache(maxsize=256)
_chembl_cache   = LRUCache(maxsize=128)
_ct_cache       = LRUCache(maxsize=128)
_ot_cache       = LRUCache(maxsize=256)
_score_cache    = LRUCache(maxsize=512)
_interact_cache = LRUCache(maxsize=128)
_cas_cache      = LRUCache(maxsize=256)

# ── API roots ─────────────────────────────────────────────────────────────────
PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
CHEMBL_BASE  = "https://www.ebi.ac.uk/chembl/api/data"
OT_GRAPHQL   = "https://api.platform.opentargets.org/api/v4/graphql"
CT_BASE      = "https://clinicaltrials.gov/api/v2"

_CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")

# ── Reference fingerprint set ─────────────────────────────────────────────────
# Known repurposed-drug scaffolds (PubChem canonical SMILES).
# Tanimoto similarity vs this set is one scoring component.
# RDKit parse failures are silently skipped in the loop.
_REFERENCE_SMILES = {
    "Aspirin":     "CC(=O)Oc1ccccc1C(=O)O",
    "Metformin":   "CN(C)C(=N)NC(N)=N",
    "Ibuprofen":   "CC(C)Cc1ccc(cc1)[C@@H](C)C(=O)O",
    "Imatinib":    "Cc1ccc(NC(=O)c2ccc(CN3CCN(C)CC3)cc2)cc1Nc1nccc(-c2cccnc2)n1",
    "Thalidomide": "O=C1CCC(=O)N1[C@@H]1CCc2ccccc21",
    "Doxycycline": "C[C@@H]1[C@H](O)[C@@H](N(C)C)[C@@H]2C[C@H]3C(=C(O)c4c(O)cccc4[C@@]3(O)C(=O)[C@@H]2[C@H]1O)C(N)=O",
}

# ── Curated interaction database ──────────────────────────────────────────────
_INTERACTIONS: dict[str, list[dict]] = {
    "metformin": [
        {"drug": "Iodinated contrast agents",     "severity": "High",
         "description": "Lactic acidosis; withhold 48 h peri-procedure (FDA label)"},
        {"drug": "Cimetidine",                    "severity": "Moderate",
         "description": "OCT2 inhibition raises metformin AUC ~50 %"},
        {"drug": "Alcohol",                       "severity": "Moderate",
         "description": "Potentiates hepatic lactic acid production"},
    ],
    "aspirin": [
        {"drug": "Warfarin",                      "severity": "High",
         "description": "Synergistic haemostasis impairment — major bleed risk"},
        {"drug": "Ibuprofen",                     "severity": "Moderate",
         "description": "Competitive COX-1 binding attenuates cardioprotection"},
        {"drug": "Methotrexate",                  "severity": "High",
         "description": "Reduced renal clearance → MTX toxicity"},
    ],
    "sildenafil": [
        {"drug": "Nitrates (any form)",           "severity": "High",
         "description": "Absolute contraindication — severe/fatal hypotension"},
        {"drug": "Ritonavir / strong CYP3A4 inhibitors", "severity": "High",
         "description": "3–11× sildenafil AUC elevation"},
        {"drug": "Alpha-blockers",                "severity": "Moderate",
         "description": "Additive hypotension; stagger dosing ≥4 h"},
    ],
    "atorvastatin": [
        {"drug": "Clarithromycin",                "severity": "High",
         "description": "CYP3A4 inhibition; rhabdomyolysis risk"},
        {"drug": "Amiodarone",                    "severity": "Moderate",
         "description": "Elevated myopathy risk — cap statin dose"},
        {"drug": "Colchicine",                    "severity": "Moderate",
         "description": "Myopathy, especially in renal impairment"},
    ],
    "rapamycin": [
        {"drug": "Tacrolimus",                    "severity": "High",
         "description": "Additive nephrotoxicity; PK synergism"},
        {"drug": "Strong CYP3A4 inhibitors",      "severity": "High",
         "description": "Marked sirolimus level elevation — TDM required"},
        {"drug": "Live vaccines",                 "severity": "Moderate",
         "description": "Immunosuppression — live vaccination contraindicated"},
    ],
    "nintedanib": [
        {"drug": "Anticoagulants",                "severity": "High",
         "description": "Bleeding risk amplification via P-gp / CYP3A4 overlap"},
        {"drug": "Pirfenidone",                   "severity": "Moderate",
         "description": "Additive hepatotoxicity signal observed in IPF trials"},
    ],
    "pirfenidone": [
        {"drug": "Fluvoxamine",                   "severity": "High",
         "description": "CYP1A2 inhibition raises pirfenidone AUC >4×"},
        {"drug": "Ciprofloxacin",                 "severity": "Moderate",
         "description": "Moderate CYP1A2 inhibition; monitor for nausea/dizziness"},
    ],
}
_GENERIC_INTERACTIONS = [
    {"drug": "CYP3A4 substrates",    "severity": "Moderate",
     "description": "Potential metabolic DDI — verify against current prescribing information"},
    {"drug": "Highly protein-bound agents", "severity": "Low",
     "description": "Displacement possible at supratherapeutic concentrations"},
]

# ── HTTP helpers ──────────────────────────────────────────────────────────────
def _get(url: str, params: dict | None = None,
         timeout: int = 10, retries: int = 3, backoff: float = 1.0) -> tuple:
    """GET with exponential back-off. Returns (json_or_None, is_fallback:bool)."""
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json(), False
            if r.status_code == 404:
                return None, True          # not found — no point retrying
        except requests.RequestException as exc:
            log.warning("GET %s attempt %d/%d: %s", url, attempt + 1, retries, exc)
        if attempt < retries - 1:
            time.sleep(backoff * (2 ** attempt))
    return None, True


def _post_gql(query: str, variables: dict,
              timeout: int = 10, retries: int = 3, backoff: float = 1.0) -> tuple:
    """POST to Open Targets GraphQL with retry."""
    for attempt in range(retries):
        try:
            r = requests.post(
                OT_GRAPHQL,
                json={"query": query, "variables": variables},
                timeout=timeout,
            )
            if r.status_code == 200:
                return r.json(), False
        except requests.RequestException as exc:
            log.warning("GraphQL attempt %d/%d: %s", attempt + 1, retries, exc)
        if attempt < retries - 1:
            time.sleep(backoff * (2 ** attempt))
    return None, True

# ── PubChem ───────────────────────────────────────────────────────────────────
def search_pubchem(drug_name: str) -> dict:
    key = f"pc:{drug_name.lower()}"
    with _lock:
        cached = _pubchem_cache.get(key)
    if cached is not None:
        return cached

    url = (
        f"{PUBCHEM_BASE}/compound/name/{quote(drug_name)}"
        "/property/MolecularFormula,MolecularWeight,CanonicalSMILES,IUPACName/JSON"
    )
    data, _ = _get(url)
    if data:
        p = data.get("PropertyTable", {}).get("Properties", [{}])[0]
        result = {
            "molecular_formula": p.get("MolecularFormula", "N/A"),
            "molecular_weight":  str(p.get("MolecularWeight", "N/A")),
            "canonical_smiles":  p.get("CanonicalSMILES", ""),
            "iupac_name":        p.get("IUPACName", "N/A"),
            "image_url":         f"{PUBCHEM_BASE}/compound/name/{quote(drug_name)}/PNG",
            "source":            "pubchem",
        }
    else:
        result = {
            "molecular_formula": "N/A",
            "molecular_weight":  "N/A",
            "canonical_smiles":  "",
            "iupac_name":        "N/A",
            "image_url":         f"{PUBCHEM_BASE}/compound/name/{quote(drug_name)}/PNG",
            "source":            "fallback",
        }

    with _lock:
        _pubchem_cache[key] = result
    return result

# ── ChEMBL ────────────────────────────────────────────────────────────────────
_CHEMBL_FALLBACK = {
    "chembl_id": None, "max_phase": 0, "mechanisms": [],
    "targets": [], "target_count": 0, "high_potency_count": 0,
    "source": "fallback",
}

def get_chembl_data(drug_name: str) -> dict:
    key = f"chembl:{drug_name.lower()}"
    with _lock:
        cached = _chembl_cache.get(key)
    if cached is not None:
        return cached

    mol_data, _ = _get(f"{CHEMBL_BASE}/molecule", params={
        "pref_name__iexact": drug_name, "format": "json", "limit": 1,
    })
    if not mol_data or not mol_data.get("molecules"):
        with _lock:
            _chembl_cache[key] = _CHEMBL_FALLBACK
        return _CHEMBL_FALLBACK

    m0        = mol_data["molecules"][0]
    chembl_id = m0.get("molecule_chembl_id")
    max_phase = int(m0.get("max_phase") or 0)

    # Mechanism of action
    mech_data, _ = _get(f"{CHEMBL_BASE}/mechanism", params={
        "molecule_chembl_id": chembl_id, "format": "json", "limit": 10,
    })
    mechanisms = []
    if mech_data:
        for m in mech_data.get("mechanisms", []):
            mechanisms.append({
                "action_type": m.get("action_type", "Unknown"),
                "target_name": m.get("target_name", "Unknown"),
                "mechanism":   m.get("mechanism_of_action", "Unknown"),
            })

    # Binding activity — limit 100 to cap per-request memory; require pChEMBL value
    act_data, _ = _get(f"{CHEMBL_BASE}/activity", params={
        "molecule_chembl_id": chembl_id, "format": "json", "limit": 100,
        "pchembl_value__isnull": False,
    })
    targets: set[str] = set()
    high_potency = 0
    if act_data:
        for act in act_data.get("activities", []):
            if act.get("target_chembl_id"):
                targets.add(act["target_chembl_id"])
            try:
                if float(act.get("pchembl_value") or 0) >= 6.0:   # ≥1 µM
                    high_potency += 1
            except (ValueError, TypeError):
                pass

    result = {
        "chembl_id":          chembl_id,
        "max_phase":          max_phase,
        "mechanisms":         mechanisms[:5],
        "targets":            list(targets)[:50],   # cap list size in cache
        "target_count":       len(targets),
        "high_potency_count": high_potency,
        "source":             "chembl",
    }
    with _lock:
        _chembl_cache[key] = result
    return result

# ── Open Targets ──────────────────────────────────────────────────────────────
_OT_QUERY = """
query DrugInfo($chemblId: String!) {
  drug(chemblId: $chemblId) {
    id
    name
    maximumClinicalTrialPhase
    indicationsCount
    indications {
      rows {
        maxPhaseForIndication
        disease { name id }
      }
    }
    linkedTargets { count }
  }
}
"""
_OT_FALLBACK = {
    "indication_count": 0, "linked_targets": 0, "max_phase_ot": 0,
    "indications": [], "source": "fallback",
}

def get_ot_data(chembl_id: str | None) -> dict:
    if not chembl_id:
        return _OT_FALLBACK

    key = f"ot:{chembl_id}"
    with _lock:
        cached = _ot_cache.get(key)
    if cached is not None:
        return cached

    data, _ = _post_gql(_OT_QUERY, {"chemblId": chembl_id})
    if data and data.get("data", {}).get("drug"):
        d    = data["data"]["drug"]
        rows = d.get("indications", {}).get("rows", [])
        result = {
            "indication_count": d.get("indicationsCount") or len(rows),
            "linked_targets":   (d.get("linkedTargets") or {}).get("count", 0),
            "max_phase_ot":     d.get("maximumClinicalTrialPhase") or 0,
            "indications":      [
                {"disease": r["disease"]["name"],
                 "phase":   r.get("maxPhaseForIndication", 0)}
                for r in rows[:5]
            ],
            "source": "open_targets",
        }
    else:
        result = dict(_OT_FALLBACK)

    with _lock:
        _ot_cache[key] = result
    return result

# ── Tanimoto (RDKit) ──────────────────────────────────────────────────────────
# IMPORTANT: Mol objects are NOT stored in any cache.
# Only primitive scores (float) are cached. This keeps memory predictable.

def _fp(smiles: str):
    """Morgan FP as bit vector, or None on any failure."""
    if not RDKIT_AVAILABLE or not smiles:
        return None
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        return rdMolDescriptors.GetMorganFingerprintAsBitVect(mol, radius=2, nBits=2048)
    except Exception:
        return None


def tanimoto_vs_references(query_smiles: str) -> float:
    """Max Tanimoto similarity of query against the known-repurposing reference set."""
    fp_q = _fp(query_smiles)
    if fp_q is None:
        return 0.0
    best = 0.0
    for smi in _REFERENCE_SMILES.values():
        fp_r = _fp(smi)
        if fp_r is None:
            continue
        try:
            sim = DataStructs.TanimotoSimilarity(fp_q, fp_r)
            if sim > best:
                best = sim
        except Exception:
            continue
    return float(best)


def tanimoto_pairwise(smi1: str, smi2: str) -> float:
    fp1, fp2 = _fp(smi1), _fp(smi2)
    if fp1 is None or fp2 is None:
        return 0.0
    try:
        return float(DataStructs.TanimotoSimilarity(fp1, fp2))
    except Exception:
        return 0.0

# ── Confidence Score ──────────────────────────────────────────────────────────
def calculate_confidence_score(drug_name: str, indication: str = "repurposing") -> dict:
    """
    Scientifically grounded heuristic (no heavy ML — safe on 512 MB).

    Component          Weight  Rationale
    ─────────────────  ──────  ────────────────────────────────────────────────
    phase_score        0.30    Clinical phase is the strongest repurposing signal
    potency_score      0.25    High pChEMBL fraction → confirmed target engagement
    tanimoto_score     0.20    Structural similarity to validated repurposed drugs
    target_richness    0.15    Log-normalised target count (polypharmacology proxy)
    ot_breadth         0.10    Open Targets indication count (existing evidence)

    All sub-scores are bounded [0, 1] before weighting.
    """
    cache_key = f"score:{drug_name.lower()}:{indication.lower()[:20]}"
    with _lock:
        cached = _score_cache.get(cache_key)
    if cached is not None:
        return cached

    mol    = search_pubchem(drug_name)
    chembl = get_chembl_data(drug_name)
    ot     = get_ot_data(chembl.get("chembl_id"))

    # 1. Phase score — normalise to [0, 1] over max clinical phase 0-4
    raw_phase   = max(int(chembl.get("max_phase", 0)),
                      int(ot.get("max_phase_ot", 0) or 0))
    phase_score = min(raw_phase / 4.0, 1.0)

    # 2. Potency score — fraction of activities with pChEMBL ≥ 6
    tc            = max(chembl.get("target_count", 0), 1)
    potency_score = min(chembl.get("high_potency_count", 0) / tc, 1.0)

    # 3. Tanimoto similarity vs known repurposed scaffolds
    tan_score = tanimoto_vs_references(mol.get("canonical_smiles", ""))

    # 4. Target richness — log10(tc+1)/log10(101) ≈ 0 for 0 targets, 1 for 100 targets
    tgt_rich = min(math.log10(tc + 1) / math.log10(101), 1.0)

    # 5. Open Targets breadth — cap at 10 indications
    ot_score = min((ot.get("indication_count", 0) or 0) / 10.0, 1.0)

    composite = (
        phase_score   * 0.30 +
        potency_score * 0.25 +
        tan_score     * 0.20 +
        tgt_rich      * 0.15 +
        ot_score      * 0.10
    )
    final = min(100, max(1, int(composite * 100)))

    all_sources = {mol["source"], chembl["source"], ot["source"]}
    if all_sources <= {"fallback"}:
        src = "fallback"
    elif "fallback" in all_sources:
        src = "partial_fallback"
    else:
        src = "live"

    result = {
        "score": final,
        "components": {
            "phase_score":    round(phase_score, 3),
            "potency_score":  round(potency_score, 3),
            "tanimoto_score": round(tan_score, 3),
            "target_richness":round(tgt_rich, 3),
            "ot_score":       round(ot_score, 3),
        },
        "raw_phase": raw_phase,
        "chembl_id": chembl.get("chembl_id"),
        "source":    src,
    }
    with _lock:
        _score_cache[cache_key] = result
    return result

# ── Clinical Trials ───────────────────────────────────────────────────────────
def search_clinical_trials(drug_name: str) -> dict:
    key = f"ct:{drug_name.lower()}"
    with _lock:
        cached = _ct_cache.get(key)
    if cached is not None:
        return cached

    data, _ = _get(CT_BASE + "/studies", params={
        "query.term": drug_name, "pageSize": 5, "sort": "Relevance",
    })
    if data:
        trials = []
        for s in data.get("studies", []):
            proto  = s.get("protocolSection", {})
            ident  = proto.get("identificationModule", {})
            status = proto.get("statusModule", {})
            spon   = proto.get("sponsorCollaboratorsModule", {})
            phases = proto.get("designModule", {}).get("phases") or ["N/A"]
            trials.append({
                "nct_id":          ident.get("nctId", "N/A"),
                "title":           ident.get("briefTitle", "N/A"),
                "phase":           ", ".join(phases),
                "status":          status.get("overallStatus", "N/A"),
                "start_date":      (status.get("startDateStruct") or {}).get("date", "N/A"),
                "completion_date": (status.get("completionDateStruct") or {}).get("date", "N/A"),
                "sponsor":         (spon.get("leadSponsor") or {}).get("name", "N/A"),
            })
        result = {"count": len(trials), "trials": trials, "source": "clinicaltrials"}
    else:
        result = {"count": 0, "trials": [], "source": "fallback"}

    with _lock:
        _ct_cache[key] = result
    return result

# ── Drug Interactions ─────────────────────────────────────────────────────────
def search_drug_interactions(drug_name: str) -> dict:
    key = f"inter:{drug_name.lower()}"
    with _lock:
        cached = _interact_cache.get(key)
    if cached is not None:
        return cached

    curated = _INTERACTIONS.get(drug_name.lower())
    result = {
        "interactions": curated if curated else _GENERIC_INTERACTIONS,
        "source":       "curated" if curated else "fallback",
    }
    with _lock:
        _interact_cache[key] = result
    return result

# ── CAS number (best-effort via PubChem synonyms) ─────────────────────────────
def get_cas_number(drug_name: str) -> str:
    key = f"cas:{drug_name.lower()}"
    with _lock:
        cached = _cas_cache.get(key)
    if cached is not None:
        return cached

    cas = "N/A"
    try:
        data, _ = _get(
            f"{PUBCHEM_BASE}/compound/name/{quote(drug_name)}/synonyms/JSON",
            timeout=8, retries=2,
        )
        if data:
            syns = (
                data.get("InformationList", {})
                    .get("Information", [{}])[0]
                    .get("Synonym", [])
            )
            for s in syns:
                if _CAS_RE.match(s):
                    cas = s
                    break
    except Exception:
        pass

    with _lock:
        _cas_cache[key] = cas
    return cas

# ── Phase label ───────────────────────────────────────────────────────────────
def _phase_label(phase) -> str:
    return {
        0: "Pre-clinical",
        1: "Phase I",
        2: "Phase II",
        3: "Phase III",
        4: "Approved / Phase IV",
    }.get(int(phase or 0), "Unknown")

# ── Full drug profile ─────────────────────────────────────────────────────────
def build_drug_profile(drug_name: str) -> dict:
    mol    = search_pubchem(drug_name)
    chembl = get_chembl_data(drug_name)
    ct     = search_clinical_trials(drug_name)
    inter  = search_drug_interactions(drug_name)
    conf   = calculate_confidence_score(drug_name)
    ot     = get_ot_data(chembl.get("chembl_id"))

    ot_ind     = [i["disease"] for i in ot.get("indications", [])]
    indication = ", ".join(ot_ind[:3]) if ot_ind else "New therapeutic use"

    mechs = chembl.get("mechanisms", [])
    mech  = mechs[0]["mechanism"] if mechs else "Mechanism under investigation"

    return {
        "name":             drug_name,
        "confidence":       conf["score"],
        "confidence_detail":conf,
        "indication":       indication,
        "mechanism":        mech,
        "mechanisms_list":  mechs,
        "molecular":        mol,
        "trials":           ct,
        "interactions":     inter["interactions"],
        "chembl_id":        chembl.get("chembl_id"),
        "max_phase":        chembl.get("max_phase", 0),
        "target_count":     chembl.get("target_count", 0),
        "source":           conf.get("source", "live"),
    }

# ── Compare profile (matches code.html column schema) ────────────────────────
def build_compare_profile(drug_name: str) -> dict:
    p   = build_drug_profile(drug_name)
    mol = p["molecular"]
    ct  = p["trials"]
    inter_list = p["interactions"]
    cas = get_cas_number(drug_name)

    return {
        "name":               drug_name,
        "cas_number":         cas,
        "clinical_phase":     _phase_label(p["max_phase"]),
        "clinical_phase_raw": p["max_phase"],
        "confidence":         p["confidence"],
        "confidence_detail":  p["confidence_detail"],
        "indication":         p["indication"],
        "mechanism":          p["mechanism"],
        "mechanisms_list":    p["mechanisms_list"],
        "molecular": {
            "formula":   mol.get("molecular_formula", "N/A"),
            "weight":    mol.get("molecular_weight", "N/A"),
            "smiles":    mol.get("canonical_smiles", ""),
            "iupac":     mol.get("iupac_name", "N/A"),
            "image_url": mol.get("image_url", ""),
        },
        "trials": {
            "count":  ct["count"],
            "trials": ct["trials"][:3],
            "source": ct.get("source", "fallback"),
        },
        "interactions": {
            "high":     [i for i in inter_list if i.get("severity") == "High"],
            "moderate": [i for i in inter_list if i.get("severity") == "Moderate"],
            "all":      inter_list,
        },
        "target_count": p["target_count"],
        "chembl_id":    p["chembl_id"],
        "source":       p["source"],
    }

# ── Mechanistic overlap (compare endpoint analysis block) ────────────────────
def compute_mechanistic_overlap(profiles: list) -> dict:
    """
    Produces:
    - Pairwise Tanimoto matrix
    - High-similarity pairs (Tanimoto > 0.4)
    - Co-administration contraindication flags
    - Polypharmacology narrative
    """
    n = len(profiles)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            if i == j:
                matrix[i][j] = 1.0
            else:
                t = tanimoto_pairwise(
                    profiles[i]["molecular"]["smiles"],
                    profiles[j]["molecular"]["smiles"],
                )
                matrix[i][j] = round(t, 3)
                matrix[j][i] = round(t, 3)

    high_sim = [
        {"pair": [profiles[i]["name"], profiles[j]["name"]],
         "tanimoto": matrix[i][j]}
        for i in range(n) for j in range(i + 1, n)
        if matrix[i][j] > 0.4
    ]

    contra_flags = []
    for i in range(n):
        for j in range(i + 1, n):
            drugs_in_j_inter = " ".join(
                x["drug"].lower() for x in profiles[j]["interactions"]["all"]
            )
            drugs_in_i_inter = " ".join(
                x["drug"].lower() for x in profiles[i]["interactions"]["all"]
            )
            if (profiles[i]["name"].lower() in drugs_in_j_inter or
                    profiles[j]["name"].lower() in drugs_in_i_inter):
                contra_flags.append({
                    "pair":     [profiles[i]["name"], profiles[j]["name"]],
                    "risk":     "Co-administration interaction flagged in curated database",
                    "severity": "High",
                    "source":   "curated",
                })

    summary = (
        "Structural similarity > 0.4 detected between at least one pair — overlapping "
        "off-target profiles are likely; monitor for additive toxicity in combination."
        if high_sim else
        "No significant structural overlap among selected candidates."
    )

    return {
        "drug_names":              [p["name"] for p in profiles],
        "tanimoto_matrix":         matrix,
        "high_similarity_pairs":   high_sim,
        "contraindication_flags":  contra_flags,
        "polypharmacology_summary":summary,
        "source":                  "live",
    }

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", cache_stats={"hits": 0, "misses": 0})


@app.route("/search", methods=["POST"])
def search():
    query = request.form.get("query", "").strip()
    if not query:
        return render_template("results.html", drugs=[], query="", cache_info=None)
    profile    = build_drug_profile(query)
    cache_info = {"last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    return render_template("results.html", drugs=[profile], query=query, cache_info=cache_info)


@app.route("/api/search", methods=["GET"])
def api_search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])
    return jsonify([build_drug_profile(query)])


@app.route("/api/compare", methods=["GET"])
def api_compare():
    """
    JSON endpoint consumed by code.html Clinical Precision Dashboard.

    GET /api/compare?drugs=Nintedanib,Pirfenidone,Sildenafil

    Response shape matches the comparison table columns in code.html:
      cas_number, clinical_phase, confidence, indication, molecular.weight, mechanism
    """
    raw   = request.args.get("drugs", "")
    names = [n.strip() for n in raw.split(",") if n.strip()][:3]
    if not names:
        return jsonify({"error": "Provide ?drugs=DrugA,DrugB", "source": "error"}), 400

    profiles = [build_compare_profile(n) for n in names]
    overlap  = compute_mechanistic_overlap(profiles)
    all_live = all(p["source"] not in ("fallback",) for p in profiles)

    return jsonify({
        "drugs":        profiles,
        "analysis":     overlap,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "source":       "live" if all_live else "partial_fallback",
    })


@app.route("/compare", methods=["GET", "POST"])
def compare():
    drug_data_list, drug_names = [], []
    if request.method == "POST":
        i = 1
        while True:
            n = request.form.get(f"compare_drug_{i}", "").strip()
            if not n:
                break
            drug_names.append(n)
            i += 1
        drug_names     = drug_names[:3]
        drug_data_list = [build_compare_profile(n) for n in drug_names]

    cache_info = {"last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    return render_template(
        "compare.html",
        drug_data_list=drug_data_list,
        drug_names=drug_names,
        cache_info=cache_info,
    )


# ── PDF generation ─────────────────────────────────────────────────────────────
@app.route("/generate_pdf", methods=["POST"])
def generate_pdf():
    payload  = request.get_json(force=True)
    filename = f"drug_repurposing_report_{int(time.time())}.pdf"
    os.makedirs("static", exist_ok=True)
    filepath = os.path.join("static", filename)

    doc    = SimpleDocTemplate(
        filepath, pagesize=letter,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=1.0  * inch, bottomMargin=0.75 * inch,
    )
    base = getSampleStyleSheet()
    S = {
        "title": ParagraphStyle("rT", parent=base["Heading1"],
                                 fontSize=20, spaceAfter=4, alignment=1),
        "sub":   ParagraphStyle("rS", parent=base["Normal"],
                                 fontSize=9, spaceAfter=3, alignment=1,
                                 textColor=colors.HexColor("#444444")),
        "h2":    ParagraphStyle("rH2", parent=base["Heading2"],
                                 fontSize=12, spaceBefore=10, spaceAfter=4,
                                 textColor=colors.HexColor("#006565")),
        "body":  ParagraphStyle("rB", parent=base["Normal"],
                                 fontSize=8.5, spaceAfter=4, leading=12),
        "src":   ParagraphStyle("rSrc", parent=base["Normal"],
                                 fontSize=7.5, textColor=colors.grey),
        "disc":  ParagraphStyle("rD", parent=base["Normal"],
                                 fontSize=7, textColor=colors.grey, leading=10),
    }

    story = []

    # ── PERMANENT ATTRIBUTION HEADER — do not alter ───────────────────────────
    story.append(Paragraph("Drug Repurposing Intelligence Report", S["title"]))
    story.append(Paragraph("Dr. Luqman Bin Fahad", S["sub"]))
    story.append(Paragraph("Doctor of Pharmacy", S["sub"]))
    # ─────────────────────────────────────────────────────────────────────────
    story.append(Paragraph(
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}  |  "
        "Clinical Precision Dashboard v2.0",
        S["sub"],
    ))
    story.append(HRFlowable(
        width="100%", thickness=1.5,
        color=colors.HexColor("#008080"), spaceAfter=14,
    ))

    teal_hdr   = colors.HexColor("#191c1e")
    white_txt  = colors.white
    row_even   = colors.HexColor("#f2f4f6")
    grid_clr   = colors.HexColor("#bdc9c8")
    sev_colors = {
        "High":     colors.HexColor("#ffdad6"),
        "Moderate": colors.HexColor("#fff8e1"),
        "Low":      colors.HexColor("#e8f5e8"),
    }

    def _base_tbl_style():
        return [
            ("FONTSIZE",      (0, 0), (-1, -1), 8.5),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("GRID",          (0, 0), (-1, -1), 0.4, grid_clr),
        ]

    for drug in payload.get("drugs", []):
        name   = drug.get("name", "Unknown")
        conf   = drug.get("confidence", "N/A")
        ind    = drug.get("indication", "N/A")
        mech   = drug.get("mechanism", "N/A")
        mol    = drug.get("molecular", {})
        trials = drug.get("trials", {})
        inter  = drug.get("interactions", [])
        src    = drug.get("source", "live")

        story.append(Paragraph(f"Drug Profile — {name}", S["h2"]))
        story.append(Paragraph(f"[Data source: {src}]", S["src"]))

        profile_rows = [
            ["Confidence Score",    f"{conf} %"],
            ["Indication",          ind],
            ["Mechanism of Action", mech],
            ["Molecular Formula",   mol.get("molecular_formula", mol.get("formula", "N/A"))],
            ["Molecular Weight",    mol.get("molecular_weight",  mol.get("weight",  "N/A"))],
        ]
        pt = Table(profile_rows, colWidths=[2.0 * inch, 4.7 * inch])
        pt.setStyle(TableStyle(_base_tbl_style() + [
            ("BACKGROUND",    (0, 0), (0, -1), colors.HexColor("#eceef0")),
            ("FONTNAME",      (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME",      (1, 0), (1, -1), "Helvetica"),
            ("ROWBACKGROUNDS",(0, 0), (-1, -1), [colors.white, row_even]),
        ]))
        story.append(pt)
        story.append(Spacer(1, 8))

        # Clinical Trials
        story.append(Paragraph("Clinical Trials", S["h2"]))
        trial_list = (trials.get("trials", []) if isinstance(trials, dict) else [])[:5]
        if trial_list:
            ct_rows = [["NCT ID", "Phase", "Status", "Sponsor"]]
            for t in trial_list:
                ct_rows.append([
                    t.get("nct_id", "N/A")[:14],
                    t.get("phase",  "N/A")[:14],
                    t.get("status", "N/A")[:18],
                    t.get("sponsor","N/A")[:22],
                ])
            ct = Table(ct_rows, colWidths=[1.5*inch, 1.2*inch, 1.7*inch, 2.3*inch])
            ct.setStyle(TableStyle(_base_tbl_style() + [
                ("BACKGROUND",    (0, 0), (-1, 0), teal_hdr),
                ("TEXTCOLOR",     (0, 0), (-1, 0), white_txt),
                ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, row_even]),
            ]))
            story.append(ct)
        else:
            story.append(Paragraph("No clinical trials on record.", S["body"]))
        story.append(Spacer(1, 8))

        # Drug Interactions
        story.append(Paragraph("Drug Interactions", S["h2"]))
        inter_list = (
            inter.get("all", inter) if isinstance(inter, dict) else inter
        )[:6]
        if inter_list:
            in_rows = [["Interacting Agent", "Severity", "Clinical Note"]]
            for ix in inter_list:
                in_rows.append([
                    ix.get("drug", "N/A"),
                    ix.get("severity", "N/A"),
                    ix.get("description", "N/A"),
                ])
            cmd = _base_tbl_style() + [
                ("BACKGROUND", (0, 0), (-1, 0), teal_hdr),
                ("TEXTCOLOR",  (0, 0), (-1, 0), white_txt),
                ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ]
            for row_idx, ix in enumerate(inter_list, start=1):
                bg = sev_colors.get(ix.get("severity", ""), colors.white)
                cmd.append(("BACKGROUND", (0, row_idx), (-1, row_idx), bg))
            it = Table(in_rows, colWidths=[1.9*inch, 1.0*inch, 3.8*inch])
            it.setStyle(TableStyle(cmd))
            story.append(it)
        else:
            story.append(Paragraph("No significant interactions recorded.", S["body"]))

        story.append(Spacer(1, 14))
        story.append(HRFlowable(
            width="100%", thickness=0.4,
            color=colors.HexColor("#bdc9c8"), spaceAfter=6,
        ))

    story.append(Spacer(1, 18))
    story.append(Paragraph(
        "DISCLAIMER: This report is produced by an AI-assisted heuristic engine for "
        "research and educational purposes only. It does not constitute clinical, "
        "diagnostic, or prescriptive advice. All findings must be independently "
        "validated by a qualified pharmacologist or clinician before application.",
        S["disc"],
    ))

    doc.build(story)
    return jsonify({"filename": filename, "source": "live"})

# ── Admin / health ────────────────────────────────────────────────────────────
@app.route("/clear_cache", methods=["POST"])
def clear_cache():
    with _lock:
        for c in (_pubchem_cache, _chembl_cache, _ct_cache, _ot_cache,
                  _score_cache, _interact_cache, _cas_cache):
            c.clear()
    return jsonify({"status": "All LRU caches cleared", "source": "live"})


@app.route("/health", methods=["GET"])
def health():
    with _lock:
        sizes = {
            "pubchem":  len(_pubchem_cache),
            "chembl":   len(_chembl_cache),
            "ct":       len(_ct_cache),
            "ot":       len(_ot_cache),
            "scores":   len(_score_cache),
            "interact": len(_interact_cache),
            "cas":      len(_cas_cache),
        }
    return jsonify({
        "status":      "ok",
        "rdkit":       RDKIT_AVAILABLE,
        "cache_sizes": sizes,
        "source":      "live",
    })


if __name__ == "__main__":
    os.makedirs("static", exist_ok=True)
    app.run(
        debug=False,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
    )
