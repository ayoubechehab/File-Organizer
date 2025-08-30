#!/usr/bin/env python3
# ================================================================
# File Organizer
# ================================================================
# Description:
#   File Organizer is a smart document organizer powered by
#   Google Gemini API. It analyzes file content (PDF, DOCX, Excel,
#   scanned images via OCR) and automatically proposes or applies
#   meaningful filenames and an optional folder tree structure.
#
# Features:
#   - Dry-run mode: generate rename proposals & folder tree mapping
#   - Real mode: rename files & optionally move into structured folders
#   - Error handling: skipped/failed files logged (dry-run) or moved to ./Failed (real run)
#   - Keeps ./Output clean (only user files)
#   - All logs stored in ./Logs
#   - Supports: PDF, DOCX, XLSX/XLS, JPG/PNG/TIFF/BMP/WEBP
#
# Folder structure:
#   Input/   -> source files to process
#   Output/  -> final renamed & organized files
#   Failed/  -> only error files from real runs
#   Logs/    -> proposals, mappings, error logs, dryrun state
#
# API Key:
#   - Place your Gemini API key in the file `api_key.txt` (empty by default)
#   - Or pass it with `--api` or set env var `GEMINI_API_KEY`
#
# Author:   Ayoub ECHEHAB
# Website:  https://www.ayoubechehab.com
# LinkedIn: https://www.linkedin.com/in/ayoubechehab
# License:  MIT
# Repository: https://github.com/ayoubechehab/file-organizer
# ================================================================

import os, re, json, csv, shutil, glob, argparse
from datetime import datetime

import google.generativeai as genai
from PIL import Image
import pytesseract
import pypdf
import docx

try:
    import pandas as pd
    HAS_PANDAS = True
except Exception:
    HAS_PANDAS = False

MODEL = "gemini-1.5-flash"
DATE_FIRST = True
MAX_TEXT_LEN = 16000
MIN_TEXT_CHARS = 40
BATCH_SIZE_TITLES = 200

PRICING = {
    "gemini-1.5-flash": {"in": 0.075, "out": 0.30},
    "gemini-1.5-pro":   {"in": 0.30,  "out": 1.20},
}

ALLOWED_EXTS = {
    ".pdf", ".docx", ".xlsx", ".xls",
    ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"
}

# ---------------- Helpers ----------------
def get_api_key(cli_api: str | None) -> str:
    if cli_api: return cli_api.strip()
    env = os.environ.get("GEMINI_API_KEY")
    if env: return env.strip()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    key_path = os.path.join(script_dir, "api_key.txt")
    if os.path.isfile(key_path):
        with open(key_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    raise RuntimeError("No API key found. Put your Gemini key in api_key.txt, or pass --api, or set GEMINI_API_KEY env var.")

def ask(prompt: str, default: str | None = None) -> str:
    if default:
        s = input(f"{prompt} [{default}]: ").strip()
        return s or default
    return input(f"{prompt}: ").strip()

def yn(prompt: str, default_yes=True) -> bool:
    d = "Y/n" if default_yes else "y/N"
    s = input(f"{prompt} ({d}): ").strip().lower()
    if not s: return default_yes
    return s in {"y", "yes"}

def write_table_any(path_base: str, rows: list[dict]):
    if HAS_PANDAS and rows:
        df = pd.DataFrame(rows)
        xlsx = path_base + ".xlsx"
        os.makedirs(os.path.dirname(xlsx), exist_ok=True)
        df.to_excel(xlsx, index=False)
        return xlsx
    elif rows:
        csv_path = path_base + ".csv"
        header = list(rows[0].keys())
        with open(csv_path,"w",newline="",encoding="utf-8") as f:
            w=csv.writer(f); w.writerow(header)
            for r in rows: w.writerow([r.get(k,"") for k in header])
        return csv_path
    return None

def clean_desc(desc: str) -> str:
    desc = "".join(c for c in desc if c.isalnum() or c in " -_").strip()
    return re.sub(r"\s+", " ", desc)

def build_new_name(original: str, desc: str, date_str: str | None) -> str:
    ext = os.path.splitext(original)[1]
    desc = clean_desc(desc) or "Document"
    if date_str:
        return (f"{date_str}_{desc}{ext}" if DATE_FIRST else f"{desc}_{date_str}{ext}")
    return f"{desc}{ext}"

def chunks(lst, n):
    for i in range(0, len(lst), n): yield lst[i:i+n]

def find_latest_dryrun_state(log_dir: str):
    files = sorted(glob.glob(os.path.join(log_dir, "dryrun_state_*.json")))
    return files[-1] if files else None

# ---------------- Gemini ----------------
def configure_genai(api_key: str):
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(MODEL)

def ask_gemini_title(model, text: str, filename: str):
    prompt = f"""
You work in FR. Detect the document's language and create a concise title:

- If ENGLISH → "lang":"en" and "resume" in ENGLISH
- If ARABIC → "lang":"ar" but "resume" in FRENCH
- If FRENCH → "lang":"fr" and "resume" in FRENCH
- Else → "lang":"other" and "resume" in FRENCH

Return JSON:
{{
  "lang": "fr|en|ar|other",
  "resume": "short title",
  "date": "YYYY-MM-DD" or null
}}
"""
    resp = model.generate_content(prompt + f"\nText from '{filename}':\n---\n{text[:MAX_TEXT_LEN]}\n---")
    data = json.loads(resp.text.strip().replace("```json","").replace("```",""))
    if not data.get("resume"): data["resume"]="Document"
    return data, getattr(getattr(resp,"usage_metadata",None),"prompt_token_count",0) or 0, getattr(getattr(resp,"usage_metadata",None),"candidates_token_count",0) or 0

TREE_PROMPT_HEADER = """
You are an information architect. Given renamed file names, propose a folder tree and mapping.

Return JSON:
{
  "tree": { "Category": ["Sub"], ... },
  "map": { "File.ext": "Category/Sub", ... },
  "rules": ["How categories were chosen"],
  "notes": "Short remarks"
}
"""

def ask_gemini_tree(model, titles_pairs):
    aggregated={"tree":{},"map":{},"rules":[],"notes":""}
    total_in=total_out=0
    for batch in chunks(titles_pairs,BATCH_SIZE_TITLES):
        listing="\n".join([f"- {t}" for _,t in batch])
        resp=model.generate_content(TREE_PROMPT_HEADER+"\nFILES:\n"+listing)
        tin=getattr(getattr(resp,"usage_metadata",None),"prompt_token_count",0) or 0
        tout=getattr(getattr(resp,"usage_metadata",None),"candidates_token_count",0) or 0
        total_in+=tin; total_out+=tout
        data=json.loads(resp.text.strip().replace("```json","").replace("```",""))
        for cat,subs in data.get("tree",{}).items():
            aggregated["tree"].setdefault(cat,[])
            aggregated["tree"][cat]=list(dict.fromkeys(aggregated["tree"][cat]+(subs or [])))
        aggregated["map"].update(data.get("map",{}))
        aggregated["rules"].extend(data.get("rules",[]))
        note=(data.get("notes") or "").strip()
        if note: aggregated["notes"]+=("\n"+note if aggregated["notes"] else note)
    aggregated["rules"]=list(dict.fromkeys([r.strip() for r in aggregated["rules"] if r.strip()]))
    return aggregated,total_in,total_out

# ---------------- Text Extraction ----------------
def extract_text(path: str) -> str:
    ext=os.path.splitext(path)[1].lower(); txt=""
    try:
        if ext==".pdf":
            with open(path,"rb") as f: reader=pypdf.PdfReader(f); txt="".join([p.extract_text() or "" for p in reader.pages])
        elif ext==".docx":
            d=docx.Document(path); txt="\n".join(p.text for p in d.paragraphs)
        elif ext in [".xlsx",".xls"] and HAS_PANDAS:
            xls=pd.read_excel(path,sheet_name=None,header=None,dtype=str)
            cells=[]
            for _,df in xls.items(): cells.extend([str(v) for v in df.fillna("").values.flatten().tolist() if str(v).strip()])
            txt="\n".join(cells)
        elif ext in [".jpg",".jpeg",".png",".tif",".tiff",".bmp",".webp"]:
            txt=pytesseract.image_to_string(Image.open(path),lang="fra")
        return txt.strip()
    except Exception as e:
        return f"__EXTRACT_ERROR__: {e}"

# ---------------- Phases ----------------
def phase1(model,input_dir,dry_run):
    titles_pairs=[]; tok_in=tok_out=0; skipped=[]; proposals=[]
    for r,_,files in os.walk(input_dir):
        for fn in files:
            path=os.path.join(r,fn); ext=os.path.splitext(fn)[1].lower()
            if ext not in ALLOWED_EXTS: skipped.append({"filename":fn,"status":"SKIPPED","reason":f"Extension {ext}"}); continue
            text=extract_text(path)
            if text.startswith("__EXTRACT_ERROR__"): skipped.append({"filename":fn,"status":"ERROR","reason":text}); continue
            if len(text)<MIN_TEXT_CHARS: skipped.append({"filename":fn,"status":"SKIPPED","reason":"Not enough text"}); continue
            try:
                data,tin,tout=ask_gemini_title(model,text,fn); tok_in+=tin; tok_out+=tout
                desc,date=data.get("resume") or "Document",data.get("date")
                proposed=build_new_name(fn,desc,date)
                if dry_run: proposals.append({"file":fn,"proposed_name":proposed,"lang":data.get("lang",""),"summary":desc,"date":date or "","current_path":path}); titles_pairs.append((path,proposed))
                else:
                    new_path=os.path.join(r,proposed)
                    if os.path.exists(new_path) and os.path.abspath(new_path)!=os.path.abspath(path):
                        base,ext=os.path.splitext(proposed); i=2
                        while os.path.exists(os.path.join(r,f"{base} ({i}){ext}")): i+=1
                        new_path=os.path.join(r,f"{base} ({i}){ext}")
                    os.rename(path,new_path); titles_pairs.append((new_path,os.path.basename(new_path)))
            except Exception as e:
                skipped.append({"filename":fn,"status":"ERROR","reason":f"LLM error {e}"})
    return titles_pairs,tok_in,tok_out,skipped,proposals

def move_flat(titles_pairs,output_dir):
    os.makedirs(output_dir,exist_ok=True)
    for src,base in titles_pairs:
        dst=os.path.join(output_dir,base)
        if os.path.exists(dst):
            n,e=os.path.splitext(base); i=2
            while os.path.exists(os.path.join(output_dir,f"{n} ({i}){e}")): i+=1
            dst=os.path.join(output_dir,f"{n} ({i}){e}")
        shutil.move(src,dst)

def apply_tree(plan,titles_pairs,output_dir,failed_dir,log_rows):
    os.makedirs(output_dir,exist_ok=True); os.makedirs(failed_dir,exist_ok=True)
    name_to_path={os.path.basename(p):p for p,_ in titles_pairs}
    for name,rel in plan.get("map",{}).items():
        src=name_to_path.get(name)
        if not src: log_rows.append({"filename":name,"status":"ERROR","reason":"Missing"}); continue
        parts=[p for p in (rel or "").split("/") if p]; dst_dir=os.path.join(output_dir,*parts) if parts else output_dir
        os.makedirs(dst_dir,exist_ok=True); dst=os.path.join(dst_dir,name)
        try: shutil.move(src,dst)
        except Exception as e:
            fb=os.path.join(failed_dir,name)
            try: shutil.move(src,fb); log_rows.append({"filename":name,"status":"ERROR","reason":f"Move fail {e}"})
            except: log_rows.append({"filename":name,"status":"ERROR","reason":f"Move+fail fail"})

# ---------------- Dry-run save/apply ----------------
def save_dryrun(log_dir,run_ts,proposals,plan,errors):
    state={"timestamp":run_ts,"proposals":proposals,"plan":plan}
    sp=os.path.join(log_dir,f"dryrun_state_{run_ts}.json")
    with open(sp,"w",encoding="utf-8") as f: json.dump(state,f,ensure_ascii=False,indent=2)
    write_table_any(os.path.join(log_dir,f"errors_{run_ts}"),errors)
    write_table_any(os.path.join(log_dir,f"rename_proposals_{run_ts}"),proposals)
    if plan: write_table_any(os.path.join(log_dir,f"arbo_mapping_{run_ts}"),[{"file":n,"dest":d} for n,d in plan.get("map",{}).items()])
    return sp

def apply_dryrun(state_path,output_dir,failed_dir,log_rows):
    with open(state_path,"r",encoding="utf-8") as f: state=json.load(f)
    proposals,plan=state.get("proposals",[]),state.get("plan"); titles_pairs=[]
    for p in proposals:
        src=p["current_path"]; newname=p["proposed_name"]
        if not os.path.isfile(src): log_rows.append({"filename":os.path.basename(src),"status":"ERROR","reason":"Not found"}); continue
        dst=os.path.join(os.path.dirname(src),newname)
        if os.path.exists(dst): n,e=os.path.splitext(newname); i=2
        while os.path.exists(os.path.join(os.path.dirname(src),f"{n} ({i}){e}")): i+=1
        dst=os.path.join(os.path.dirname(src),f"{n} ({i}){e}")
        try: os.rename(src,dst); titles_pairs.append((dst,os.path.basename(dst)))
        except: log_rows.append({"filename":newname,"status":"ERROR","reason":"Rename fail"})
    if plan: apply_tree(plan,titles_pairs,output_dir,failed_dir,log_rows)
    else: move_flat(titles_pairs,output_dir)

# ---------------- Interactive ----------------
def interactive_inputs():
    print("=== File Organizer ===")
    input_dir=ask("Folder to process","./Input"); output_dir=ask("Output folder","./Output")
    failed_dir=ask("Failed folder","./Failed"); log_dir=ask("Logs folder","./Logs")
    os.makedirs(input_dir,exist_ok=True); os.makedirs(output_dir,exist_ok=True); os.makedirs(failed_dir,exist_ok=True); os.makedirs(log_dir,exist_ok=True)
    dry=yn("Dry-Run (do not modify files)?",True)
    if dry: arbo=yn("→ Include folder tree proposal too?",False)
    else: arbo=yn("→ Apply folder tree organization?",False)
    return {"input_dir":input_dir,"output_dir":output_dir,"failed_dir":failed_dir,"log_dir":log_dir,"dry_run":dry,"arbo":arbo}

# ---------------- Main ----------------
def main():
    args=argparse.ArgumentParser(); args.add_argument("--api"); args=args.parse_args()
    api=get_api_key(args.api); model=configure_genai(api)
    opts=interactive_inputs(); run_ts=datetime.now().strftime("%Y%m%d_%H%M%S"); log_rows=[]
    titles_pairs,tin1,tout1,errors,proposals=phase1(model,opts["input_dir"],opts["dry_run"])
    plan,tin2,tout2=(None,0,0)
    if opts["arbo"] and titles_pairs: plan,tin2,tout2=ask_gemini_tree(model,titles_pairs)
    if opts["dry_run"]:
        sp=save_dryrun(opts["log_dir"],run_ts,proposals,plan,errors)
        print("\n===== SUMMARY (dry-run) =====")
        print(f"Tokens IN  : {tin1+tin2:,}\nTokens OUT : {tout1+tout2:,}")
        print(f"Estimated cost : ${(tin1+tin2)/1e6*PRICING[MODEL]['in']+(tout1+tout2)/1e6*PRICING[MODEL]['out']:.4f}")
        print(f"Logs folder : {opts['log_dir']}\nSaved state : {sp}")
        if yn("\nApply these proposals now (no extra API)?",False):
            apply_dryrun(sp,opts["output_dir"],opts["failed_dir"],log_rows)
            print("Applied ✅")
    else:
        if opts["arbo"] and plan: apply_tree(plan,titles_pairs,opts["output_dir"],opts["failed_dir"],log_rows)
        else: move_flat(titles_pairs,opts["output_dir"])
        print("\n===== SUMMARY =====")
        print(f"Files processed : {len(titles_pairs)}")
        print(f"Tokens IN  : {tin1+tin2:,}\nTokens OUT : {tout1+tout2:,}")
        print(f"Estimated cost : ${(tin1+tin2)/1e6*PRICING[MODEL]['in']+(tout1+tout2)/1e6*PRICING[MODEL]['out']:.4f}")
        print(f"Logs folder : {opts['log_dir']}\nErrors moved to : {opts['failed_dir']}\nDone ✨")

if __name__=="__main__": main()
