# Drug Repurposing App

A small Flask web application that demonstrates simple drug-repurposing support features:
- queries PubChem, ClinicalTrials.gov (and uses fallbacks) to retrieve molecular, trials and interaction information;
- computes a simple "confidence" score for repurposing using molecular/text similarity (RDKit optional);
- provides HTML views and a minimal JSON API;
- can generate a PDF report and supports a small comparison UI for multiple drugs.

This README documents installation, usage, architecture, endpoints, and contribution guidance based on the repository contents.

Table of contents
- Features
- Requirements
- Quick start (local)
- Environment variables & configuration
- Endpoints / Usage
- PDF generation format
- Caching and performance
- Deployment
- Project structure
- Development & contribution
- Troubleshooting
- Security & license

Features
- Search for a drug by name (UI and API).
- Confidence score for potential repurposing using:
  - molecular similarity (RDKit when installed, otherwise a fallback),
  - simple indication text similarity.
- Looks up molecular properties from PubChem, clinical trial summaries from ClinicalTrials.gov, and (mock) drug interactions.
- Generate a PDF report of results.
- Compare up to 3 drugs side-by-side.
- Simple in-memory caching for API results and computed scores.
- Procfile present for Heroku-style deployment using gunicorn.

Requirements
- Python 3.8+
- See pinned dependencies in requirements.txt:
  - Flask==2.3.3
  - reportlab==4.0.4
  - requests==2.31.0
  - gunicorn==21.2.0
  - Flask-Caching==2.1.0
- Optional (for improved molecular similarity):
  - RDKit (recommended, not required). If RDKit is not installed the app falls back to approximate similarity values.

Installing RDKit (optional)
- The easiest approach is conda:
  conda create -n rdkit-env -c conda-forge rdkit python=3.10
  conda activate rdkit-env
- Or follow RDKit installation instructions at: https://www.rdkit.org/docs/Install.html

Quick start — local development
1. Clone repository
   git clone https://github.com/LuqmanBinFahad/drug-repurposing-app.git
   cd drug-repurposing-app

2. Create and activate virtual environment
   python -m venv venv
   # macOS / Linux
   source venv/bin/activate
   # Windows (PowerShell)
   venv\Scripts\Activate.ps1

3. Install dependencies
   pip install -r requirements.txt

4. (Optional) Install RDKit in your environment if you want robust molecular similarity.

5. Run the app
   # Development
   python app.py
   # Or using flask CLI if preferred
   export FLASK_APP=app.py
   export FLASK_ENV=development
   flask run
   # Production (as in Procfile)
   gunicorn app:app

6. Open browser:
   http://127.0.0.1:5000/

Environment variables & configuration
- The app uses simple defaults and expects no special configuration to run, but in production you should set:
  - FLASK_ENV=production or development as appropriate
  - SECRET_KEY (if you add session usage)
- The app calls external APIs (PubChem, ClinicalTrials.gov). No API key is currently required for those calls, but check upstream changes if you rely on other services.
- RDKit presence is detected at runtime; if not installed the app prints a message and uses a fallback similarity.

Endpoints / Usage
HTML pages
- GET /  
  - Renders `index.html` (search form). The template expects cache stats and a simple form.

- POST /search  
  - Form field: `query` (drug name)  
  - Returns `results.html` with a list of results (drugs). Each result contains:
    - name
    - confidence (calculated)
    - indication (placeholder)
    - trials (from ClinicalTrials.gov or mock)
    - molecular (PubChem properties or fallback)
    - interactions (mock interaction list or fallback)

- GET, POST /compare  
  - POST: submit form fields `compare_drug_1`, `compare_drug_2`, ... up to 3
  - Renders `compare.html` showing side-by-side drug data and confidence scores.

API (JSON)
- GET /api/search?q=<drug_name>  
  - Returns a JSON array of simple results:
    [
      {
        "name": "<drug_name>",
        "confidence": <0-100>,
        "indication": "New therapeutic use"
      }
    ]
  - Useful for quick programmatic checks.

Admin / Utility
- POST /clear_cache  
  - Clears the in-memory cache. Returns JSON: { "status": "Cache cleared successfully" }

PDF generation
- POST /generate_pdf  
  - Expects JSON body with structure roughly:
    {
      "drugs": [
        {
          "name": "Aspirin",
          "confidence": 82,
          "indication": "Pain ...",
          "molecular": { "molecular_formula": "...", "molecular_weight": "...", ... },
          "trials": { "count": 2, "trials": [ ... ] },
          "interactions": [ ... ]
        },
        ...
      ]
    }
  - On success returns: { "filename": "drug_repurposing_report_<timestamp>.pdf" }
  - The PDF file is written into the repository `static/` directory (the app creates `static/` if missing).

Example curl usage
- Search (API):
  curl 'http://127.0.0.1:5000/api/search?q=Metformin'

- Generate PDF (example):
  curl -X POST 'http://127.0.0.1:5000/generate_pdf' \
    -H 'Content-Type: application/json' \
    -d '{"drugs":[{"name":"Metformin","confidence":75}]}'

Notes on algorithmic behavior
- Confidence score calculation (see app.py):
  - Fetches canonical SMILES from PubChem when available.
  - If RDKit is installed: calculates Morgan fingerprints and Tanimoto similarity.
  - Also computes a simple Jaccard text similarity between known indications.
  - Weighted combination:
    - molecular similarity weight: 0.6
    - text similarity weight: 0.3
    - base: 0.1
  - Score is normalized to 0–100 and cached for 24 hours.
- Fallback behavior: when APIs fail or RDKit is not present the app returns plausible mock data and fallback scores to keep the UI responsive.

Caching and performance
- Flask-Caching with SimpleCache (in-memory) is used.
- Important caches and timeouts from code:
  - calculate_confidence_score: cached 24 hours (86400 sec)
  - search_pubchem: cached 7 days (604800 sec)
  - search_clinical_trials: cached 24 hours (86400 sec)
  - search_drug_interactions: cached 7 days (604800 sec)
- SimpleCache is ephemeral — in production use a shared cache like Redis for multi-worker setups.

Deployment
- Procfile: `web: gunicorn app:app` — ready for Heroku/Render style deployment.
- For production you should:
  - Use gunicorn with multiple workers: e.g., `gunicorn -w 4 app:app`
  - Use a proper WSGI server and reverse proxy (nginx) if needed.
  - Use an external cache (Redis) and persistent storage for large assets.
- Optional Dockerfile (example pattern):
  FROM python:3.10-slim
  WORKDIR /app
  COPY requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt
  COPY . .
  CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8080"]

Project structure (what's present)
- app.py                # Main Flask application (routes, caching, API calls, PDF generation)
- requirements.txt      # Pinned Python packages
- Procfile              # Heroku gunicorn starter
- templates/            # Jinja2 templates (index.html, results.html, compare.html referenced in app.py)
- static/               # Static assets and generated PDFs (created at runtime if missing)

Development & contribution
- Coding style: follow PEP8.
- Tests: add pytest tests under a `tests/` folder (not present currently).
- Branch and PR workflow: feature branches, then open PR to `main`.
- Contributing checklist for PRs:
  - Add tests for new behavior.
  - Update README and inline docs if behavior changes.
  - Ensure no secrets are committed.

Troubleshooting & notes
- If PubChem or ClinicalTrials API calls fail you will see fallback/mock data; check network connectivity and upstream service availability.
- If RDKit is not installed you’ll see: "RDKit not available. Using fallback similarity method." Install RDKit via conda to enable real molecular similarity.
- Generated PDF files are placed in `static/`. Ensure the app process has write permissions for that folder.
- The app currently runs with `debug=True` when run via `python app.py`. Switch to `debug=False` in production and configure logging.

Security & data privacy
- Do not commit secrets (API keys, credentials).
- If you add third-party datasets or real patient data, ensure proper de-identification and legal compliance.

License
- No explicit license file is present in the repository. Add a LICENSE file (e.g., MIT, Apache-2.0) to clarify reuse terms.
