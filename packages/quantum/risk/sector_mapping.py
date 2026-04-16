"""
SIC industry string -> canonical GICS-aligned sector taxonomy.

Used by risk_envelope.check_concentration to enforce sector concentration limits
that survive raw-SIC string fragmentation. Without this mapping, AMD ("SEMI-
CONDUCTORS & RELATED DEVICES"), MSFT ("SERVICES-PREPACKAGED SOFTWARE"), and
ADBE ("SERVICES-PREPACKAGED SOFTWARE") all hash to different sectors, so a
tech-heavy basket evades the 40% sector cap entirely.

First substring match wins. Order matters: more specific keywords first.
"""

SECTOR_MAP = (
    ("Technology", (
        "SEMICONDUCTOR", "SOFTWARE", "PREPACKAGED",
        "COMPUTER", "DATA PROCESSING", "ELECTRONIC COMP",
        "INSTRUMENTS", "OPTICAL",
    )),
    ("Communication Services", (
        "TELEPHONE", "TELECOMMUN", "RADIO", "TELEVISION",
        "PUBLISHING", "VIDEO TAPE", "CABLE", "ADVERTISING",
        "SERVICES-COMPUTER PROGRAMMING",
    )),
    ("Consumer Discretionary", (
        "RETAIL", "MAIL-ORDER", "CATALOG", "AUTO", "APPAREL",
        "RESTAURANT", "HOTEL", "LEISURE", "FOOTWEAR", "TOYS",
    )),
    ("Consumer Staples", (
        "FOOD", "BEVERAGE", "TOBACCO", "HOUSEHOLD", "PERSONAL CARE",
        "GROCERY", "DRUG STORE",
    )),
    ("Healthcare", (
        "PHARMACEUT", "MEDICAL", "BIOLOGICAL", "HOSPITAL",
        "HEALTH", "DENTAL", "SURGICAL",
    )),
    ("Financials", (
        "BANK", "INSURANCE", "FINANCIAL", "INVESTMENT", "BROKER",
        "CREDIT", "LOAN", "SAVINGS",
    )),
    ("Energy", (
        "PETROLEUM", "OIL", "NATURAL GAS", "COAL", "MINING",
    )),
    ("Industrials", (
        "AIRCRAFT", "AIRLINE", "MACHINERY", "MOTOR VEHICLE",
        "INDUSTRIAL", "TRANSPORT", "RAILROAD", "CONSTRUCTION",
        "DEFENSE", "AEROSPACE",
    )),
    ("Materials", (
        "CHEMICAL", "STEEL", "METAL", "PAPER", "PLASTIC",
        "GLASS", "CEMENT", "FOREST",
    )),
    ("Real Estate", (
        "REAL ESTATE", "REIT",
    )),
    ("Utilities", (
        "ELECTRIC SERV", "UTILIT", "WATER SUPP", "GAS DISTRIB",
    )),
)


def canonical_sector(raw_sic: str | None) -> str:
    """Map a raw SIC industry string (any case) to a canonical GICS sector.

    Returns 'Unclassified' for null/empty input or no keyword match. Returns
    'Unclassified' rather than None so concentration math treats unmapped
    positions as one bucket rather than fragmenting them further.
    """
    if not raw_sic:
        return "Unclassified"
    upper = raw_sic.upper()
    for canonical, keywords in SECTOR_MAP:
        for kw in keywords:
            if kw in upper:
                return canonical
    return "Unclassified"
