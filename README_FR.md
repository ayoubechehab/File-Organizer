# 📂 File Organizer (v1.0.0)
![Terminal Preview](./file_organizer_terminal_preview.png)
Organisateur de documents intelligent propulsé par **Google Gemini API**.  
Analyse le contenu, **renomme** les fichiers et (optionnellement) **organise** dans une **arborescence** — interface, prompts et arbo **FR/EN**.

## ✨ Fonctionnalités
- **FR/EN** au choix au démarrage (affichage console, prompts Gemini, arbo finale).
- **Renommage intelligent** basé sur le contenu (date incluse si détectée).
- **Arbo optimisée** : normalisation (synonymes/accents), **limite de racines**, repli des racines en trop sous **Divers/Misc**, ajout de **sous-dossiers minimaux** seulement si nécessaire.
- **Réutilisation d’arbo** : reclasse de nouveaux fichiers selon `Logs/arbo_last.json`.
- **OCR fallback** :
  - PDF : extraction texte → si insuffisant, OCR (Poppler + `pdf2image` + `pytesseract`).
  - DOCX : OCR d’images intégrées si texte quasi nul.
  - Images (JPG/PNG/TIFF…) : OCR via `pytesseract`.
- **Sécurité de fin** : tout ce qui reste dans `Input/` → `Failed/` (en **conservant le sous-chemin**), puis **suppression des dossiers vides**.
- **Logs complets** et historiques (propositions, erreurs, résumé, arbo utilisée).

---

## 📦 Prérequis

### 1) Python & dépendances
- **Python 3.9+** recommandé
- Installez les libs Python :
```bash
pip install -r requirements.txt
```

### 2) Tesseract (OCR images & DOCX)
- **Windows** : télécharger l’installateur (Google “tesseract windows installer”), ensuite ajoutez le chemin de `tesseract.exe` au `PATH` si besoin.
- **macOS** :  
  ```bash
  brew install tesseract
  ```
- **Linux (Debian/Ubuntu)** :  
  ```bash
  sudo apt-get update
  sudo apt-get install tesseract-ocr
  ```

> Conseil : installez aussi les packs linguistiques utiles (ex. `tesseract-ocr-fra` pour le français).

### 3) Poppler (OCR des PDF scannés)
- **Windows** : télécharger “Poppler for Windows”, dézipper, ajouter le dossier `bin` au `PATH`.
- **macOS** :  
  ```bash
  brew install poppler
  ```
- **Linux (Debian/Ubuntu)** :  
  ```bash
  sudo apt-get install poppler-utils
  ```

> Sans Poppler, l’OCR **PDF** n’est pas possible (les PDF purement scannés finiront en *Failed*). L’OCR **images** marche quand même (Tesseract).

---

## 🔑 Clé API Gemini
- Ouvrez **`api_key.txt`** et **collez** votre clé (ex. `sk-...`).  
- Alternativement : exportez `GEMINI_API_KEY` dans vos variables d’environnement ou passez `--api` au script.

---

## 🚀 Utilisation

1. Placez vos fichiers dans **`Input/`**.  
2. Lancez :
   ```bash
   python file_organizer.py
   ```
3. Suivez les questions :
   - **FR ou EN** (pilote interface, prompts et arbo)
   - Dossiers (Input/Output/Failed/Logs) — laissez les valeurs par défaut si OK
   - **Dry-Run** (aperçu sans modifier) ou **Apply** (appliquer)
   - Option **arbo** (proposer ou appliquer)
   - Option **réutiliser l’arbo précédente** (si `Logs/arbo_last.json` existe)

### Modes
- **Dry-Run :**
  - Génère les **propositions de renommage** (`Logs/rename_proposals_*.xlsx`)  
  - Si arbo demandée : **plan de classement** (`Logs/arbo_mapping_*.xlsx`)  
  - Écrit un **state** réutilisable (`Logs/dryrun_state_*.json`) pour appliquer **sans regénérer via API**  
  - Possibilité d’**appliquer directement** les propositions à la fin du dry-run

- **Apply (run réel) :**
  - Renomme les fichiers et les **déplace dans `Output/`**
  - Si arbo activée : crée la structure et **classe** dans les bons sous-dossiers
  - Écrit `Logs/arbo_last.json` (réutilisable la prochaine fois)
  - Déplace les fichiers non traités / restants vers **`Failed/`** en **conservant le sous-chemin**
  - **Supprime** les dossiers **vides** de `Input/`
  - Supprime les `.gitkeep` (pour garder des dossiers “propres” côté utilisateur)

---

## 📁 Dossiers
- **Input/** : déposez vos fichiers à traiter  
- **Output/** : fichiers renommés / organisés  
- **Failed/** : erreurs & restes, **sous-chemin conservé**  
- **Logs/** :  
  - `run_summary_*.txt` (résumé, tokens IN/OUT, coût estimé)  
  - `errors_*.xlsx` (raison des échecs et restes)  
  - `rename_proposals_*.xlsx` (dry-run)  
  - `arbo_mapping_*.xlsx` (dry-run + arbo)  
  - `dryrun_state_*.json` (pour appliquer sans nouvel appel API)  
  - `arbo_last.json` & `arbo_history/*` (arbo utilisée — réutilisable)

---

## 🧠 Comment ça marche (simplifié)
1. **Extraction du texte** (PDF/DOCX/Excel/Images).  
   - Si texte insuffisant, **OCR** (Images toujours ; PDF si Poppler dispo ; DOCX → OCR des images intégrées).  
2. **Gemini titre** : propose un **titre concis** (+ date si trouvée).  
3. **Renommage** : `YYYY-MM-DD_Titre.ext` (si date) ou `Titre.ext`.  
4. **Arbo** (si activée) :
   - **Fresh** : propose une arbo FR/EN propre (racines limitées, pas de doublons/synonymes).  
   - **Reuse** : reclasse dans **l’ancienne arbo**, n’ajoute des sous-dossiers que si nécessaire.  
5. **Sécurité de fin** : tout ce qui reste dans `Input/` part en **Failed/** (sous-chemin conservé), puis suppression des **dossiers vides**.

---

## 💰 Coût & tokens
- Le script affiche en fin de run :
  - **Tokens IN/OUT** (estimation)
  - **Coût estimé** basé sur le modèle (`gemini-1.5-flash` par défaut, barème dans le code `PRICING`).

---

## 🔐 Confidentialité
- Le traitement est local ; seules des **sous-parties de texte** nécessaires sont envoyées à Gemini pour titrage et classement.

---

## ❓ FAQ

**Q. Puis-je utiliser uniquement le renommage sans arbo ?**  
Oui. Choisissez *Apply* et **désactivez** l’arbo, les fichiers renommés iront tous dans `Output/`.

**Q. Comment rejouer un dry-run sans consommer plus d’API ?**  
Utilisez le **`dryrun_state_*.json`** généré : le script propose d’appliquer les propositions **sans nouvel appel** à Gemini.

**Q. Je veux une arbo en FR mais garder des titres en EN (ou inversement) ?**  
Le script respecte la logique :  
- Documents EN → titres **EN** ;  
- Documents FR → titres **FR** ;  
- Documents AR → titres **FR** (par défaut) ;  
L’**arbo** suit la **langue choisie** au début (FR/EN).

**Q. PDF scannés non traités ?**  
Installez **Poppler** (voir *Prérequis*) pour activer l’OCR des PDF. Sans Poppler, les PDF purement images finiront en *Failed*.

**Q. Où modifier la liste des racines suggérées / alias de normalisation ?**  
Dans le code : `SUGGESTED_ROOTS_FR/EN` et `ALIAS_MAP_FR/EN`.

---

## 🧩 Dépannage

- **`poppler not found` / OCR PDF KO**  
  → Installez Poppler (voir *Prérequis*), redémarrez le terminal, vérifiez que `pdftoppm`/`pdftocairo` sont dans le `PATH`.

- **`tesseract not found`**  
  → Installez Tesseract (voir *Prérequis*) et ajoutez au `PATH`. Sur Windows, rouvrez le terminal après installation.

- **Erreur JSON côté LLM**  
  → Le script enregistre la **réponse brute** dans `Logs/llm_raw_*.txt`. Le parseur applique des “fixes” doux, sinon dry-run fournit toujours les propositions.

- **Certains fichiers restent dans Input**  
  → En fin de run, tout est **balayé vers `Failed/`** et les dossiers vides sont **supprimés**. Consultez `Logs/errors_realrun_*.xlsx`.

---

## 🧑‍💻 Crédits
- Auteur : **Ayoub ECHEHAB**  
- Website : https://www.ayoubechehab.com  
- GitHub  : https://github.com/ayoubechehab  
- Licence : **MIT**
