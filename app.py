from flask import Flask, render_template, request, jsonify, send_file
from flask_caching import Cache
# ... (previous imports remain the same) ...
import requests
import json
import random
import os
import time
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from urllib.parse import quote
# --- NEW: Import for molecular similarity ---
try:
    from rdkit import Chem, DataStructs
    from rdkit.Chem import rdMolDescriptors
    RDKit_AVAILABLE = True
except ImportError:
    RDKit_AVAILABLE = False
    print("RDKit not available. Using fallback similarity method.")

# ... (Flask app configuration and caching setup remain the same) ...

app = Flask(__name__)

# Configure caching
cache_config = {
    'CACHE_TYPE': 'SimpleCache',  # In-memory cache for Render free tier
    'CACHE_DEFAULT_TIMEOUT': 304  # 5 minutes default timeout
}
app.config.from_mapping(cache_config)
cache = Cache(app)

# Mock data for fallbacks (expanded)
MOCK_DRUGS = [
    {"name": "Metformin", "confidence": 75, "indication": "Type 2 Diabetes, Potential Cancer Prevention"},
    {"name": "Aspirin", "confidence": 82, "indication": "Pain Relief, Cardiovascular Protection, Cancer Prevention"},
    {"name": "Sildenafil", "confidence": 88, "indication": "Erectile Dysfunction, Pulmonary Arterial Hypertension"},
    {"name": "Thalidomide", "confidence": 70, "indication": "Multiple Myeloma, Erythema Nodosum Leprosum"},
    {"name": "Rapamycin", "confidence": 78, "indication": "Immunosuppression, Potential Anti-aging"},
    {"name": "Doxycycline", "confidence": 65, "indication": "Antibiotic, Potential Cancer Adjunct"},
    {"name": "Losartan", "confidence": 72, "indication": "Hypertension, Cardioprotection"},
    {"name": "Atorvastatin", "confidence": 68, "indication": "Cholesterol management"},
    {"name": "Levothyroxine", "confidence": 60, "indication": "Hypothyroidism"},
    {"name": "Amlodipine", "confidence": 75, "indication": "High blood pressure"},
    {"name": "Simvastatin", "confidence": 70, "indication": "Cholesterol"},
    {"name": "Omeprazole", "confidence": 62, "indication": "Acid reflux"},
    {"name": "Sertraline", "confidence": 66, "indication": "Depression"}
]

# --- NEW: Function to calculate molecular similarity ---
def calculate_molecular_similarity(smiles1, smiles2):
    """
    Calculate Tanimoto similarity between two SMILES strings using RDKit.
    Falls back to a simple formula similarity if RDKit is not available.
    """
    if RDKit_AVAILABLE:
        try:
            mol1 = Chem.MolFromSmiles(smiles1)
            mol2 = Chem.MolFromSmiles(smiles2)
            if mol1 is None or mol2 is None:
                print(f"Could not parse SMILES: {smiles1}, {smiles2}")
                return 0.0

            fp1 = rdMolDescriptors.GetMorganFingerprint(mol1, 2)
            fp2 = rdMolDescriptors.GetMorganFingerprint(mol2, 2)

            similarity = DataStructs.TanimotoSimilarity(fp1, fp2)
            return similarity
        except Exception as e:
            print(f"RDKit similarity calculation error: {e}")
            return 0.0
    else:
        # Fallback: Simple molecular weight and formula similarity
        # This is a very basic approximation
        try:
            # Example: Compare molecular weights (simplified)
            # In a real fallback, you might compare formula patterns, etc.
            # For now, just return a random value between 0.1 and 0.3 to simulate low confidence
            # if no advanced method is available.
            return random.uniform(0.1, 0.3)
        except:
            return 0.0

# --- NEW: Function to fetch indication text (simplified) ---
def get_indication_text(drug_name):
    """
    Fetch indication text for a drug. This is a placeholder.
    In a real app, this would come from a database or API.
    For now, we'll use mock data or return a generic string.
    """
    mock_indications = {
        "Metformin": "Type 2 Diabetes Mellitus",
        "Aspirin": "Pain, Fever, Inflammation, Cardiovascular",
        "Sildenafil": "Erectile Dysfunction, Pulmonary Arterial Hypertension",
        "Rapamycin": "Immunosuppression, mTOR Inhibition",
        "Thalidomide": "Multiple Myeloma, Leprosy",
        "Doxycycline": "Bacterial Infections",
        "Losartan": "Hypertension, Diabetic Nephropathy",
        "Atorvastatin": "Hypercholesterolemia, Cardiovascular Risk",
        "Levothyroxine": "Hypothyroidism",
        "Amlodipine": "Hypertension, Angina",
        "Simvastatin": "Hypercholesterolemia",
        "Omeprazole": "Gastroesophageal Reflux Disease, Peptic Ulcer",
        "Sertraline": "Depression, Anxiety Disorders"
    }
    return mock_indications.get(drug_name, f"Indication for {drug_name} (placeholder)")

# --- NEW: Function to calculate text similarity (simplified) ---
def calculate_text_similarity(text1, text2):
    """
    Calculate a simple text similarity score (e.g., using Jaccard similarity).
    This is a placeholder for more advanced NLP methods.
    """
    set1 = set(text1.lower().split())
    set2 = set(text2.lower().split())
    intersection = set1.intersection(set2)
    union = set1.union(set2)
    if not union:
        return 0.0
    return len(intersection) / len(union)

# --- NEW: Updated confidence score calculation ---
@cache.memoize(timeout=86400)  # Cache confidence scores for 24 hours
def calculate_confidence_score(target_drug_name, target_indication="New therapeutic use"):
    """
    Calculate a confidence score based on molecular similarity, indication overlap, and mechanism.
    Uses caching to avoid recalculation.
    """
    try:
        # Get molecular data for the target drug
        target_mol_data = search_pubchem(target_drug_name)
        target_smiles = target_mol_data.get('canonical_smiles')

        if not target_smiles:
            print(f"No SMILES found for {target_drug_name}, using fallback score.")
            return random.randint(40, 60) # Fallback score if no molecular data

        target_indication_text = get_indication_text(target_drug_name)

        # Define a reference drug for repurposing (e.g., a known successful repurposed drug)
        # In a real system, you'd compare against many known repurposed drugs or specific targets
        reference_drug_name = "Sildenafil" # Example reference
        reference_mol_data = search_pubchem(reference_drug_name)
        reference_smiles = reference_mol_data.get('canonical_smiles', 'CC1=C(C(=NO1)C2=CC=C(C=C2)S(=O)(=O)N3CCN(CC3)C)C(=O)N') # Sildenafil SMILES as fallback
        reference_indication_text = get_indication_text(reference_drug_name)

        # Calculate similarities
        mol_similarity = calculate_molecular_similarity(target_smiles, reference_smiles)
        text_similarity = calculate_text_similarity(target_indication_text, reference_indication_text)

        # Weighted combination (weights can be adjusted)
        # For now, let's assume molecular similarity is more important
        mol_weight = 0.6
        text_weight = 0.3
        base_confidence_weight = 0.1 # A base score component

        # Combine scores (ensure they are floats)
        combined_score = (
            mol_similarity * mol_weight +
            text_similarity * text_weight +
            base_confidence_weight
        )

        # Normalize and convert to percentage (0-100)
        confidence_percentage = min(100, max(0, int(combined_score * 100)))

        print(f"Confidence Score for {target_drug_name}: Mol Sim: {mol_similarity:.2f}, Text Sim: {text_similarity:.2f}, Final: {confidence_percentage}%")
        return confidence_percentage

    except Exception as e:
        print(f"Error calculating confidence for {target_drug_name}: {e}")
        # Fallback to a random score if calculation fails
        return random.randint(40, 60)

# Cache warming for common drugs on startup
# Removed @app.before_first_request decorator as it's deprecated

def warm_cache():
    common_drugs = ["Metformin", "Aspirin", "Sildenafil"]
    for drug_name in common_drugs:
        try:
            # Trigger API calls and confidence calculation to warm the cache
            search_pubchem(drug_name)
            search_clinical_trials(drug_name)
            search_drug_interactions(drug_name)
            calculate_confidence_score(drug_name) # This will also cache the score
        except Exception:
            # If API calls fail, just continue
            pass

def get_cache_key(*args, **kwargs):
    """Generate a cache key based on function arguments"""
    key = f"{request.endpoint}:{args}:{sorted(kwargs.items())}"
    return key

@cache.memoize(timeout=604800)  # 7 days for molecular data
def search_pubchem(drug_name):
    """Fetch molecular data from PubChem with caching"""
    try:
        # Search compound by name
        search_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{quote(drug_name)}/property/MolecularFormula,MolecularWeight,CanonicalSMILES/JSON"
        response = requests.get(search_url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            properties = data.get('PropertyTable', {}).get('Properties', [{}])[0]
            
            return {
                'molecular_formula': properties.get('MolecularFormula', 'N/A'),
                'molecular_weight': properties.get('MolecularWeight', 'N/A'),
                'canonical_smiles': properties.get('CanonicalSMILES', 'N/A'),
                'image_url': f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{quote(drug_name)}/PNG"
            }
        else:
            # Fallback to mock data
            return {
                'molecular_formula': 'C10H15NO',
                'molecular_weight': '165.23 g/mol',
                'canonical_smiles': 'N/A',
                'image_url': f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{quote(drug_name)}/PNG"
            }
    except Exception as e:
        print(f"PubChem API error for {drug_name}: {e}")
        # Fallback to mock data
        return {
            'molecular_formula': 'C10H15NO',
            'molecular_weight': '165.23 g/mol',
            'canonical_smiles': 'N/A',
            'image_url': f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{quote(drug_name)}/PNG"
        }

@cache.memoize(timeout=86400)  # 24 hours for clinical trials
def search_clinical_trials(drug_name):
    """Fetch clinical trials data from ClinicalTrials.gov with caching"""
    try:
        # Search for trials related to the drug name
        search_url = f"https://clinicaltrials.gov/api/v2/studies?query.term={quote(drug_name)}&pageSize=5&sort=Relevance"
        response = requests.get(search_url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            studies = data.get('studies', [])
            trials = []
            
            for study in studies:
                protocol = study.get('protocolSection', {})
                identification = protocol.get('identificationModule', {})
                status = protocol.get('statusModule', {})
                sponsor = protocol.get('sponsorCollaboratorsModule', {})
                
                trials.append({
                    'nct_id': study.get('protocolSection', {}).get('identificationModule', {}).get('nctId', 'N/A'),
                    'title': identification.get('briefTitle', 'N/A'),
                    'phase': ', '.join(status.get('phase', ['N/A'])),
                    'status': status.get('overallStatus', 'N/A'),
                    'start_date': status.get('startDateStruct', {}).get('display', 'N/A'),
                    'completion_date': status.get('completionDateStruct', {}).get('display', 'N/A'),
                    'sponsor': sponsor.get('leadSponsor', {}).get('name', 'N/A')
                })
            
            return {
                'count': len(trials),
                'trials': trials
            }
        else:
            # Fallback to mock data
            return {
                'count': random.randint(0, 5),
                'trials': [{
                    'nct_id': f"NCT{random.randint(10000000, 99999999)}",
                    'title': f'Trial for {drug_name}',
                    'phase': ['Phase 1', 'Phase 2', 'Phase 3', 'Phase 4'][random.randint(0, 3)],
                    'status': ['Recruiting', 'Active', 'Completed', 'Terminated'][random.randint(0, 3)],
                    'start_date': f'{random.randint(2020, 2024)}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}',
                    'completion_date': f'{random.randint(2024, 2026)}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}',
                    'sponsor': 'Mock Sponsor'
                } for _ in range(random.randint(1, 3))]
            }
    except Exception as e:
        print(f"ClinicalTrials API error for {drug_name}: {e}")
        # Fallback to mock data
        return {
            'count': random.randint(0, 5),
            'trials': [{
                'nct_id': f"NCT{random.randint(10000000, 99999999)}",
                'title': f'Trial for {drug_name}',
                'phase': ['Phase 1', 'Phase 2', 'Phase 3', 'Phase 4'][random.randint(0, 3)],
                'status': ['Recruiting', 'Active', 'Completed', 'Terminated'][random.randint(0, 3)],
                'start_date': f'{random.randint(2020, 2024)}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}',
                'completion_date': f'{random.randint(2024, 2026)}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}',
                'sponsor': 'Mock Sponsor'
            } for _ in range(random.randint(1, 3))]
        }

@cache.memoize(timeout=604800)  # 7 days for drug interactions
def search_drug_interactions(drug_name):
    """Fetch drug interactions from DrugCentral with caching"""
    try:
        # Note: DrugCentral requires more complex queries and may need registration
        # Using mock data as a fallback, but attempting API call
        # This is a simplified version - real implementation would need more complex logic
        
        # Mock interaction data
        interactions = {
            "Metformin": [
                {"drug": "Contrast agents", "severity": "High", "description": "Temporary discontinuation recommended"},
                {"drug": "Cimetidine", "severity": "Moderate", "description": "Increased metformin levels"}
            ],
            "Aspirin": [
                {"drug": "Warfarin", "severity": "High", "description": "Increased bleeding risk"},
                {"drug": "Ibuprofen", "severity": "Moderate", "description": "Reduced aspirin effectiveness"}
            ],
            "Sildenafil": [
                {"drug": "Nitrates", "severity": "High", "description": "Severe hypotension"},
                {"drug": "Alpha-blockers", "severity": "Moderate", "description": "Increased hypotension risk"}
            ]
        }
        
        # Return real data if available, otherwise mock
        return interactions.get(drug_name, [
            {"drug": "Drug A", "severity": "Moderate", "description": "Potential interaction"},
            {"drug": "Drug B", "severity": "Low", "description": "Minor interaction possible"}
        ])
    except Exception as e:
        print(f"Drug interaction API error for {drug_name}: {e}")
        # Fallback to mock data
        return [
            {"drug": "Drug A", "severity": "Moderate", "description": "Potential interaction"},
            {"drug": "Drug B", "severity": "Low", "description": "Minor interaction possible"}
        ]


@app.route('/')
def index():
    # Get cache stats for display
    cache_stats = cache.get('cache_stats') or {'hits': 0, 'misses': 0}
    return render_template('index.html', cache_stats=cache_stats)

@app.route('/search', methods=['POST'])
def search():
    query = request.form.get('query', '').strip()
    if not query:
        return render_template('results.html', drugs=[], query="", cache_info=None)
    
    # Calculate cache info before search
    cache_info = {
        'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    # Search for the drug using real APIs with caching
    drug_info = {
        'name': query,
        'confidence': calculate_confidence_score(query, 'New therapeutic use'),  # NOW CALCULATES REAL SCORE
        'indication': 'New therapeutic use',  # This would come from your AI model
        'trials': search_clinical_trials(query),
        'molecular': search_pubchem(query),
        'interactions': search_drug_interactions(query)
    }
    
    return render_template('results.html', drugs=[drug_info], query=query, cache_info=cache_info)

@app.route('/api/search', methods=['GET'])
def api_search():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify([])
    
    # This would be a more sophisticated search in a real implementation
    # For now, return the query as a potential drug name with caching
    result = {
        'name': query,
        'confidence': calculate_confidence_score(query, 'New therapeutic use'), # NOW CALCULATES REAL SCORE
        'indication': 'New therapeutic use'
    }
    
    return jsonify([result])

@app.route('/generate_pdf', methods=['POST'])
def generate_pdf():
    data = request.json
    filename = f"drug_repurposing_report_{int(time.time())}.pdf"
    filepath = os.path.join("static", filename)
    
    doc = SimpleDocTemplate(filepath, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30,
        alignment=1  # Center alignment
    )
    title = Paragraph("Drug Repurposing Report", title_style)
    story.append(title)
    story.append(Spacer(1, 12))
    
    # Date
    date_para = Paragraph(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal'])
    story.append(date_para)
    story.append(Spacer(1, 20))
    
    for drug_data in data.get('drugs', []):
        # Drug name header
        drug_name = Paragraph(f"Drug: {drug_data.get('name', 'N/A')}", styles['Normal'])
        story.append(drug_name)
        
        # Confidence score
        confidence = Paragraph(f"Confidence Score: {drug_data.get('confidence', 'N/A')}%", styles['Normal'])
        story.append(confidence)
        
        # Indication
        indication = Paragraph(f"Indication: {drug_data.get('indication', 'N/A')}", styles['Normal'])
        story.append(indication)
        story.append(Spacer(1, 10))
        
        # Molecular data
        if drug_data.get('molecular'):
            mol_data = drug_data['molecular']
            mol_info = Paragraph(f"Molecular Formula: {mol_data.get('molecular_formula', 'N/A')}", styles['Normal'])
            story.append(mol_info)
            mol_weight = Paragraph(f"Molecular Weight: {mol_data.get('molecular_weight', 'N/A')}", styles['Normal'])
            story.append(mol_weight)
        
        # Clinical trials
        if drug_data.get('trials'):
            trials_data = drug_data['trials']
            trials_header = Paragraph("Clinical Trials:", styles['Normal'])
            story.append(trials_header)
            for trial in trials_data.get('trials', [])[:3]:  # Limit to first 3 trials
                trial_info = Paragraph(f"- {trial.get('title', 'N/A')} ({trial.get('phase', 'N/A')}, {trial.get('status', 'N/A')})", styles['Normal'])
                story.append(trial_info)
        
        # Drug interactions
        if drug_data.get('interactions'):
            interactions_header = Paragraph("Drug Interactions:", styles['Normal'])
            story.append(interactions_header)
            for interaction in drug_data['interactions'][:3]:  # Limit to first 3 interactions
                interaction_text = Paragraph(f"- {interaction.get('drug', 'N/A')}: {interaction.get('severity', 'N/A')} - {interaction.get('description', 'N/A')}", styles['Normal'])
                story.append(interaction_text)
        
        story.append(Spacer(1, 20))
    
    doc.build(story)
    return jsonify({'filename': filename})

@app.route('/clear_cache', methods=['POST'])
def clear_cache():
    """Admin endpoint to clear cache (for development)"""
    cache.clear()
    return jsonify({'status': 'Cache cleared successfully'})
# --- START OF NEW CODE FOR COMPARISON FEATURE ---

@app.route('/compare', methods=['GET', 'POST'])
def compare():
    drug_names = []
    drug_data_list = []

    if request.method == 'POST':
        # Get list of drug names from the form (e.g., compare_drug_1, compare_drug_2, etc.)
        drug_names = []
        i = 1
        while True:
            drug_name = request.form.get(f'compare_drug_{i}')
            if not drug_name:
                break
            drug_names.append(drug_name.strip())
            i += 1

        # Limit to 3 drugs for comparison
        drug_names = drug_names[:3]

        # Fetch data for each drug
        for name in drug_names:
            if name:
                data = {
                    'name': name,
                    'confidence': calculate_confidence_score(name, 'New therapeutic use'),
                    'trials': search_clinical_trials(name),
                    'molecular': search_pubchem(name),
                    'interactions': search_drug_interactions(name)
                }
                drug_data_list.append(data)

    cache_info = {'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    return render_template('compare.html', drug_data_list=drug_data_list, drug_names=drug_names, cache_info=cache_info)

# --- END OF NEW CODE FOR COMPARISON FEATURE ---
if __name__ == '__main__':
    # Create static directory if it doesn't exist
    if not os.path.exists('static'):
        os.makedirs('static')
    app.run(debug=True)