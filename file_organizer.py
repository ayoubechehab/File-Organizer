#!/usr/bin/env python3
# ================================================================
# File Organizer v1.0.0
# ================================================================
# Description:
#   Smart file organizer powered by Google Gemini API.
#   Analyzes content (PDF, DOCX, Excel, scanned images via OCR),
#   proposes or applies meaningful filenames, and optionally organizes
#   files into a folder tree (arborescence) in French or English.
#
# This build adds:
#   - FR/EN UI + prompts + arbo output (you choose at start)
#   - Canonicalization & guardrails to avoid duplicate roots (Finance/Finances/Financial)
#   - Root cap + fold extras under Divers/Misc (FR) or Misc (EN)
#   - Robust JSON parser & safe fallbacks (no crash on malformed JSON)
#   - End sweep: move leftovers from Input → Failed (preserve subpath)
#   - Delete empty folders left in Input after the sweep
#   - Error log for all failed/leftover moves
#   - OCR fallback: if a PDF/DOCX/Image has no text, try OCR automatically before skipping
#
# Author:   Ayoub ECHEHAB
# Website:  https://www.ayoubechehab.com
# GitHub:   https://github.com/ayoubechehab
# License:  MIT
# ================================================================

import os, re, json, csv, shutil, glob, argparse, time, logging, tempfile
from datetime import datetime

import google.generativeai as genai
from PIL import Image
import pytesseract
import pypdf
import docx

# Optional, used to OCR image-only PDFs if available (requires poppler on your OS)
try:
    from pdf2image import convert_from_path as pdf2images
    HAS_PDF2IMAGE = True
except Exception:
    HAS_PDF2IMAGE = False

logging.getLogger("pypdf").setLevel(logging.ERROR)

try:
    import pandas as pd
    HAS_PANDAS = True
except Exception:
    HAS_PANDAS = False

APP_VERSION = "1.0.0"
MODEL       = "gemini-1.5-flash"
DATE_FIRST  = True
MAX_TEXT_LEN      = 16000
MIN_TEXT_CHARS    = 40
BATCH_SIZE_TITLES = 50   # shorter batches => safer JSON
PRICING = {
    "gemini-1.5-flash": {"in": 0.075, "out": 0.30},
    "gemini-1.5-pro":   {"in": 0.30,  "out": 1.20},
}
ALLOWED_EXTS = {".pdf",".docx",".xlsx",".xls",".jpg",".jpeg",".png",".tif",".tiff",".bmp",".webp"}

AUTHOR_NAME   = "Ayoub ECHEHAB"
AUTHOR_GITHUB = "https://github.com/ayoubechehab"
AUTHOR_SITE   = "https://www.ayoubechehab.com"

VERBOSE = True
REQUEST_SPACING_SECONDS = 1.1
MAX_RETRIES = 5
BACKOFF_BASE = 2.0
REMOVE_GITKEEP_AFTER_RUN = True  # remove .gitkeep files at the end of real run

# ==============================
# i18n — terminal texts (FR/EN)
# ==============================
UI_LANG = "FR"   # set at runtime from user choice

I18N = {
    "FR": {
        "app_title": "=== Organisateur de Fichiers ===",
        "ask_lang": "Langue de l'arbo et de l'interface ? (FR/EN)",
        "arbo_lang_set": "→ Langue de l'arbo définie sur",
        "ask_input": "Dossier à traiter",
        "ask_output": "Dossier de sortie",
        "ask_failed": "Dossier des échecs",
        "ask_logs": "Dossier des logs",
        "ask_dry": "Dry-Run (ne modifie pas les fichiers) ?",
        "ask_tree_dry": "→ Inclure aussi une proposition d'arborescence ?",
        "ask_tree_apply": "→ Appliquer une organisation en arborescence ?",
        "ask_reuse": "→ Réutiliser la dernière arborescence si disponible ?",
        "tree_reuse": "[ARBO] Réutilisation de l'arbo précédente",
        "tree_reuse_fail": "[ARBO] Réutilisation impossible, nouvelle cartographie demandée :",
        "tree_fresh": "[ARBO] Demande d'une arborescence fraîche à Gemini…",
        "tree_fresh_fail": "[ARBO] Échec d'analyse JSON pour l'arbo fraîche :",
        "tree_fallback_fail": "[ARBO] L'arbo de repli a aussi échoué :",
        "scan": "[SCAN {i}/{n}]",
        "skip_ext": "  └─ IGNORÉ (extension non supportée)",
        "extracting": "  └─ Extraction du texte…",
        "extract_err": "  └─ ERREUR d'extraction :",
        "ocr_try": "  └─ Aucun texte détecté, tentative OCR…",
        "ocr_err": "  └─ ERREUR OCR :",
        "skip_short": "  └─ IGNORÉ (texte insuffisant)",
        "send_title": "  └─ Envoi à Gemini pour titre…",
        "proposed": "  └─ Proposé :",
        "renamed": "  └─ Renommé →",
        "err_llm": "  └─ ERREUR LLM :",
        "rate_limit": "[LIMITE] Attente {s:.1f}s avant retry {a}/{m}…",
        "summary_dry": "===== RÉSUMÉ (dry-run) =====",
        "summary": "===== RÉSUMÉ =====",
        "tokens_in": "Jetons ENTRÉE",
        "tokens_out": "Jetons SORTIE",
        "est_cost": "Coût estimé",
        "logs_folder": "Dossier des logs",
        "saved_state": "État sauvegardé",
        "apply_now": "\nAppliquer ces propositions maintenant (sans API supplémentaire) ?",
        "applied": "Appliqué ✅",
        "files_processed": "Fichiers traités",
        "errors_moved": "Erreurs déplacées vers",
        "done": "Terminé ✨",
        "pdf2image_hint": "  └─ Conseil: pour OCR des PDFs images, installez poppler + pdf2image."
    },
    "EN": {
        "app_title": "=== File Organizer ===",
        "ask_lang": "Arbo & interface language? (FR/EN)",
        "arbo_lang_set": "→ Arbo language set to",
        "ask_input": "Folder to process",
        "ask_output": "Output folder",
        "ask_failed": "Failed folder",
        "ask_logs": "Logs folder",
        "ask_dry": "Dry-Run (do not modify files)?",
        "ask_tree_dry": "→ Include folder tree proposal too?",
        "ask_tree_apply": "→ Apply folder tree organization?",
        "ask_reuse": "→ Reuse last folder tree if available?",
        "tree_reuse": "[TREE] Reusing last folder tree",
        "tree_reuse_fail": "[TREE] Reuse failed, requesting new mapping:",
        "tree_fresh": "[TREE] Requesting fresh folder tree mapping from Gemini...",
        "tree_fresh_fail": "[TREE] Fresh tree failed to parse JSON:",
        "tree_fallback_fail": "[TREE] Fallback fresh mapping also failed:",
        "scan": "[SCAN {i}/{n}]",
        "skip_ext": "  └─ SKIPPED (unsupported extension)",
        "extracting": "  └─ Extracting text...",
        "extract_err": "  └─ ERROR extracting:",
        "ocr_try": "  └─ No text detected, trying OCR...",
        "ocr_err": "  └─ OCR ERROR:",
        "skip_short": "  └─ SKIPPED (not enough text)",
        "send_title": "  └─ Sending to Gemini for title...",
        "proposed": "  └─ Proposed:",
        "renamed": "  └─ Renamed →",
        "err_llm": "  └─ LLM ERROR:",
        "rate_limit": "[RATE-LIMIT] Waiting {s:.1f}s before retry {a}/{m}...",
        "summary_dry": "===== SUMMARY (dry-run) =====",
        "summary": "===== SUMMARY =====",
        "tokens_in": "Tokens IN",
        "tokens_out": "Tokens OUT",
        "est_cost": "Estimated cost",
        "logs_folder": "Logs folder",
        "saved_state": "Saved state",
        "apply_now": "\nApply these proposals now (no extra API)?",
        "applied": "Applied ✅",
        "files_processed": "Files processed",
        "errors_moved": "Errors moved to",
        "done": "Done ✨",
        "pdf2image_hint": "  └─ Tip: to OCR image-only PDFs, install poppler + pdf2image."
    },
}

def L(key, **fmt):
    s = I18N[UI_LANG].get(key, key)
    return s.format(**fmt) if fmt else s

# =========================================================
# Robust JSON parsing
# =========================================================
def _strip_code_fences(s: str) -> str:
    s = s.strip()
    s = s.replace("```json", "").replace("```", "")
    return s.strip()

def _between_braces(s: str) -> str | None:
    i = s.find("{")
    j = s.rfind("}")
    if i != -1 and j != -1 and j > i:
        return s[i:j+1]
    return None

def _json_soft_fixes(s: str) -> str:
    s = s.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    s = re.sub(r",\s*([}\]])", r"\1", s)
    s = re.sub(r"//.*?$", "", s, flags=re.MULTILINE)
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.DOTALL)
    return s.strip()

def safe_json_loads(raw_text: str, logs_dir: str, tag: str) -> dict:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    text = _strip_code_fences(raw_text)
    block = _between_braces(text) or text
    try:
        return json.loads(block)
    except Exception as e1:
        try:
            os.makedirs(logs_dir, exist_ok=True)
            raw_path = os.path.join(logs_dir, f"llm_raw_{tag}_{ts}.txt")
            with open(raw_path, "w", encoding="utf-8") as f:
                f.write(raw_text)
        except Exception:
            pass
        try:
            fixed = _json_soft_fixes(block)
            return json.loads(fixed)
        except Exception:
            raise e1

# ==========================================
# Canonicalization & guardrails (FR / EN)
# ==========================================
ARBO_LANG = "FR"  # set at runtime
LIMIT_NEW_SUBFOLDERS = 4
LIMIT_ROOTS = 12

SUGGESTED_ROOTS_FR = [
    "Archives","Administratif","Finances","Assurances","Études","Professionnel",
    "Personnel","Logiciels","Médias","Achats","Marketing Digital","Travail","Divers"
]
SUGGESTED_ROOTS_EN = [
    "Archive","Administration","Finance","Insurance","Studies","Professional",
    "Personal","Software","Media","Purchases","Digital Marketing","Work","Misc"
]

ALIAS_MAP_FR = {
    "finance":"Finances","finances":"Finances","financial":"Finances",
    "administration":"Administratif","administrative":"Administratif","administratif":"Administratif",
    "professional":"Professionnel","professionnel":"Professionnel",
    "personal":"Personnel","personnel":"Personnel",
    "education":"Études","etudes":"Études","etude":"Études","études":"Études",
    "releves de notes":"Relevés de notes","relevés de notes":"Relevés de notes","relevés":"Relevés de notes",
    "documents fiscaux":"Impôts","fiscalite":"Impôts","impots":"Impôts","impôts":"Impôts",
    "bank":"Banque","documents bancaires":"Banque","banque":"Banque",
    "autres":"Divers","other":"Divers","non classe":"Divers","non classé":"Divers","documents divers":"Divers",
    "applications":"Logiciels","application":"Logiciels","software":"Logiciels",
    "media":"Médias","medias":"Médias","videos":"Vidéos","video":"Vidéos",
    "travail":"Travail","work":"Travail","entreprise":"Travail",
}
ALIAS_MAP_EN = {
    "finances":"Finance","financial":"Finance",
    "administratif":"Administration","administration":"Administration",
    "professionnel":"Professional","professional":"Professional",
    "personnel":"Personal","personal":"Personal",
    "education":"Studies","etudes":"Studies","études":"Studies",
    "releves de notes":"Transcripts","relevés de notes":"Transcripts",
    "documents fiscaux":"Tax","impots":"Tax","impôts":"Tax","taxes":"Tax",
    "banque":"Bank","documents bancaires":"Bank","bank":"Bank",
    "autres":"Misc","other":"Misc","non classe":"Misc","non classé":"Misc","documents divers":"Misc",
    "applications":"Software","logiciels":"Software",
    "media":"Media","medias":"Media","videos":"Videos",
    "travail":"Work","entreprise":"Work",
}

def get_alias_map():
    return ALIAS_MAP_FR if ARBO_LANG.upper()=="FR" else ALIAS_MAP_EN

def get_suggested_roots():
    return SUGGESTED_ROOTS_FR if ARBO_LANG.upper()=="FR" else SUGGESTED_ROOTS_EN

def _title_norm(s: str) -> str:
    specials = {"cv":"CV","crous":"CROUS","urssaf":"URSSAF"}
    low = s.strip().lower()
    if low in specials: return specials[low]
    return " ".join(w.capitalize() for w in low.split())

def canon_label(s: str) -> str:
    if not s: return s
    m = get_alias_map()
    key = s.strip().lower()
    if key in m: return m[key]
    s2 = _title_norm(s)
    if s2.lower() in m: return m[s2.lower()]
    return s2

def canon_path(path: str) -> str:
    parts = [p for p in (path or "").split("/") if p]
    parts = [canon_label(p) for p in parts]
    return "/".join(parts)

def canon_plan_multilang(plan: dict) -> dict:
    if not plan: return plan
    new_tree = {}
    for cat, subs in (plan.get("tree") or {}).items():
        ccat = canon_label(cat)
        new_tree.setdefault(ccat, [])
        for s in subs or []:
            cs = canon_label(s)
            if cs not in new_tree[ccat]: new_tree[ccat].append(cs)
    new_map = {}
    for fname, dest in (plan.get("map") or {}).items():
        cpath = canon_path(dest)
        new_map[fname] = cpath
        if cpath:
            parts = cpath.split("/")
            if parts:
                root = canon_label(parts[0])
                new_tree.setdefault(root, [])
                for sub in parts[1:]:
                    if sub and sub not in new_tree[root]:
                        new_tree[root].append(sub)
    return {
        "tree": {k: sorted(v) for k, v in new_tree.items()},
        "map": new_map,
        "rules": list(dict.fromkeys(plan.get("rules", []))),
        "notes": plan.get("notes", "")
    }

def enforce_root_cap(plan: dict, max_roots: int) -> dict:
    if not plan: return plan
    roots = list((plan.get("tree") or {}).keys())
    if len(roots) <= max_roots:
        return plan
    suggested = set(get_suggested_roots())
    keep = [r for r in roots if r in suggested]
    extra = [r for r in roots if r not in suggested]
    if len(keep) >= max_roots:
        fold_list = [r for r in roots if r not in keep]
    else:
        fold_slots = max_roots - len(keep)
        keep += extra[:max(0, fold_slots)]
        fold_list = extra[max(0, fold_slots):]
    if not fold_list:
        return plan
    divers = "Divers" if ARBO_LANG.upper()=="FR" else "Misc"
    tree = dict(plan.get("tree", {}))
    tree.setdefault(divers, [])
    new_map = {}
    for fname, dest in (plan.get("map") or {}).items():
        if not dest:
            new_map[fname] = dest
            continue
        parts = [p for p in dest.split("/") if p]
        if parts and parts[0] in fold_list:
            new_map[fname] = f"{divers}/{parts[0]}" + ("/" + "/".join(parts[1:]) if len(parts) > 1 else "")
            if parts[0] not in tree[divers]:
                tree[divers].append(parts[0])
        else:
            new_map[fname] = dest
    for r in fold_list:
        tree.pop(r, None)
    return {"tree": {k: sorted(v) for k, v in tree.items()}, "map": new_map, "rules": plan.get("rules", []), "notes": plan.get("notes", "")}

# ==========================================
# Helper I/O
# ==========================================
def vprint(*a, **kw):
    if VERBOSE:
        print(*a, **kw)

def print_author_footer():
    print(f"\n— File Organizer v{APP_VERSION}")
    print("  Made by:", AUTHOR_NAME)
    print("  GitHub :", AUTHOR_GITHUB)
    print("  Website:", AUTHOR_SITE)

def get_api_key(cli):
    if cli: return cli.strip()
    env = os.environ.get("GEMINI_API_KEY")
    if env: return env.strip()
    key_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_key.txt")
    if os.path.isfile(key_path):
        with open(key_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    raise RuntimeError("No API key found. Put your Gemini key in api_key.txt, or pass --api, or set GEMINI_API_KEY.")

def ask(p, d=None):
    if d is not None:
        s = input(f"{p} [{d}]: ").strip()
        return s or d
    return input(f"{p}: ").strip()

def yn(p, default_yes=True):
    d = "Y/n" if default_yes else "y/N"
    s = input(f"{p} ({d}): ").strip().lower()
    if not s: return default_yes
    return s in {"y", "yes", "o", "oui"}

def write_table_any(path_base, rows):
    if not rows:
        csv_path = path_base + ".csv"
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["filename","status","reason"])
        return csv_path
    if HAS_PANDAS:
        df = pd.DataFrame(rows)
        xlsx = path_base + ".xlsx"
        os.makedirs(os.path.dirname(xlsx), exist_ok=True)
        df.to_excel(xlsx, index=False)
        return xlsx
    else:
        csv_path = path_base + ".csv"
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            header = list(rows[0].keys())
            w.writerow(header)
            for r in rows:
                w.writerow([r.get(k,"") for k in header])
        return csv_path

def write_summary_txt(path, info_lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(info_lines))

def clean_desc(s):
    s = "".join(c for c in s if c.isalnum() or c in " -_").strip()
    return re.sub(r"\s+", " ", s)

def build_new_name(orig, desc, date):
    ext = os.path.splitext(orig)[1]
    desc = clean_desc(desc) or "Document"
    if DATE_FIRST and date:
        return f"{date}_{desc}{ext}"
    elif date:
        return f"{desc}_{date}{ext}"
    else:
        return f"{desc}{ext}"

def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

def find_latest_dryrun_state(log_dir):
    files = sorted(glob.glob(os.path.join(log_dir, "dryrun_state_*.json")))
    return files[-1] if files else None

def save_arbo_snapshot(plan, log_dir, run_ts):
    if not plan:
        return None
    os.makedirs(log_dir, exist_ok=True)
    hist_dir = os.path.join(log_dir, "arbo_history")
    os.makedirs(hist_dir, exist_ok=True)
    last_path = os.path.join(log_dir, "arbo_last.json")
    hist_path = os.path.join(hist_dir, f"arbo_{run_ts}.json")
    with open(last_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    with open(hist_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    return last_path

def load_last_arbo(log_dir):
    p = os.path.join(log_dir, "arbo_last.json")
    if os.path.isfile(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None

# ==========================================
# Gemini helpers
# ==========================================
def configure_genai(key):
    genai.configure(api_key=key)
    return genai.GenerativeModel(MODEL)

def _gen_content_with_retry(model, prompt):
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            time.sleep(REQUEST_SPACING_SECONDS)
            return model.generate_content(prompt)
        except Exception as e:
            last_err = e
            msg = str(e)
            if "429" in msg or "ResourceExhausted" in msg or "quota" in msg.lower():
                sleep_s = (BACKOFF_BASE ** (attempt - 1))
                vprint(L("rate_limit", s=sleep_s, a=attempt, m=MAX_RETRIES))
                time.sleep(sleep_s)
                continue
            break
    raise last_err

def ask_gemini_title(model, text, filename, logs_dir):
    prompt_fr = """
Vous travaillez en français. Détectez la langue du document et proposez un titre concis.

Règles:
- Si ANGLAIS → "lang":"en" et "resume" en ANGLAIS
- Si ARABE → "lang":"ar" mais "resume" en FRANÇAIS
- Si FRANÇAIS → "lang":"fr" et "resume" en FRANÇAIS
- Sinon → "lang":"other" et "resume" en FRANÇAIS

Retournez UNIQUEMENT un objet JSON valide (pas de Markdown/texte). Commencez par "{" et terminez par "}".

Schéma:
{"lang":"fr|en|ar|other","resume":"titre court","date":"YYYY-MM-DD" ou null}
""".strip()

    prompt_en = """
You work in English. Detect the document language and create a concise title.

Rules:
- If ENGLISH → "lang":"en" and "resume" in ENGLISH
- If ARABIC → "lang":"ar" but "resume" in FRENCH
- If FRENCH → "lang":"fr" and "resume" in FRENCH
- Else → "lang":"other" and "resume" in FRENCH

Return ONLY a single valid JSON object (no Markdown, no extra text). Start with "{" and end with "}".

Schema:
{"lang":"fr|en|ar|other","resume":"short title","date":"YYYY-MM-DD" or null}
""".strip()

    full = (prompt_fr if UI_LANG=="FR" else prompt_en) + f"\n\nText from '{filename}':\n---\n{text[:MAX_TEXT_LEN]}\n---"
    resp = _gen_content_with_retry(model, full)
    data = safe_json_loads(resp.text, logs_dir=logs_dir, tag="title")
    if not data.get("resume"):
        data["resume"] = "Document"
    tin = getattr(getattr(resp, "usage_metadata", None), "prompt_token_count", 0) or 0
    tout = getattr(getattr(resp, "usage_metadata", None), "candidates_token_count", 0) or 0
    return data, tin, tout

def build_tree_prompt_header():
    lang_word = "FRANÇAIS" if ARBO_LANG.upper()=="FR" else "ENGLISH"
    roots = json.dumps(get_suggested_roots(), ensure_ascii=False, indent=2)
    limit_new = LIMIT_NEW_SUBFOLDERS
    limit_roots = LIMIT_ROOTS
    return f"""You are an information architect. You must return a CLEAN {lang_word} folder structure.

HARD RULES:
- Language: {lang_word} ONLY for all folder names (accents if French).
- Avoid synonyms or duplicates (normalize to a single canonical label).
- Root categories MUST NOT exceed {limit_roots}. Prefer these ROOTS (soft guardrails; do not invent near-duplicates):
{roots}
- Map EVERY file to exactly one path "Category/Sub[/Sub2]".
- Create NEW subfolders ONLY when no reasonable existing folder fits (keep additions minimal; ~{limit_new} additions for this batch).
- Use short, meaningful names (no dates, no filenames).
- Return ONLY a single valid JSON object (no Markdown/comments). Start with "{{" and end with "}}".

JSON Schema:
{{
  "tree": {{ "Category": ["Sub1","Sub2", ...], ... }},
  "map":  {{ "File.ext": "Category/Sub[/Sub2]", ... }},
  "rules": ["short guidance points"],
  "notes": "optional notes"
}}
"""

def ask_gemini_tree(model, titles_pairs, logs_dir):
    agg = {"tree":{}, "map":{}, "rules":[], "notes":""}
    total_in = total_out = 0
    for batch in chunks(titles_pairs, BATCH_SIZE_TITLES):
        listing = "\n".join([f"- {t}" for _, t in batch])
        prompt = build_tree_prompt_header() + "\nFILES:\n" + listing
        resp = _gen_content_with_retry(model, prompt)
        tin  = getattr(getattr(resp, "usage_metadata", None), "prompt_token_count", 0) or 0
        tout = getattr(getattr(resp, "usage_metadata", None), "candidates_token_count", 0) or 0
        total_in  += tin
        total_out += tout
        data = safe_json_loads(resp.text, logs_dir=logs_dir, tag="tree")
        data = canon_plan_multilang(data)
        for cat, subs in data.get("tree", {}).items():
            agg["tree"].setdefault(cat, [])
            agg["tree"][cat] = list(dict.fromkeys(agg["tree"][cat] + (subs or [])))
        agg["map"].update(data.get("map", {}))
        agg["rules"].extend(data.get("rules", []))
        note = (data.get("notes") or "").strip()
        if note:
            agg["notes"] += ("\n" + note if agg["notes"] else note)
    agg["rules"] = list(dict.fromkeys([r.strip() for r in agg["rules"] if r.strip()]))
    agg = enforce_root_cap(agg, LIMIT_ROOTS)
    return agg, total_in, total_out

def ask_gemini_map_with_existing_tree(model, titles_pairs, existing_plan, logs_dir):
    existing_tree = existing_plan.get("tree", {})
    lang_word = "FRANÇAIS" if ARBO_LANG.upper()=="FR" else "ENGLISH"
    roots = json.dumps(get_suggested_roots(), ensure_ascii=False, indent=2)
    prompt = f"""
You are an information architect. You are given an EXISTING {lang_word} folder tree and a list of FILE NAMES (already renamed).
Your job:
1) Map each file into the MOST appropriate existing path. Language: {lang_word} ONLY.
2) ONLY if no fit is reasonable, propose a MINIMAL new subfolder under the closest category (keep additions minimal; ~{LIMIT_NEW_SUBFOLDERS} for this batch).
3) Avoid synonyms and duplicates (normalize to a single canonical label).
4) Prefer these ROOTS when relevant (soft guardrails; do not invent near-duplicates):
{roots}
5) Use short paths like "Category/Sub[/Sub2]".

Return ONLY a single valid JSON object. Start with "{{" and end with "}}".

Schema:
{{
  "map": {{ "File.ext": "Category/Sub", ... }},
  "tree_additions": {{ "Category": ["NewSub", ...], ... }}
}}

EXISTING_TREE (keep coherent; do not invent alternate root names):
{json.dumps(existing_tree, ensure_ascii=False, indent=2)}

FILES:
""" + "\n".join([f"- {t}" for _, t in titles_pairs])
    resp = _gen_content_with_retry(model, prompt)
    tin  = getattr(getattr(resp, "usage_metadata", None), "prompt_token_count", 0) or 0
    tout = getattr(getattr(resp, "usage_metadata", None), "candidates_token_count", 0) or 0
    data = safe_json_loads(resp.text, logs_dir=logs_dir, tag="reuse_map")
    if "map" in data:
        data["map"] = {k: canon_path(v) for k, v in (data.get("map") or {}).items()}
    if "tree_additions" in data:
        data["tree_additions"] = {canon_label(k): [canon_label(x) for x in (v or [])]
                                  for k, v in (data.get("tree_additions") or {}).items()}
    return data, tin, tout

# ==========================================
# File operations
# ==========================================
def move_with_collision_avoid(src, dst_dir):
    os.makedirs(dst_dir, exist_ok=True)
    base = os.path.basename(src)
    dst  = os.path.join(dst_dir, base)
    if os.path.exists(dst):
        n, e = os.path.splitext(base)
        i = 2
        while os.path.exists(os.path.join(dst_dir, f"{n} ({i}){e}")):
            i += 1
        dst = os.path.join(dst_dir, f"{n} ({i}){e}")
    shutil.move(src, dst)
    return dst

def move_preserve_subpath(src, input_dir, failed_dir):
    """Move src to Failed, preserving relative subpath from input_dir."""
    try:
        rel = os.path.relpath(src, input_dir)
    except Exception:
        rel = os.path.basename(src)
    rel_dir = os.path.dirname(rel)
    dst_dir = os.path.join(failed_dir, rel_dir) if rel_dir else failed_dir
    return move_with_collision_avoid(src, dst_dir)

def delete_empty_dirs(root_dir):
    # Walk bottom-up and remove empty directories
    for r, dirs, files in os.walk(root_dir, topdown=False):
        if not files and not dirs:
            try:
                os.rmdir(r)
            except Exception:
                pass

def sweep_input_to_failed(input_dir, failed_dir, log_rows):
    """Move any leftover files in Input to Failed, preserve subpath, then delete empty folders."""
    os.makedirs(failed_dir, exist_ok=True)
    for root, _, files in os.walk(input_dir):
        for fn in files:
            if fn.lower() == ".gitkeep":
                continue
            src = os.path.join(root, fn)
            try:
                move_preserve_subpath(src, input_dir, failed_dir)
                log_rows.append({"filename": os.path.relpath(src, input_dir), "status": "MOVED_TO_FAILED", "reason": "Leftover in Input at end"})
            except Exception as e:
                log_rows.append({"filename": os.path.relpath(src, input_dir), "status": "ERROR", "reason": f"Final sweep move fail: {e}"})
    delete_empty_dirs(input_dir)

# =======================
# Text extraction + OCR
# =======================
def extract_text(path):
    ext = os.path.splitext(path)[1].lower()
    txt = ""
    try:
        if ext == ".pdf":
            with open(path, "rb") as f:
                reader = pypdf.PdfReader(f)
                txt = "".join([p.extract_text() or "" for p in reader.pages])
            if not txt.strip():
                # try OCR for image-only PDF
                vprint(I18N[UI_LANG]["ocr_try"])
                if HAS_PDF2IMAGE:
                    try:
                        images = pdf2images(path)
                        buf = []
                        for im in images:
                            try:
                                buf.append(pytesseract.image_to_string(im, lang="fra"))
                            except Exception:
                                buf.append(pytesseract.image_to_string(im))
                        txt = "\n".join(buf)
                    except Exception as e:
                        vprint(I18N[UI_LANG]["ocr_err"] + f" {e}")
                else:
                    vprint(I18N[UI_LANG]["pdf2image_hint"])
        elif ext == ".docx":
            d = docx.Document(path)
            txt = "\n".join(p.text for p in d.paragraphs if p.text.strip())
            if not txt.strip():
                # try OCR on embedded images
                vprint(I18N[UI_LANG]["ocr_try"])
                try:
                    rels = d.part._rels
                    buf = []
                    for r in rels:
                        rel = rels[r]
                        if "image" in rel.target_ref or rel.target_part.content_type.startswith("image/"):
                            img_blob = rel.target_part.blob
                            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                                tmp.write(img_blob)
                                tmp.flush()
                                try:
                                    buf.append(pytesseract.image_to_string(Image.open(tmp.name), lang="fra"))
                                except Exception:
                                    buf.append(pytesseract.image_to_string(Image.open(tmp.name)))
                            os.unlink(tmp.name)
                    if buf:
                        txt = "\n".join(buf)
                except Exception as e:
                    vprint(I18N[UI_LANG]["ocr_err"] + f" {e}")
        elif ext in [".xlsx",".xls"] and HAS_PANDAS:
            xls = pd.read_excel(path, sheet_name=None, header=None, dtype=str)
            cells = []
            for _, df in xls.items():
                cells.extend([str(v) for v in df.fillna("").values.flatten().tolist() if str(v).strip()])
            txt = "\n".join(cells)
        elif ext in [".jpg",".jpeg",".png",".tif",".tiff",".bmp",".webp"]:
            try:
                txt = pytesseract.image_to_string(Image.open(path), lang="fra")
            except Exception:
                txt = pytesseract.image_to_string(Image.open(path))
        return (txt or "").strip()
    except Exception as e:
        return f"__EXTRACT_ERROR__: {e}"

# ===============
# Phase 1 (scan)
# ===============
def phase1(model, input_dir, dry_run, logs_dir):
    titles_pairs = []
    tok_in = tok_out = 0
    skipped = []
    proposals = []
    total = 0
    for r0, _, f0 in os.walk(input_dir):
        total += len([x for x in f0 if x.lower() != ".gitkeep"])
    i = 0
    for r, _, files in os.walk(input_dir):
        for fn in files:
            if fn.lower() == ".gitkeep":
                continue
            i += 1
            path = os.path.join(r, fn)
            ext  = os.path.splitext(fn)[1].lower()
            vprint(f"{L('scan', i=i, n=total)} {fn}")
            if ext not in ALLOWED_EXTS:
                vprint(f"{L('skip_ext')} ({ext})")
                skipped.append({"filename":fn,"status":"SKIPPED","reason":f"Extension {ext}","fullpath":path})
                continue
            vprint(L("extracting"))
            text = extract_text(path)
            if text.startswith("__EXTRACT_ERROR__"):
                vprint(f"{L('extract_err')} {text}")
                skipped.append({"filename":fn,"status":"ERROR","reason":text,"fullpath":path})
                continue
            if len(text) < MIN_TEXT_CHARS:
                vprint(L("skip_short"))
                skipped.append({"filename":fn,"status":"SKIPPED","reason":"Not enough text","fullpath":path})
                continue
            try:
                vprint(L("send_title"))
                data, tin, tout = ask_gemini_title(model, text, fn, logs_dir=logs_dir)
                tok_in  += tin
                tok_out += tout
                desc     = data.get("resume") or "Document"
                date     = data.get("date")
                proposed = build_new_name(fn, desc, date)
                vprint(f"{L('proposed')} {proposed}")
                if dry_run:
                    proposals.append({"file":fn,"proposed_name":proposed,"lang":data.get("lang",""),
                                      "summary":desc,"date":date or "","current_path":path})
                    titles_pairs.append((path, proposed))
                else:
                    new_path = os.path.join(r, proposed)
                    if os.path.exists(new_path) and os.path.abspath(new_path)!=os.path.abspath(path):
                        base,ext2=os.path.splitext(proposed); k=2
                        while os.path.exists(os.path.join(r,f"{base} ({k}){ext2}")): k+=1
                        new_path=os.path.join(r,f"{base} ({k}){ext2}")
                    os.rename(path, new_path)
                    vprint(f"{L('renamed')} {os.path.basename(new_path)}")
                    titles_pairs.append((new_path, os.path.basename(new_path)))
            except Exception as e:
                vprint(f"{L('err_llm')} {e}")
                skipped.append({"filename":fn,"status":"ERROR","reason":f"LLM error {e}","fullpath":path})
    return titles_pairs, tok_in, tok_out, skipped, proposals

# ==============================
# Moves (flat / by tree) + logs
# ==============================
def move_flat(titles_pairs, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    for src, base in titles_pairs:
        dst = os.path.join(out_dir, base)
        if os.path.exists(dst):
            n, e = os.path.splitext(base); i=2
            while os.path.exists(os.path.join(out_dir,f"{n} ({i}){e}")): i+=1
            dst = os.path.join(out_dir,f"{n} ({i}){e}")
        shutil.move(src, dst)

def apply_tree(plan, titles_pairs, out_dir, failed_dir, input_dir, log_rows):
    os.makedirs(out_dir, exist_ok=True); os.makedirs(failed_dir, exist_ok=True)
    name_to_path = {os.path.basename(p): p for p,_ in titles_pairs}
    mapped = plan.get("map",{}) or {}
    for name,rel in mapped.items():
        src = name_to_path.get(name)
        if not src:
            log_rows.append({"filename":name,"status":"ERROR","reason":"Missing"}); continue
        parts=[p for p in (rel or "").split("/") if p]
        dst_dir=os.path.join(out_dir,*parts) if parts else out_dir
        os.makedirs(dst_dir,exist_ok=True)
        dst=os.path.join(dst_dir,name)
        try:
            shutil.move(src,dst)
        except Exception as e:
            try:
                move_preserve_subpath(src, input_dir, failed_dir)
                log_rows.append({"filename":name,"status":"ERROR","reason":f"Move fail {e}"})
            except Exception as e2:
                log_rows.append({"filename":name,"status":"ERROR","reason":f"Move+fail fail: {e2}"})
    # Unmapped still present → move to Failed preserving subpath
    for name, src in list(name_to_path.items()):
        if os.path.exists(src):
            try:
                move_preserve_subpath(src, input_dir, failed_dir)
                log_rows.append({"filename":os.path.basename(src),"status":"MOVED_TO_FAILED","reason":"Unmapped in plan"})
            except Exception as e:
                log_rows.append({"filename":os.path.basename(src),"status":"ERROR","reason":f"Unmapped move fail: {e}"})

def save_dryrun(log_dir, ts, props, plan, errors):
    state={"timestamp":ts,"proposals":props,"plan":plan}
    sp=os.path.join(log_dir,f"dryrun_state_{ts}.json"); os.makedirs(log_dir,exist_ok=True)
    with open(sp,"w",encoding="utf-8") as f: json.dump(state,f,ensure_ascii=False,indent=2)
    write_table_any(os.path.join(log_dir,f"errors_{ts}"),errors)
    write_table_any(os.path.join(log_dir,f"rename_proposals_{ts}"),props)
    if plan: write_table_any(os.path.join(log_dir,f"arbo_mapping_{ts}"),[{"file":n,"dest":d} for n,d in plan.get("map",{}).items()])
    return sp

def apply_dryrun(sp,out_dir,failed_dir,log_rows,input_dir):
    with open(sp,"r",encoding="utf-8") as f: state=json.load(f)
    props,plan=state.get("proposals",[]),state.get("plan")
    titles_pairs=[]
    for p in props:
        src=p["current_path"]; newname=p["proposed_name"]
        if not os.path.isfile(src): log_rows.append({"filename":os.path.basename(src),"status":"ERROR","reason":"Not found"}); continue
        dst=os.path.join(os.path.dirname(src),newname)
        if os.path.exists(dst):
            n,e=os.path.splitext(newname); i=2
            while os.path.exists(os.path.join(os.path.dirname(src),f"{n} ({i}){e}")): i+=1
            dst=os.path.join(os.path.dirname(src),f"{n} ({i}){e}")
        try: os.rename(src,dst); titles_pairs.append((dst,os.path.basename(dst)))
        except Exception: log_rows.append({"filename":newname,"status":"ERROR","reason":"Rename fail"})
    if plan: apply_tree(plan,titles_pairs,out_dir,failed_dir,input_dir,log_rows)
    else: move_flat(titles_pairs,out_dir)

# =======================
# Interactive CLI
# =======================
def interactive_inputs():
    global UI_LANG, ARBO_LANG
    print(L("app_title"))
    # ask in a language-neutral way first time
    lang_choice = ask(I18N["EN"]["ask_lang"] if UI_LANG=="EN" else I18N["FR"]["ask_lang"], "FR").strip().upper()
    UI_LANG = "FR" if lang_choice not in {"FR","EN"} else lang_choice
    ARBO_LANG = UI_LANG
    print(f"{L('arbo_lang_set')} {ARBO_LANG}")

    inp  = ask(L("ask_input"), "./Input")
    out  = ask(L("ask_output"), "./Output")
    fail = ask(L("ask_failed"), "./Failed")
    logs = ask(L("ask_logs"), "./Logs")
    os.makedirs(inp, exist_ok=True); os.makedirs(out, exist_ok=True); os.makedirs(fail, exist_ok=True); os.makedirs(logs, exist_ok=True)

    dry = yn(L("ask_dry"), True)
    if dry:
        arbo  = yn(L("ask_tree_dry"), False)
        reuse = False
    else:
        arbo  = yn(L("ask_tree_apply"), False)
        reuse = False
        if arbo:
            reuse = yn(L("ask_reuse"), True)
            if not reuse:
                vprint(L("tree_fresh"))
    return {"input_dir":inp,"output_dir":out,"failed_dir":fail,"log_dir":logs,"dry_run":dry,"arbo":arbo,"reuse_arbo":reuse if not dry else False}

# =======================
# Main
# =======================
def main():
    ap = argparse.ArgumentParser(description="File Organizer — content-aware rename & optional folder organization")
    ap.add_argument("--api"); args = ap.parse_args()
    api = get_api_key(args.api); model = configure_genai(api)

    opts=interactive_inputs(); ts=datetime.now().strftime("%Y%m%d_%H%M%S"); log_rows=[]
    titles_pairs,tin1,tout1,errors,proposals=phase1(model,opts["input_dir"],opts["dry_run"],logs_dir=opts["log_dir"])

    plan,tin2,tout2=(None,0,0)
    if opts["arbo"] and titles_pairs:
        if not opts["dry_run"] and opts.get("reuse_arbo"):
            last=load_last_arbo(opts["log_dir"])
            if last:
                vprint(L("tree_reuse"))
                try:
                    mapping_out,tin_m,tout_m=ask_gemini_map_with_existing_tree(model,titles_pairs,last,logs_dir=opts["log_dir"])
                    tin2+=tin_m; tout2+=tout_m
                    fused_tree=dict(last.get("tree",{}))
                    for cat,subs in (mapping_out.get("tree_additions",{}) or {}).items():
                        fused_tree.setdefault(cat,[]); fused_tree[cat]=list(dict.fromkeys(fused_tree[cat]+(subs or [])))
                    fused_map=dict(last.get("map",{})); fused_map.update(mapping_out.get("map",{}) or {})
                    plan={"tree":fused_tree,"map":fused_map,"rules":last.get("rules",[]),"notes":last.get("notes","")}
                    plan=canon_plan_multilang(plan); plan=enforce_root_cap(plan,LIMIT_ROOTS)
                except Exception as e:
                    vprint(f"{L('tree_reuse_fail')} {e}")
                    try:
                        plan,tin2,tout2=ask_gemini_tree(model,titles_pairs,logs_dir=opts["log_dir"]); plan=canon_plan_multilang(plan); plan=enforce_root_cap(plan,LIMIT_ROOTS)
                    except Exception as e2:
                        vprint(f"{L('tree_fallback_fail')} {e2}"); plan=None
            else:
                vprint(L("tree_fresh"))
                try:
                    plan,tin2,tout2=ask_gemini_tree(model,titles_pairs,logs_dir=opts["log_dir"]); plan=canon_plan_multilang(plan); plan=enforce_root_cap(plan,LIMIT_ROOTS)
                except Exception as e:
                    vprint(f"{L('tree_fresh_fail')} {e}"); plan=None
        else:
            vprint(L("tree_fresh"))
            try:
                plan,tin2,tout2=ask_gemini_tree(model,titles_pairs,logs_dir=opts["log_dir"]); plan=canon_plan_multilang(plan); plan=enforce_root_cap(plan,LIMIT_ROOTS)
            except Exception as e:
                vprint(f"{L('tree_fresh_fail')} {e}"); plan=None

    # Dry-run
    if opts["dry_run"]:
        sp=save_dryrun(opts["log_dir"],ts,proposals,plan,errors)
        if plan: save_arbo_snapshot(plan,opts["log_dir"],ts)
        total_in,total_out=tin1+tin2,tout1+tout2; price=PRICING.get(MODEL,PRICING["gemini-1.5-flash"]); cost=total_in/1e6*price["in"]+total_out/1e6*price["out"]
        print(f"\n{L('summary_dry')}"); print(f"{L('tokens_in')}: {total_in:,}"); print(f"{L('tokens_out')}: {total_out:,}"); print(f"{L('est_cost')}: ${cost:.4f}"); print(f"{L('logs_folder')}: {opts['log_dir']}"); print(f"{L('saved_state')}: {sp}")
        print_author_footer()
        if yn(L("apply_now"), False):
            apply_dryrun(sp,opts["output_dir"],opts["failed_dir"],log_rows,opts["input_dir"])
            print(L("applied"))
    else:
        # Apply mode
        if opts["arbo"] and plan:
            apply_tree(plan,titles_pairs,opts["output_dir"],opts["failed_dir"],opts["input_dir"],log_rows)
            save_arbo_snapshot(plan,opts["log_dir"],ts)
        else:
            move_flat(titles_pairs,opts["output_dir"])

        # Move residual errors/skipped (preserve subpath)
        for s in errors:
            fp=s.get("fullpath")
            if fp and os.path.isfile(fp):
                try:
                    move_preserve_subpath(fp, opts["input_dir"], opts["failed_dir"])
                    log_rows.append({"filename":os.path.relpath(fp, opts["input_dir"]),"status":"MOVED_TO_FAILED","reason":s.get("reason",s.get("status","Unknown"))})
                except Exception as e:
                    log_rows.append({"filename":os.path.basename(fp),"status":"ERROR","reason":f"Move residual fail: {e}"})

        # Final sweep of Input → Failed + delete empty dirs
        sweep_input_to_failed(opts["input_dir"],opts["failed_dir"],log_rows)

        # ALWAYS write logs in real runs
        summary_lines=[
            f"Run timestamp    : {ts}",
            f"Model            : {MODEL}",
            f"Files processed  : {len(titles_pairs)}",
            f"Tokens IN        : {tin1+tin2:,}",
            f"Tokens OUT       : {tout1+tout2:,}",
            f"Estimated cost   : ${((tin1+tin2)/1e6*PRICING.get(MODEL,PRICING['gemini-1.5-flash'])['in'] + (tout1+tout2)/1e6*PRICING.get(MODEL,PRICING['gemini-1.5-flash'])['out']):.4f}",
            f"Output folder    : {opts['output_dir']}",
            f"Failed folder    : {opts['failed_dir']}",
            f"Logs folder      : {opts['log_dir']}",
        ]
        write_summary_txt(os.path.join(opts["log_dir"], f"run_summary_{ts}.txt"), summary_lines)
        write_table_any(os.path.join(opts["log_dir"], f"errors_realrun_{ts}"), log_rows if log_rows else [])

        # Cleanup .gitkeep (post-run, to keep repo clean for users)
        if REMOVE_GITKEEP_AFTER_RUN:
            for d in [opts["input_dir"], opts["output_dir"], opts["failed_dir"], opts["log_dir"]]:
                for root, _, files in os.walk(d):
                    for fn in files:
                        if fn.lower()==".gitkeep":
                            try: os.remove(os.path.join(root,fn))
                            except Exception: pass

        total_in,total_out=tin1+tin2,tout1+tout2; price=PRICING.get(MODEL,PRICING["gemini-1.5-flash"]); cost=total_in/1e6*price["in"]+total_out/1e6*price["out"]
        print(f"\n{L('summary')}"); print(f"{L('files_processed')}: {len(titles_pairs)}"); print(f"{L('tokens_in')}: {total_in:,}"); print(f"{L('tokens_out')}: {total_out:,}"); print(f"{L('est_cost')}: ${cost:.4f}"); print(f"{L('logs_folder')}: {opts['log_dir']}"); print(f"{L('errors_moved')}: {opts['failed_dir']}"); print(L('done'))
        print_author_footer()

if __name__ == "__main__":
    main()
