# 📂 File Organizer (v1.0.0)

**File Organizer** is a smart document organizer powered by the Google Gemini API.  
It analyzes file content and automatically **renames** files and (optionally) **organizes** them into a meaningful **folder tree**.

---

## ✨ Features
- 🔍 **Content-aware renaming** for PDFs, DOCX, Excel, and scanned images (OCR)
- 📝 **Dry-run**: preview rename proposals and (optionally) a proposed folder tree — no file changes
- 🚚 **Apply mode**: actually rename and move files into `Output/` (flat) or into a structured **arborescence**
- ♻️ **Reuse last folder tree**: classify new files into your **previous** arbo (`Logs/arbo_last.json`) and let Gemini add **minimal new subfolders** only if needed
- 🌱 **Fresh tree mode**: ignore the previous arbo and ask Gemini to suggest a **brand-new** tree from the current batch
- 🧹 **Safety sweep**: anything left in `Input/` after an apply run is moved to `Failed/` and logged
- 🧾 **Logging** (apply runs):
  - `Logs/run_summary_*.txt`
  - `Logs/errors_realrun_*.(xlsx/csv)` — created even if there are no errors (empty file)
- 📈 **Progress indicator**: `[SCAN i/N] filename`
- 💸 **Token usage & cost estimate** printed at the end

---

## 📦 Download (Release)
Grab the user-friendly ZIP from the latest release:  
👉 **https://github.com/ayoubechehab/File-Organizer/releases/download/v1.0.0/File-Organizer-UserPack-v1.0.0.zip**

---

## 🚀 Quick Start
1) `pip install -r requirements.txt`  
2) Open `api_key.txt` and paste your **Gemini API key**  
3) `python file_organizer.py`  
4) Answer the prompts:
   - **Dry-Run?** (safe preview)  
   - **Apply folder tree?** (No / Yes)  
   - If **Yes**, choose between:
     - **Reuse last folder tree** (uses `Logs/arbo_last.json`; Gemini only classifies & adds minimal subfolders if required)  
     - **Fresh tree** (ignore previous arbo; Gemini builds a new tree from the current batch)

> The script creates these folders on first run: `Input/`, `Output/`, `Failed/`, `Logs/`.  
> In apply runs, it also **removes `.gitkeep`** to keep things clean.

---

## 📂 Default Folders
```
Input/   -> put your files here
Output/  -> renamed / organized files
Failed/  -> files that failed or were left in Input
Logs/    -> summaries, errors, proposals, and saved arbo (arbo_last.json)
```

---

## 🧠 How “reuse last tree” works
- After a run with a tree, the plan is saved to `Logs/arbo_last.json` (+ versioned copies in `Logs/arbo_history/`).  
- On the next run, if you choose **Reuse last folder tree**, Gemini **classifies the new files into your existing arbo** and creates **tiny additions** (subfolders) **only if necessary**.  
- Prefer **Fresh tree** when you want to ignore the past and build a new structure based on the current batch only.

---

## 📜 License
MIT License © 2025 Ayoub ECHEHAB — https://www.ayoubechehab.com
