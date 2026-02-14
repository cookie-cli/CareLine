# app/services/correction.py

# Medicine name corrections for Indian medicines
CORRECTIONS = {
    "thermal": "Telma",
    "thelma": "Telma", 
    "chelma": "Telma",
    "telma": "Telma",
    "shall call": "Shelcal",
    "shell call": "Shelcal",
    "shelcal": "Shelcal",
    "glide comet": "Glycomet",
    "glyco met": "Glycomet",
    "glycomet": "Glycomet",
    "emma": "Amma",
    "ecosprint": "Ecosprin",
    "ecosprin": "Ecosprin",
    "metaformin": "Metformin",
    "metformin": "Metformin",
    "atorva": "Atorva",
    "pan": "Pan",
    "omez": "Omez",
    "bp": "BP",
}

def correct_medicine_names(text: str) -> str:
    """
    Fix common misheard medicine names
    """
    corrected = text.lower()
    for wrong, right in CORRECTIONS.items():
        corrected = corrected.replace(wrong.lower(), right)
    return corrected