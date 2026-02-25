import csv
import os

KNOWN_MEDICATIONS = [
    # Pain relievers & Fever reducers
    "acetaminophen", "paracetamol", "ibuprofen", "naproxen", "diclofenac",
    "celecoxib", "meloxicam", "ketorolac", "indomethacin", "piroxicam",
    "aspirin", "tylenol", "advil", "motrin", "aleve", "panadol", "excedrin",
    
    # Antibiotics
    "amoxicillin", "azithromycin", "ciprofloxacin", "doxycycline", "cephalexin",
    "clindamycin", "metronidazole", "sulfamethoxazole", "trimethoprim",
    "levofloxacin", "penicillin", "augmentin", "keflex", "bactrim", "zithromax",
    "cefdinir", "nitrofurantoin", "vancomycin", "gentamicin", "erythromycin",
    
    # Blood pressure medications
    "lisinopril", "amlodipine", "losartan", "metoprolol", "atenolol",
    "hydrochlorothiazide", "furosemide", "spironolactone", "valsartan",
    "candesartan", "propranolol", "carvedilol", "nifedipine", "diltiazem",
    "verapamil", "ramipril", "quinapril", "benazepril", "clonidine",
    "hydralazine", "minoxidil", "prazosin", "terazosin", "doxazosin",
    
    # Cholesterol medications
    "atorvastatin", "simvastatin", "rosuvastatin", "pravastatin", "lovastatin",
    "pitavastatin", "fluvastatin", "ezetimibe", "fenofibrate", "gemfibrozil",
    "lipitor", "crestor", "pravachol", "zocor", "lescol", "livalo",
    
    # Diabetes medications
    "metformin", "glipizide", "glyburide", "glimepiride", "sitagliptin",
    "linagliptin", "saxagliptin", "alogliptin", "pioglitazone", "rosiglitazone",
    "empagliflozin", "canagliflozin", "dapagliflozin", "liraglutide", "semaglutide",
    "dulaglutide", "insulin", "lantus", "humalog", "novolog", "levemir",
    "januvia", "janumet", "farxiga", "jardiance", "invokana", "trulicity",
    "ozempic", "victoza", "rybelsus", "glucophage", "actos", "avandia",
    
    # Thyroid medications
    "levothyroxine", "liothyronine", "methimazole", "propylthiouracil",
    "synthroid", "levoxyl", "unithroid", "armour thyroid", "nature-throid",
    
    # Anticoagulants (Blood thinners)
    "warfarin", "apixaban", "rivaroxaban", "dabigatran", "edoxaban",
    "coumadin", "eliquis", "xarelto", "pradaxa", "heparin", "enoxaparin",
    "clopidogrel", "ticagrelor", "prasugrel", "plavix", "brilinta", "effient",
    
    # Antidepressants
    "sertraline", "fluoxetine", "citalopram", "escitalopram", "paroxetine",
    "duloxetine", "venlafaxine", "desvenlafaxine", "bupropion", "mirtazapine",
    "trazodone", "amitriptyline", "nortriptyline", "imipramine", "clomipramine",
    "zoloft", "prozac", "celexa", "lexapro", "paxil", "cymbalta", "effexor",
    "wellbutrin", "remeron", "desyrel", "elavil", "pamelor", "tofranil",
    
    # Anti-anxiety medications
    "alprazolam", "lorazepam", "clonazepam", "diazepam", "buspirone",
    "xanax", "ativan", "klonopin", "valium", "buspar",
    
    # Antipsychotics
    "risperidone", "olanzapine", "quetiapine", "aripiprazole", "ziprasidone",
    "clozapine", "haloperidol", "fluphenazine", "perphenazine", "thiothixene",
    "risperdal", "zyprexa", "seroquel", "abilify", "geodon", "clozaril",
    "haldol", "prolixin", "trilafon", "navane",
    
    # Mood stabilizers
    "lithium", "valproic acid", "lamotrigine", "carbamazepine", "oxcarbazepine",
    "topiramate", "gabapentin", "pregabalin", "depakote", "lamictal", "tegretol",
    "trileptal", "topamax", "neurontin", "lyrica",
    
    # ADHD medications
    "methylphenidate", "amphetamine", "dextroamphetamine", "lisdexamfetamine",
    "atomoxetine", "guanfacine", "clonidine", "ritalin", "concerta", "adderall",
    "vyvanse", "strattera", "intuniv", "kapvay",
    
    # Allergy medications
    "cetirizine", "loratadine", "fexofenadine", "diphenhydramine", "levocetirizine",
    "desloratadine", "promethazine", "zyrtec", "claritin", "allegra", "benadryl",
    "xozal", "clarinex", "phenergan",
    
    # Asthma & Respiratory medications
    "albuterol", "levalbuterol", "salmeterol", "formoterol", "budesonide",
    "fluticasone", "mometasone", "beclomethasone", "tiotropium", "ipratropium",
    "montelukast", "zafirlukast", "theophylline", "ventolin", "proair", "proventil",
    "xopenex", "serevent", "foradil", "pulmicort", "flovent", "asmanex", "qvar",
    "spiriva", "atrovent", "singulair", "accolate", "theo-dur",
    
    # Proton pump inhibitors (Acid reflux)
    "omeprazole", "esomeprazole", "lansoprazole", "pantoprazole", "rabeprazole",
    "prilosec", "nexium", "prevacid", "protonix", "aciphex", "dexilant",
    
    # H2 blockers (Acid reflux)
    "famotidine", "ranitidine", "cimetidine", "nizatidine", "pepcid", "tagamet",
    "axid", "zantac",
    
    # Antiemetics (Nausea)
    "ondansetron", "metoclopramide", "promethazine", "prochlorperazine",
    "granisetron", "dolasetron", "zofran", "reglan", "phenergan", "compazine",
    "kytril", "anzemet",
    
    # Muscle relaxants
    "cyclobenzaprine", "methocarbamol", "carisoprodol", "baclofen", "tizanidine",
    "orphenadrine", "metaxalone", "chlorzoxazone", "flexeril", "robaxin", "soma",
    "lioresal", "zanaflex", "norflex", "skelaxin", "parafon",
    
    # Sleep aids
    "zolpidem", "eszopiclone", "zaleplon", "ramelteon", "doxepin", "trazodone",
    "ambien", "lunesta", "sonata", "rozerem", "silenor", "desyrel",
    
    # Erectile dysfunction
    "sildenafil", "tadalafil", "vardenafil", "avanafil", "viagra", "cialis",
    "levitra", "stendra",
    
    # Osteoporosis medications
    "alendronate", "risedronate", "ibandronate", "zoledronic acid", "raloxifene",
    "teriparatide", "denosumab", "fosamax", "actonel", "boniva", "reclast",
    "evista", "forteo", "prolia",
    
    # Glaucoma medications
    "latanoprost", "bimatoprost", "travoprost", "tafluprost", "timolol",
    "dorzolamide", "brinzolamide", "brimonidine", "xalatan", "lumigan", "travatan",
    "zioptan", "timoptic", "trusopt", "azopt", "alphagan",
    
    # Antifungals
    "fluconazole", "itraconazole", "ketoconazole", "terbinafine", "clotrimazole",
    "miconazole", "nystatin", "diflucan", "sporanox", "nizoral", "lamisil",
    "lotrimin", "micatin", "mycostatin",
    
    # Antivirals
    "acyclovir", "valacyclovir", "famciclovir", "oseltamivir", "zanamivir",
    "ribavirin", "zovirax", "valtrex", "famvir", "tamiflu", "relenza", "rebetol",
    
    # Chemotherapy & Immunosuppressants
    "methotrexate", "azathioprine", "cyclophosphamide", "mycophenolate",
    "tacrolimus", "sirolimus", "everolimus", "leflunomide", "hydroxychloroquine",
    "plaquenil", "imuran", "cytoxan", "cellcept", "prograf", "rapamune", "afinitor",
    "arava",
    
    # Vitamins & Supplements
    "vitamin a", "vitamin b1", "vitamin b2", "vitamin b3", "vitamin b5",
    "vitamin b6", "vitamin b7", "vitamin b9", "vitamin b12", "vitamin c",
    "vitamin d", "vitamin d2", "vitamin d3", "vitamin e", "vitamin k",
    "multivitamin", "folic acid", "ferrous sulfate", "calcium carbonate",
    "calcium citrate", "magnesium oxide", "zinc sulfate", "potassium chloride",
    "omega-3", "fish oil", "coq10", "glucosamine", "chondroitin", "melatonin",
    
    # Miscellaneous common medications
    "allopurinol", "colchicine", "probenecid", "febuxostat", "zyloprim",
    "colcrys", "benemid", "uloric", "naloxone", "naltrexone", "buprenorphine",
    "methadone", "suboxone", "subutex", "methadose", "varenicline", "bupropion",
    "nicotine", "chantix", "zyban", "nicoderm", "nicorette",
    
    # Brand names for common combinations
    "vicodin", "norco", "percocet", "oxycontin", "dilaudid", "morphine",
    "fentanyl", "duragesic", "codeine", "tramadol", "ultram", "demerol",
    "meperidine", "hydromorphone", "oxymorphone", "opana", "hydrocodone",
    "oxycodone"
]

def create_medications_csv(medications_list, filename="medications.csv"):
    """
    Create a CSV file with the medications list.
    """
    # Create data directory if it doesn't exist
    data_dir = "data"
    os.makedirs(data_dir, exist_ok=True)
    
    # Full path to CSV file
    filepath = os.path.join(data_dir, filename)
    
    # Write to CSV
    with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        
        # Write header
        writer.writerow(['medication_name'])
        
        # Write each medication (remove duplicates and sort)
        unique_meds = sorted(set(medications_list))
        for med in unique_meds:
            writer.writerow([med.lower()])
    
    print(f"✅ Created {filepath} with {len(unique_meds)} unique medications")
    return filepath

def categorize_medication(med_name):
    """Simple categorization based on medication name."""
    med_lower = med_name.lower()
    
    categories = {
        'pain': ['acetaminophen', 'paracetamol', 'ibuprofen', 'naproxen', 'diclofenac', 'celecoxib', 'meloxicam', 'ketorolac', 'aspirin', 'tylenol', 'advil', 'motrin', 'aleve', 'panadol', 'excedrin', 'vicodin', 'norco', 'percocet', 'oxycontin', 'tramadol', 'codeine', 'hydrocodone', 'oxycodone'],
        'antibiotic': ['amoxicillin', 'azithromycin', 'ciprofloxacin', 'doxycycline', 'cephalexin', 'clindamycin', 'metronidazole', 'penicillin', 'augmentin', 'keflex', 'bactrim', 'zithromax', 'cefdinir', 'nitrofurantoin', 'vancomycin', 'erythromycin'],
        'blood_pressure': ['lisinopril', 'amlodipine', 'losartan', 'metoprolol', 'atenolol', 'hydrochlorothiazide', 'furosemide', 'spironolactone', 'valsartan', 'candesartan', 'propranolol', 'carvedilol', 'nifedipine', 'diltiazem', 'verapamil'],
        'cholesterol': ['atorvastatin', 'simvastatin', 'rosuvastatin', 'pravastatin', 'lovastatin', 'ezetimibe', 'fenofibrate', 'gemfibrozil', 'lipitor', 'crestor', 'zocor'],
        'diabetes': ['metformin', 'glipizide', 'glyburide', 'glimepiride', 'sitagliptin', 'linagliptin', 'pioglitazone', 'empagliflozin', 'canagliflozin', 'dapagliflozin', 'liraglutide', 'semaglutide', 'insulin', 'lantus', 'humalog', 'januvia', 'farxiga', 'jardiance', 'ozempic'],
        'thyroid': ['levothyroxine', 'liothyronine', 'methimazole', 'propylthiouracil', 'synthroid'],
        'anticoagulant': ['warfarin', 'apixaban', 'rivaroxaban', 'dabigatran', 'edoxaban', 'coumadin', 'eliquis', 'xarelto', 'pradaxa', 'heparin', 'enoxaparin', 'clopidogrel', 'plavix'],
        'antidepressant': ['sertraline', 'fluoxetine', 'citalopram', 'escitalopram', 'paroxetine', 'duloxetine', 'venlafaxine', 'bupropion', 'mirtazapine', 'trazodone', 'amitriptyline', 'zoloft', 'prozac', 'celexa', 'lexapro', 'cymbalta', 'wellbutrin'],
        'anxiety': ['alprazolam', 'lorazepam', 'clonazepam', 'diazepam', 'buspirone', 'xanax', 'ativan', 'klonopin', 'valium'],
        'allergy': ['cetirizine', 'loratadine', 'fexofenadine', 'diphenhydramine', 'zyrtec', 'claritin', 'allegra', 'benadryl'],
        'asthma': ['albuterol', 'levalbuterol', 'salmeterol', 'fluticasone', 'budesonide', 'montelukast', 'ventolin', 'singulair'],
        'acid_reflux': ['omeprazole', 'esomeprazole', 'lansoprazole', 'pantoprazole', 'rabeprazole', 'famotidine', 'ranitidine', 'prilosec', 'nexium', 'pepcid'],
        'vitamin': ['vitamin', 'multivitamin', 'folic acid', 'calcium', 'magnesium', 'zinc', 'omega-3', 'fish oil'],
    }
    
    for category, keywords in categories.items():
        if any(keyword in med_lower for keyword in keywords):
            return category
    
    return 'other'

def get_common_brand(med_name):
    """Get common brand name for medications."""
    brands = {
        'acetaminophen': 'Tylenol',
        'ibuprofen': 'Advil/Motrin',
        'naproxen': 'Aleve',
        'diclofenac': 'Voltaren',
        'amoxicillin': 'Amoxil',
        'azithromycin': 'Zithromax',
        'ciprofloxacin': 'Cipro',
        'doxycycline': 'Vibramycin',
        'metformin': 'Glucophage',
        'lisinopril': 'Prinivil/Zestril',
        'amlodipine': 'Norvasc',
        'atorvastatin': 'Lipitor',
        'simvastatin': 'Zocor',
        'rosuvastatin': 'Crestor',
        'sertraline': 'Zoloft',
        'fluoxetine': 'Prozac',
        'escitalopram': 'Lexapro',
        'omeprazole': 'Prilosec',
        'esomeprazole': 'Nexium',
        'alprazolam': 'Xanax',
        'lorazepam': 'Ativan',
        'clonazepam': 'Klonopin',
        'warfarin': 'Coumadin',
        'apixaban': 'Eliquis',
        'rivaroxaban': 'Xarelto',
        'albuterol': 'Ventolin/Proair',
        'montelukast': 'Singulair',
        'levothyroxine': 'Synthroid',
        'cetirizine': 'Zyrtec',
        'loratadine': 'Claritin',
        'fexofenadine': 'Allegra',
        'diphenhydramine': 'Benadryl',
        'hydrochlorothiazide': 'Microzide',
        'furosemide': 'Lasix',
        'prednisone': 'Deltasone',
        'methylprednisolone': 'Medrol',
        'gabapentin': 'Neurontin',
        'pregabalin': 'Lyrica',
    }
    
    return brands.get(med_name.lower(), '')

# Create the CSV file
if __name__ == "__main__":
    csv_path = create_medications_csv(KNOWN_MEDICATIONS)
    print(f"\n📊 CSV file created at: {csv_path}")
    
    # Optional: Read and display first 10 rows
    try:
        import pandas as pd
        df = pd.read_csv(csv_path)
        print("\n📋 First 10 medications:")
        print(df.head(10).to_string(index=False))
    except ImportError:
        print("\n📋 First 10 medications (preview):")
        with open(csv_path, 'r') as f:
            for i, line in enumerate(f):
                if i < 11:  # Header + 10 rows
                    print(line.strip())