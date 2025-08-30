# 📂 File Organizer (v1.0.0)
![Terminal Preview](./file_organizer_terminal_preview.png)
[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)  
[![License MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)  
[![Gemini](https://img.shields.io/badge/Gemini%20API-integrated-orange.svg)](https://ai.google.dev/)

Smart document organizer powered by **Google Gemini API**.  
Analyzes file content, **renames** files, and (optionally) **organizes** them into a structured **folder tree** — works in **English** and **French**.

---

## 🌍 Documentation

- 🇬🇧 You are reading the **English documentation** (main README).  
- 🇫🇷 [Lire la documentation en Français](./README_FR.md)

---

## 📸 Preview

### Terminal Preview
![Terminal Preview](./file_organizer_terminal_preview.png)

---

## ✨ Key Features

- **Bilingual support (EN/FR)**  
  Choose your language at startup — console messages, Gemini prompts, and folder tree adapt.

- **Content-aware renaming**  
  Generates meaningful filenames based on extracted content, includes detected dates.

- **Smart folder tree**  
  Optimized categories, limited roots, no duplicates/synonyms, fallback to `Misc/Divers`.

- **Re-use last folder tree**  
  Ensures consistent classification across runs. Minimal new subfolders added only when needed.

- **OCR fallback**  
  - Scanned PDFs (requires Poppler + pdf2image + Tesseract)  
  - Images (JPG/PNG/TIFF…) → OCR with Tesseract  
  - DOCX embedded images → OCR fallback if text is missing  

- **Safe & clean execution**  
  - Leftovers in `Input/` → moved to `Failed/` (subpath preserved)  
  - Empty input folders automatically deleted  
  - `.gitkeep` files removed in real runs (keeps clean structure for end-users)

- **Comprehensive logs**  
  - Rename proposals (dry-run)  
  - Error logs with reasons  
  - Run summary with token usage & estimated cost  
  - Last used tree saved (`arbo_last.json`) and reusable

---

## 📁 Folder Structure

```
Input/   → files to process
Output/  → renamed/organized files
Failed/  → errors & leftovers (subpaths preserved)
Logs/    → reports, proposals, errors, last folder trees
```

---

## 🔑 Setup

- Python 3.9+  
- Install dependencies:  
  ```bash
  pip install -r requirements.txt
  ```
- Install **Tesseract** for OCR (images, DOCX).  
- Install **Poppler** for OCR on scanned PDFs (optional but recommended).  

Paste your Gemini API key inside `api_key.txt`.

---

## 🚀 Quick Start

1. Place your files in **`Input/`**.  
2. Run:
   ```bash
   python file_organizer.py
   ```
3. Follow the interactive prompts:
   - Choose **EN or FR**  
   - Dry-run or Apply  
   - Folder tree enabled or not  
   - Reuse last tree or generate fresh  

---

## 🧑‍💻 Author

- **Ayoub ECHEHAB**  
- 🌐 [Website](https://www.ayoubechehab.com)  
- 💻 [GitHub](https://github.com/ayoubechehab)  
- 📜 License: **MIT**
