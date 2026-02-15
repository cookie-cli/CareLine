# app/services/correction.py

import re

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
    if not text:
        return ""

    corrected = text
    for wrong, right in CORRECTIONS.items():
        pattern = re.compile(rf"\b{re.escape(wrong)}\b", flags=re.IGNORECASE)
        corrected = pattern.sub(right, corrected)
    return corrected
