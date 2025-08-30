#!/usr/bin/env python3
# ================================================================
# File Organizer v1.0.0
# ================================================================
# Description:
#   Smart file organizer powered by Google Gemini API.
#   Analyzes content (PDF, DOCX, Excel, scanned images via OCR),
#   proposes or applies meaningful filenames, and optionally organizes
#   files into a folder tree (arborescence).
#
# Features:
#   - Content-aware renaming
#   - Dry-run preview with rename & tree proposals
#   - Apply mode: rename + move files to Output/ or structured arbo
#   - Reuse last folder tree for classifying new files (with minimal new subfolders when needed)
#   - Or do a fresh tree (ignore previous one and let Gemini suggest a brand-new arbo)
#   - End-of-run safety: leftovers in Input/ → Failed/
#   - Always logs in Logs/ (summary + errors)
#   - Removes .gitkeep automatically after run
#
# Author:   Ayoub ECHEHAB
# Website:  https://www.ayoubechehab.com
# GitHub:   https://github.com/ayoubechehab
# License:  MIT
# ================================================================

import os, re, json, csv, shutil, glob, argparse, time, logging
from datetime import datetime

import google.generativeai as genai
from PIL import Image
import pytesseract
import pypdf
import docx

logging.getLogger("pypdf").setLevel(logging.ERROR)

try:
    import pandas as pd
    HAS_PANDAS = True
except Exception:
    HAS_PANDAS = False

APP_VERSION="1.0.0"
MODEL="gemini-1.5-flash"
DATE_FIRST=True
MAX_TEXT_LEN=16000
MIN_TEXT_CHARS=40
BATCH_SIZE_TITLES=200
PRICING={"gemini-1.5-flash":{"in":0.075,"out":0.30},"gemini-1.5-pro":{"in":0.30,"out":1.20}}
ALLOWED_EXTS={".pdf",".docx",".xlsx",".xls",".jpg",".jpeg",".png",".tif",".tiff",".bmp",".webp"}

AUTHOR_NAME="Ayoub ECHEHAB"
AUTHOR_GITHUB="https://github.com/ayoubechehab"
AUTHOR_SITE="https://www.ayoubechehab.com"

VERBOSE=True
REQUEST_SPACING_SECONDS=1.2
MAX_RETRIES=5
BACKOFF_BASE=2.0
REMOVE_GITKEEP_AFTER_RUN=True  # remove .gitkeep files at the end of real run

def vprint(*a,**kw):
    if VERBOSE: print(*a,**kw)

def print_author_footer():
    print(f"\n— File Organizer v{APP_VERSION}")
    print("  Made by:", AUTHOR_NAME)
    print("  GitHub :", AUTHOR_GITHUB)
    print("  Website:", AUTHOR_SITE)

def get_api_key(cli):
    if cli: return cli.strip()
    env=os.environ.get("GEMINI_API_KEY")
    if env: return env.strip()
    key_path=os.path.join(os.path.dirname(os.path.abspath(__file__)),"api_key.txt")
    if os.path.isfile(key_path):
        with open(key_path,"r",encoding="utf-8") as f: return f.read().strip()
    raise RuntimeError("No API key found. Put your Gemini key in api_key.txt, or pass --api, or set GEMINI_API_KEY.")

def ask(p,d=None):
    if d is not None:
        s=input(f"{p} [{d}]: ").strip(); return s or d
    return input(f"{p}: ").strip()

def yn(p, default_yes=True):
    d="Y/n" if default_yes else "y/N"; s=input(f"{p} ({d}): ").strip().lower()
    if not s: return default_yes
    return s in {"y","yes"}

def write_table_any(path_base, rows):
    if not rows:
        # Always create an empty CSV if there are no rows
        csv_path=path_base+".csv"
        os.makedirs(os.path.dirname(csv_path),exist_ok=True)
        with open(csv_path,"w",newline="",encoding="utf-8") as f:
            w=csv.writer(f); w.writerow(["filename","status","reason"])
        return csv_path
    if HAS_PANDAS:
        import pandas as pd
        df=pd.DataFrame(rows)
        xlsx=path_base+".xlsx"
        os.makedirs(os.path.dirname(xlsx),exist_ok=True)
        df.to_excel(xlsx,index=False)
        return xlsx
    else:
        csv_path=path_base+".csv"
        os.makedirs(os.path.dirname(csv_path),exist_ok=True)
        with open(csv_path,"w",newline="",encoding="utf-8") as f:
            w=csv.writer(f)
            header=list(rows[0].keys())
            w.writerow(header)
            for r in rows:
                w.writerow([r.get(k,"") for k in header])
        return csv_path

def write_summary_txt(path, info_lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(info_lines))

def clean_desc(s):
    s="".join(c for c in s if c.isalnum() or c in " -_").strip()
    import re; return re.sub(r"\s+"," ",s)

def build_new_name(orig, desc, date):
    ext=os.path.splitext(orig)[1]; desc=clean_desc(desc) or "Document"
    return (f"{date}_{desc}{ext}" if DATE_FIRST and date else (f"{desc}_{date}{ext}" if date else f"{desc}{ext}"))

def chunks(lst,n):
    for i in range(0,len(lst),n): yield lst[i:i+n]

def find_latest_dryrun_state(log_dir):
    files=sorted(glob.glob(os.path.join(log_dir,"dryrun_state_*.json"))); return files[-1] if files else None

def save_arbo_snapshot(plan, log_dir, run_ts):
    if not plan: return None
    os.makedirs(log_dir, exist_ok=True)
    hist_dir=os.path.join(log_dir,"arbo_history"); os.makedirs(hist_dir, exist_ok=True)
    last_path=os.path.join(log_dir,"arbo_last.json")
    hist_path=os.path.join(hist_dir,f"arbo_{run_ts}.json")
    with open(last_path,"w",encoding="utf-8") as f: json.dump(plan,f,ensure_ascii=False,indent=2)
    with open(hist_path,"w",encoding="utf-8") as f: json.dump(plan,f,ensure_ascii=False,indent=2)
    return last_path

def load_last_arbo(log_dir):
    p=os.path.join(log_dir,"arbo_last.json")
    if os.path.isfile(p):
        try:
            with open(p,"r",encoding="utf-8") as f: return json.load(f)
        except Exception: return None
    return None

def configure_genai(key): genai.configure(api_key=key); return genai.GenerativeModel(MODEL)

def _gen_content_with_retry(model, prompt):
    last_err=None
    for attempt in range(1,MAX_RETRIES+1):
        try:
            time.sleep(REQUEST_SPACING_SECONDS); return model.generate_content(prompt)
        except Exception as e:
            last_err=e; msg=str(e)
            if "429" in msg or "ResourceExhausted" in msg or "quota" in msg.lower():
                sleep_s=(BACKOFF_BASE**(attempt-1))
                vprint(f"[RATE-LIMIT] Waiting {sleep_s:.1f}s before retry {attempt}/{MAX_RETRIES}..."); time.sleep(sleep_s); continue
            break
    raise last_err

def ask_gemini_title(model,text,filename):
    prompt = """
You work in FR. Detect the document's language and create a concise title:

- If ENGLISH → "lang":"en" and "resume" in ENGLISH
- If ARABIC → "lang":"ar" but "resume" in FRENCH
- If FRENCH → "lang":"fr" and "resume" in FRENCH
- Else → "lang":"other" and "resume" in FRENCH

Return JSON:
{"lang":"fr|en|ar|other","resume":"short title","date":"YYYY-MM-DD" or null}
"""
    full=prompt+f"\nText from '{filename}':\n---\n{text[:MAX_TEXT_LEN]}\n---"
    resp=_gen_content_with_retry(model,full)
    data=json.loads(resp.text.strip().replace("```json","").replace("```",""))
    if not data.get("resume"): data["resume"]="Document"
    tin=getattr(getattr(resp,"usage_metadata",None),"prompt_token_count",0) or 0
    tout=getattr(getattr(resp,"usage_metadata",None),"candidates_token_count",0) or 0
    return data,tin,tout

TREE_PROMPT_HEADER="""You are an information architect. Given renamed file names, propose a folder tree and mapping.
Return JSON: {"tree":{},"map":{},"rules":[],"notes":""}"""

def ask_gemini_tree(model,titles_pairs):
    agg={"tree":{},"map":{},"rules":[],"notes":""}; total_in=total_out=0
    for batch in chunks(titles_pairs,BATCH_SIZE_TITLES):
        listing="\n".join([f"- {t}" for _,t in batch])
        prompt=TREE_PROMPT_HEADER+"\nFILES:\n"+listing
        resp=_gen_content_with_retry(model,prompt)
        tin=getattr(getattr(resp,"usage_metadata",None),"prompt_token_count",0) or 0
        tout=getattr(getattr(resp,"usage_metadata",None),"candidates_token_count",0) or 0
        total_in+=tin; total_out+=tout
        data=json.loads(resp.text.strip().replace("```json","").replace("```",""))
        for cat,subs in data.get("tree",{}).items():
            agg["tree"].setdefault(cat,[]); agg["tree"][cat]=list(dict.fromkeys(agg["tree"][cat]+(subs or [])))
        agg["map"].update(data.get("map",{})); agg["rules"].extend(data.get("rules",[]))
        note=(data.get("notes") or "").strip()
        if note: agg["notes"]+=("\n"+note if agg["notes"] else note)
    agg["rules"]=list(dict.fromkeys([r.strip() for r in agg["rules"] if r.strip()])); return agg,total_in,total_out

def ask_gemini_map_with_existing_tree(model, titles_pairs, existing_plan):
    existing_tree = existing_plan.get("tree", {})
    prompt = f"""
You are an information architect. You are given an EXISTING folder tree (categories/subcategories) and a list of FILE NAMES (already renamed).
Your job:
1) Map each file into the MOST appropriate existing category/subcategory path from the provided tree.
2) ONLY if no fit is reasonable, you MAY propose a minimal new subfolder under the closest category.
3) Keep mappings short like "Category/Sub[/Sub2]".
4) Return JSON with keys:
{{
  "map": {{ "File.ext": "Category/Sub", ... }},
  "tree_additions": {{ "Category": ["NewSub", ...], ... }}
}}

EXISTING_TREE:
{json.dumps(existing_tree, ensure_ascii=False, indent=2)}

FILES:
""" + "\n".join([f"- {t}" for _, t in titles_pairs])
    resp=_gen_content_with_retry(model,prompt)
    tin=getattr(getattr(resp,"usage_metadata",None),"prompt_token_count",0) or 0
    tout=getattr(getattr(resp,"usage_metadata",None),"candidates_token_count",0) or 0
    data=json.loads(resp.text.strip().replace("```json","").replace("```",""))
    out={"map": data.get("map",{}) or {}, "tree_additions": data.get("tree_additions",{}) or {}}
    return out,tin,tout

def extract_text(path):
    ext=os.path.splitext(path)[1].lower(); txt=""
    try:
        if ext==".pdf":
            with open(path,"rb") as f:
                reader=pypdf.PdfReader(f); txt="".join([p.extract_text() or "" for p in reader.pages])
        elif ext==".docx":
            d=docx.Document(path); txt="\n".join(p.text for p in d.paragraphs)
        elif ext in [".xlsx",".xls"] and HAS_PANDAS:
            import pandas as pd
            xls=pd.read_excel(path,sheet_name=None,header=None,dtype=str); cells=[]
            for _,df in xls.items(): cells.extend([str(v) for v in df.fillna("").values.flatten().tolist() if str(v).strip()])
            txt="\n".join(cells)
        elif ext in [".jpg",".jpeg",".png",".tif",".tiff",".bmp",".webp"]:
            try: txt=pytesseract.image_to_string(Image.open(path),lang="fra")
            except Exception: txt=pytesseract.image_to_string(Image.open(path))
        return (txt or "").strip()
    except Exception as e:
        return f"__EXTRACT_ERROR__: {e}"

def move_with_collision_avoid(src, dst_dir):
    os.makedirs(dst_dir,exist_ok=True)
    base=os.path.basename(src); dst=os.path.join(dst_dir,base)
    if os.path.exists(dst):
        n,e=os.path.splitext(base); i=2
        while os.path.exists(os.path.join(dst_dir,f"{n} ({i}){e}")): i+=1
        dst=os.path.join(dst_dir,f"{n} ({i}){e}")
    shutil.move(src,dst); return dst

def sweep_input_to_failed(input_dir, failed_dir, log_rows):
    os.makedirs(failed_dir, exist_ok=True)
    for root,_,files in os.walk(input_dir):
        for fn in files:
            if fn.lower()==".gitkeep": 
                continue
            src=os.path.join(root,fn)
            try:
                move_with_collision_avoid(src, failed_dir)
                log_rows.append({"filename": fn, "status": "MOVED_TO_FAILED", "reason": "Leftover in Input at end"})
            except Exception as e:
                log_rows.append({"filename": fn, "status": "ERROR", "reason": f"Final sweep move fail: {e}"})

def remove_gitkeeps(*dirs):
    if not REMOVE_GITKEEP_AFTER_RUN: return
    for d in dirs:
        for root,_,files in os.walk(d):
            for fn in files:
                if fn.lower()==".gitkeep":
                    try: os.remove(os.path.join(root,fn))
                    except Exception: pass

def phase1(model,input_dir,dry_run):
    titles_pairs=[]; tok_in=tok_out=0; skipped=[]; proposals=[]
    # count
    total=0
    for r0,_,f0 in os.walk(input_dir): total+=len([x for x in f0 if x.lower()!=".gitkeep"])
    i=0
    for r,_,files in os.walk(input_dir):
        for fn in files:
            if fn.lower()==".gitkeep": continue
            i+=1
            path=os.path.join(r,fn); ext=os.path.splitext(fn)[1].lower()
            vprint(f"[SCAN {i}/{total}] {fn}")
            if ext not in ALLOWED_EXTS:
                vprint(f"  └─ SKIP (unsupported extension: {ext})")
                skipped.append({"filename":fn,"status":"SKIPPED","reason":f"Extension {ext}","fullpath":path}); continue
            vprint("  └─ Extracting text..."); text=extract_text(path)
            if text.startswith("__EXTRACT_ERROR__"): vprint(f"  └─ ERROR extracting: {text}"); skipped.append({"filename":fn,"status":"ERROR","reason":text,"fullpath":path}); continue
            if len(text)<MIN_TEXT_CHARS: vprint("  └─ SKIP (not enough text)"); skipped.append({"filename":fn,"status":"SKIPPED","reason":"Not enough text","fullpath":path}); continue
            try:
                vprint("  └─ Sending to Gemini for title...")
                data,tin,tout=ask_gemini_title(model,text,fn); tok_in+=tin; tok_out+=tout
                desc=data.get("resume") or "Document"; date=data.get("date"); proposed=build_new_name(fn,desc,date)
                vprint(f"  └─ Proposed: {proposed}")
                if dry_run:
                    proposals.append({"file":fn,"proposed_name":proposed,"lang":data.get("lang",""),"summary":desc,"date":date or "","current_path":path})
                    titles_pairs.append((path,proposed))
                else:
                    new_path=os.path.join(r,proposed)
                    if os.path.exists(new_path) and os.path.abspath(new_path)!=os.path.abspath(path):
                        base,ext2=os.path.splitext(proposed); k=2
                        while os.path.exists(os.path.join(r,f"{base} ({k}){ext2}")): k+=1
                        new_path=os.path.join(r,f"{base} ({k}){ext2}")
                    os.rename(path,new_path); vprint(f"  └─ Renamed → {os.path.basename(new_path)}")
                    titles_pairs.append((new_path,os.path.basename(new_path)))
            except Exception as e:
                vprint(f"  └─ ERROR LLM: {e}")
                skipped.append({"filename":fn,"status":"ERROR","reason":f"LLM error {e}","fullpath":path})
    return titles_pairs,tok_in,tok_out,skipped,proposals

def move_flat(titles_pairs,out_dir):
    os.makedirs(out_dir,exist_ok=True)
    for src,base in titles_pairs:
        dst=os.path.join(out_dir,base)
        if os.path.exists(dst):
            n,e=os.path.splitext(base); i=2
            while os.path.exists(os.path.join(out_dir,f"{n} ({i}){e}")): i+=1
            dst=os.path.join(out_dir,f"{n} ({i}){e}")
        shutil.move(src,dst)

def apply_tree(plan,titles_pairs,out_dir,failed_dir,log_rows):
    os.makedirs(out_dir,exist_ok=True); os.makedirs(failed_dir,exist_ok=True)
    name_to_path={os.path.basename(p):p for p,_ in titles_pairs}
    mapped=plan.get("map",{}) or {}
    for name,rel in mapped.items():
        src=name_to_path.get(name)
        if not src: log_rows.append({"filename":name,"status":"ERROR","reason":"Missing"}); continue
        parts=[p for p in (rel or "").split("/") if p]; dst_dir=os.path.join(out_dir,*parts) if parts else out_dir
        os.makedirs(dst_dir,exist_ok=True); dst=os.path.join(dst_dir,name)
        try: shutil.move(src,dst)
        except Exception as e:
            fb=os.path.join(failed_dir,name)
            try: shutil.move(src,fb); log_rows.append({"filename":name,"status":"ERROR","reason":f"Move fail {e}"})
            except Exception: log_rows.append({"filename":name,"status":"ERROR","reason":"Move+fail fail"})
    # Unmapped -> Failed
    for name,src in list(name_to_path.items()):
        if os.path.exists(src):
            try: move_with_collision_avoid(src,failed_dir); log_rows.append({"filename":os.path.basename(src),"status":"MOVED_TO_FAILED","reason":"Unmapped in plan"})
            except Exception as e: log_rows.append({"filename":os.path.basename(src),"status":"ERROR","reason":f"Unmapped move fail: {e}"})

def save_dryrun(log_dir,ts,props,plan,errors):
    state={"timestamp":ts,"proposals":props,"plan":plan}
    sp=os.path.join(log_dir,f"dryrun_state_{ts}.json"); os.makedirs(log_dir,exist_ok=True)
    with open(sp,"w",encoding="utf-8") as f: json.dump(state,f,ensure_ascii=False,indent=2)
    write_table_any(os.path.join(log_dir,f"errors_{ts}"),errors)
    write_table_any(os.path.join(log_dir,f"rename_proposals_{ts}"),props)
    if plan: write_table_any(os.path.join(log_dir,f"arbo_mapping_{ts}"),[{"file":n,"dest":d} for n,d in plan.get("map",{}).items()])
    return sp

def apply_dryrun(sp,out_dir,failed_dir,log_rows):
    with open(sp,"r",encoding="utf-8") as f: state=json.load(f)
    props,plan=state.get("proposals",[]),state.get("plan"); titles_pairs=[]
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
    if plan: apply_tree(plan,titles_pairs,out_dir,failed_dir,log_rows)
    else: move_flat(titles_pairs,out_dir)

def interactive_inputs():
    print("=== File Organizer ===")
    inp=ask("Folder to process","./Input"); out=ask("Output folder","./Output"); fail=ask("Failed folder","./Failed"); logs=ask("Logs folder","./Logs")
    os.makedirs(inp,exist_ok=True); os.makedirs(out,exist_ok=True); os.makedirs(fail,exist_ok=True); os.makedirs(logs,exist_ok=True)
    dry=yn("Dry-Run (do not modify files)?",True)
    if dry:
        arbo=yn("→ Include folder tree proposal too?",False); reuse=False
    else:
        arbo=yn("→ Apply folder tree organization?",False); reuse=False
        if arbo:
            reuse=yn("→ Reuse last folder tree if available?",True)
            if not reuse:
                vprint("[TREE] Fresh tree mode selected: previous arbo will be ignored.")
    return {"input_dir":inp,"output_dir":out,"failed_dir":fail,"log_dir":logs,"dry_run":dry,"arbo":arbo,"reuse_arbo":reuse if not dry else False}

def main():
    ap=argparse.ArgumentParser(description="File Organizer — content-aware rename & optional folder organization")
    ap.add_argument("--api"); args=ap.parse_args()
    api=get_api_key(args.api); model=configure_genai(api)
    opts=interactive_inputs(); ts=datetime.now().strftime("%Y%m%d_%H%M%S"); log_rows=[]
    titles_pairs,tin1,tout1,errors,proposals=phase1(model,opts["input_dir"],opts["dry_run"])
    plan,tin2,tout2=(None,0,0)
    if opts["arbo"] and titles_pairs:
        if not opts["dry_run"] and opts.get("reuse_arbo"):
            last=load_last_arbo(opts["log_dir"])
            if last:
                vprint("[TREE] Reusing last folder tree")
                try:
                    mapping_out,tin_m,tout_m=ask_gemini_map_with_existing_tree(model,titles_pairs,last)
                    tin2+=tin_m; tout2+=tout_m
                    fused_tree=dict(last.get("tree",{}))
                    for cat,subs in (mapping_out.get("tree_additions",{}) or {}).items():
                        fused_tree.setdefault(cat,[]); fused_tree[cat]=list(dict.fromkeys(fused_tree[cat]+(subs or [])))
                    fused_map=dict(last.get("map",{})); fused_map.update(mapping_out.get("map",{}) or {})
                    plan={"tree":fused_tree,"map":fused_map,"rules":last.get("rules",[]),"notes":last.get("notes","")}
                except Exception as e:
                    vprint(f"[TREE] Reuse failed, requesting new mapping: {e}")
                    plan,tin2,tout2=ask_gemini_tree(model,titles_pairs)
            else:
                vprint("[TREE] No previous tree found → requesting a new one from Gemini...")
                plan,tin2,tout2=ask_gemini_tree(model,titles_pairs)
        else:
            vprint("[TREE] Requesting fresh folder tree mapping from Gemini...")
            plan,tin2,tout2=ask_gemini_tree(model,titles_pairs)

    if opts["dry_run"]:
        sp=save_dryrun(opts["log_dir"],ts,proposals,plan,errors)
        if plan: save_arbo_snapshot(plan,opts["log_dir"],ts)
        total_in,total_out=tin1+tin2,tout1+tout2; price=PRICING.get(MODEL,PRICING["gemini-1.5-flash"]); cost=total_in/1e6*price["in"]+total_out/1e6*price["out"]
        print("\n===== SUMMARY (dry-run) ====="); print(f"Tokens IN  : {total_in:,}"); print(f"Tokens OUT : {total_out:,}"); print(f"Estimated cost : ${cost:.4f}"); print(f"Logs folder : {opts['log_dir']}"); print(f"Saved state : {sp}")
        print_author_footer()
        if yn("\nApply these proposals now (no extra API)?",False):
            apply_dryrun(sp,opts["output_dir"],opts["failed_dir"],log_rows); print("Applied ✅")
    else:
        if opts["arbo"] and plan:
            apply_tree(plan,titles_pairs,opts["output_dir"],opts["failed_dir"],log_rows)
            save_arbo_snapshot(plan,opts["log_dir"],ts)
        else:
            move_flat(titles_pairs,opts["output_dir"])
        # Move residual errors/skipped with fullpath
        for s in errors:
            fp=s.get("fullpath")
            if fp and os.path.isfile(fp):
                try: move_with_collision_avoid(fp,opts["failed_dir"]); log_rows.append({"filename":os.path.basename(fp),"status":"MOVED_TO_FAILED","reason":s.get("reason",s.get("status","Unknown"))})
                except Exception as e: log_rows.append({"filename":os.path.basename(fp),"status":"ERROR","reason":f"Move residual fail: {e}"})
        sweep_input_to_failed(opts["input_dir"],opts["failed_dir"],log_rows)
        # ALWAYS write logs in real run
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
        # Optional cleanup of .gitkeep so users don't see them
        remove_gitkeeps(opts["input_dir"], opts["output_dir"], opts["failed_dir"], opts["log_dir"])
        total_in,total_out=tin1+tin2,tout1+tout2; price=PRICING.get(MODEL,PRICING["gemini-1.5-flash"]); cost=total_in/1e6*price["in"]+total_out/1e6*price["out"]
        print("\n===== SUMMARY ====="); print(f"Files processed : {len(titles_pairs)}"); print(f"Tokens IN  : {total_in:,}"); print(f"Tokens OUT : {total_out:,}"); print(f"Estimated cost : ${cost:.4f}"); print(f"Logs folder : {opts['log_dir']}"); print(f"Errors moved to : {opts['failed_dir']}"); print("Done ✨")
        print_author_footer()

if __name__=="__main__": main()
