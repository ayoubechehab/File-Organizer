# 📂 File Organizer

**File Organizer** is a smart document organizer powered by [Google Gemini API](https://ai.google.dev).  
It analyzes file content and automatically proposes or applies meaningful filenames and folder structures.

---

## ✨ Features
- 🔍 **Content-aware renaming** (PDF, DOCX, Excel, scanned images)
- 📝 **Dry-run mode**: safe preview of rename & folder proposals
- 📁 **Folder tree organization**: optional recommended structure
- ⚠️ **Error handling**:
  - Dry-run → logs skipped/failed in `Logs/`
  - Real run → moves problematic files to `Failed/`
- 📊 **Cost estimation**: token usage + estimated API cost
- 📂 **Clean Output**: only final user files
- 📑 **Logs**: proposals, mapping, errors, and dryrun state in `Logs/`

---

## 📂 Folder Structure
```
Input/   -> put your files here
Output/  -> renamed / organized files
Failed/  -> files that failed in real run
Logs/    -> rename proposals, folder mappings, errors, dryrun state
```

---

## 🚀 Usage

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set your Gemini API key
- Open the file `api_key.txt` and paste your key inside:
  ```
  sk-xxxxxx
  ```

### 3. Run
```bash
python file_organizer.py
```

### 4. Workflow
- The script will ask:
  - **Dry-run?** → Generate proposals only, logs in `Logs/`
  - If dry-run → Also generate folder tree proposal?
  - If real run → Apply folder tree or rename-only?

- After dry-run, check the generated Excel in `Logs/`.  
  If satisfied, you can apply immediately (0 extra API calls).

---

## 📊 Example Summary
```
===== SUMMARY (dry-run) =====
Tokens IN          : 23,415
Tokens OUT         : 2,103
Estimated cost     : $0.0035
Logs folder        : ./Logs
Rename proposals   : ./Logs/rename_proposals_20250301.xlsx
Recommended tree   : ./Logs/arbo_mapping_20250301.xlsx
Error log          : ./Logs/errors_20250301.xlsx
Saved state        : ./Logs/dryrun_state_20250301.json

Apply these proposals now (no extra API calls)? (y/N):
```

---

## ❓ FAQ

**Q: Does dry-run cost tokens?**  
Yes. Dry-run still calls Gemini to generate proposals. The "no extra API calls" applies only when you choose to apply those saved results.

**Q: Which files are supported?**  
- PDF, DOCX, XLSX/XLS, JPG/PNG/TIFF/BMP/WEBP (OCR).  
- `.txt` and other raw text are intentionally excluded.

**Q: Where are logs saved?**  
- In `./Logs`: rename proposals, tree mapping, errors, dryrun state JSON.

**Q: What happens to failed files?**  
- Dry-run: listed in `Logs/errors_*.xlsx`.  
- Real run: moved to `./Failed`.

---

## 🛠 Requirements
- Python 3.9+  
- Google Gemini API key  

---

## 📜 License
MIT License © 2025 Ayoub ECHEHAB

---

## 👤 Author
**Ayoub ECHEHAB**  
🌐 [www.ayoubechehab.com](https://www.ayoubechehab.com)  
💼 [LinkedIn](https://www.linkedin.com/in/ayoubechehab)
