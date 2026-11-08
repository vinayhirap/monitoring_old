"""NSE F&O universe — the ~180 stocks tradable in the Nifty F&O segment,
plus indices. Used by the recommender to scan and rank.

Source: NSE FNO list (manually curated; refresh periodically from
https://www.nseindia.com/products-services/equity-derivatives-list-underlyings)
"""

# Index futures + options
INDICES = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"]

# Sector classification used for sector-rotation views in the UI
SECTORS: dict[str, list[str]] = {
    "Banking & Financial": [
        "HDFCBANK", "ICICIBANK", "AXISBANK", "SBIN", "KOTAKBANK", "INDUSINDBK",
        "BAJFINANCE", "BAJAJFINSV", "HDFCAMC", "SBILIFE", "HDFCLIFE", "ICICIPRULI",
        "ICICIGI", "CHOLAFIN", "MUTHOOTFIN", "PFC", "RECLTD", "LICHSGFIN",
        "M&MFIN", "BANDHANBNK", "AUBANK", "FEDERALBNK", "IDFCFIRSTB", "IEX",
    ],
    "IT": [
        "TCS", "INFY", "WIPRO", "HCLTECH", "TECHM", "LTIM", "MPHASIS",
        "PERSISTENT", "COFORGE", "LTTS", "OFSS", "TATAELXSI",
    ],
    "Oil & Gas / Energy": [
        "RELIANCE", "ONGC", "IOC", "BPCL", "HINDPETRO", "GAIL", "PETRONET",
        "OIL", "ATGL", "ADANIENT", "ADANIPORTS", "POWERGRID", "NTPC", "TATAPOWER",
    ],
    "Auto": [
        "MARUTI", "TATAMOTORS", "M&M", "EICHERMOT", "BAJAJ-AUTO", "HEROMOTOCO",
        "TVSMOTOR", "ASHOKLEY", "BOSCHLTD", "MOTHERSON", "BHARATFORG", "ESCORTS",
        "MRF", "BALKRISIND", "EXIDEIND",
    ],
    "Pharma": [
        "SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "AUROPHARMA", "LUPIN",
        "TORNTPHARM", "BIOCON", "ALKEM", "GLAND", "ZYDUSLIFE", "GLENMARK",
        "LAURUSLABS", "GRANULES", "IPCALAB", "NATCOPHARM",
    ],
    "FMCG": [
        "HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR", "MARICO",
        "GODREJCP", "COLPAL", "UBL", "TATACONSUM", "VBL", "RADICO", "EMAMILTD",
    ],
    "Metals": [
        "TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "JINDALSTEL", "NMDC",
        "SAIL", "NATIONALUM", "HINDCOPPER", "JSL", "RATNAMANI", "APLAPOLLO",
    ],
    "Cement & Infra": [
        "LT", "ULTRACEMCO", "GRASIM", "SHREECEM", "AMBUJACEM", "ACC",
        "DALBHARAT", "JKCEMENT", "RAMCOCEM", "DLF", "OBEROIRLTY", "GODREJPROP",
        "PRESTIGE", "LODHA", "SUNTECK",
    ],
    "Telecom & Media": [
        "BHARTIARTL", "IDEA", "INDUSTOWER", "ZEEL", "SUNTV", "PVRINOX",
        "NETWORK18", "DISHTV",
    ],
    "Consumer Durables / Retail": [
        "TITAN", "ASIANPAINT", "BERGEPAINT", "PIDILITIND", "HAVELLS", "VOLTAS",
        "DIXON", "POLYCAB", "CROMPTON", "BATAINDIA", "RELAXO", "TRENT",
        "DMART", "JUBLFOOD", "WHIRLPOOL", "BLUESTARCO",
    ],
    "Chemicals / Agro": [
        "UPL", "PIIND", "SRF", "DEEPAKNTR", "AARTIIND", "ALKYLAMINE",
        "ATUL", "NAVINFLUOR", "GNFC", "CHAMBLFERT", "COROMANDEL",
    ],
    "Misc": [
        "ADANIENSOL", "ABFRL", "ABCAPITAL", "ABBOTINDIA", "BEL", "BHEL",
        "CONCOR", "CUMMINSIND", "GMRAIRPORT", "HAL", "IRCTC", "MFSL",
        "NAUKRI", "PAGEIND", "PIRAMALFIN", "SBICARD", "SIEMENS", "TATACHEM",
        "TATACOMM", "VEDL", "VOLTAS", "ETERNAL", "PAYTM", "POLICYBZR",
    ],
}


def all_symbols(include_indices: bool = True) -> list[str]:
    syms = []
    if include_indices:
        syms.extend(INDICES)
    for sector_syms in SECTORS.values():
        syms.extend(sector_syms)
    # de-duplicate while preserving order
    seen = set()
    out = []
    for s in syms:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


# Top-50 most-liquid F&O names — used by quick scans to keep response time <30s
TOP50 = [
    "NIFTY", "BANKNIFTY", "FINNIFTY",
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK",
    "KOTAKBANK", "HINDUNILVR", "ITC", "LT", "BAJFINANCE", "BHARTIARTL",
    "MARUTI", "TATAMOTORS", "M&M", "BAJAJFINSV", "HCLTECH", "WIPRO",
    "ASIANPAINT", "SUNPHARMA", "ULTRACEMCO", "NTPC", "POWERGRID", "ONGC",
    "ADANIENT", "ADANIPORTS", "JSWSTEEL", "TATASTEEL", "COALINDIA",
    "INDUSINDBK", "HDFCLIFE", "SBILIFE", "DRREDDY", "CIPLA", "DIVISLAB",
    "NESTLEIND", "BRITANNIA", "TITAN", "TECHM", "EICHERMOT", "HEROMOTOCO",
    "BPCL", "GRASIM", "TATACONSUM", "BAJAJ-AUTO", "UPL", "APOLLOHOSP",
]


def top_liquid(n: int = 50) -> list[str]:
    return TOP50[:n]


def sector_of(symbol: str) -> str:
    for sector, syms in SECTORS.items():
        if symbol in syms:
            return sector
    if symbol in INDICES:
        return "Index"
    return "Unknown"


# ---------------------------------------------------------------------------
# Broader universe lookups — pull from Angel One scrip master
# ---------------------------------------------------------------------------

def nifty500_symbols() -> list[str]:
    """Returns the F&O 180 + an expanded list pulled from the scrip master.
    Cached after first call. Used when caller wants more than the F&O universe.
    """
    from app.services import instruments
    fno = all_symbols(include_indices=True)
    try:
        all_eq = instruments.all_nse_equity_symbols()
        if not all_eq:
            return fno
        # Prefer F&O first (so the order keeps liquid names early), then add
        # the rest of NSE equities up to 500 total.
        seen = set(fno)
        merged = list(fno)
        for s in all_eq:
            if len(merged) >= 500:
                break
            if s not in seen:
                merged.append(s)
                seen.add(s)
        return merged
    except Exception:
        return fno


def all_nse_equity() -> list[str]:
    """Returns every NSE equity symbol in the scrip master (~2000).
    WARNING: scanning this in the recommender takes 30+ minutes."""
    from app.services import instruments
    try:
        return instruments.all_nse_equity_symbols()
    except Exception:
        return all_symbols(include_indices=True)


def universe_for(name: str) -> list[str]:
    """Resolve a universe-name string to a list of symbols.
    name ∈ {fno_top50, fno, nifty500, all_nse}.
    """
    name = (name or "fno").lower()
    if name in ("fno_top50", "top50"):
        return top_liquid(50)
    if name == "fno":
        return all_symbols(include_indices=True)
    if name == "nifty500":
        return nifty500_symbols()
    if name == "all_nse":
        return all_nse_equity()
    return all_symbols(include_indices=True)
