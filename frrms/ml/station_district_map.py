"""
Maps BMD weather station names (from the flood dataset) to the Bangladesh
district they belong to, so model predictions can be attached to FRRMS's
existing Location/District records.
"""

STATION_TO_DISTRICT = {
    "Barisal": "Barisal",
    "Bhola": "Bhola",
    "Bogra": "Bogura",
    "Chandpur": "Chandpur",
    "Chittagong (City-Ambagan)": "Chattogram",
    "Chittagong (IAP-Patenga)": "Chattogram",
    "Comilla": "Cumilla",
    "Cox's Bazar": "Cox's Bazar",
    "Dhaka": "Dhaka",
    "Dinajpur": "Dinajpur",
    "Faridpur": "Faridpur",
    "Feni": "Feni",
    "Hatiya": "Noakhali",
    "Ishurdi": "Pabna",
    "Jessore": "Jashore",
    "Khepupara": "Patuakhali",
    "Khulna": "Khulna",
    "Kutubdia": "Cox's Bazar",
    "Madaripur": "Madaripur",
    "Maijdee Court": "Noakhali",
    "Mongla": "Bagerhat",
    "Mymensingh": "Mymensingh",
    "Patuakhali": "Patuakhali",
    "Rajshahi": "Rajshahi",
    "Rangamati": "Rangamati",
    "Rangpur": "Rangpur",
    "Sandwip": "Chattogram",
    "Satkhira": "Satkhira",
    "Sitakunda": "Chattogram",
    "Srimangal": "Moulvibazar",
    "Sylhet": "Sylhet",
    "Tangail": "Tangail",
    "Teknaf": "Cox's Bazar",
}
