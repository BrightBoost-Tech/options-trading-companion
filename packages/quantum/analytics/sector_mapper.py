from typing import Optional, Tuple, Dict

class SectorMapper:
    # Static mapping for common tickers (can be expanded or replaced by API later)
    SECTOR_MAP: Dict[str, Tuple[str, str]] = {
        "SPY": ("Indices", "Broad Market"),
        "QQQ": ("Indices", "Tech Heavy"),
        "IWM": ("Indices", "Small Cap"),
        "GLD": ("Commodities", "Precious Metals"),
        "USO": ("Commodities", "Oil"),
        "TLT": ("Fixed Income", "Treasuries"),
        # Tech
        "AAPL": ("Technology", "Consumer Electronics"),
        "MSFT": ("Technology", "Software"),
        "GOOGL": ("Technology", "Internet"),
        "AMZN": ("Consumer Cyclical", "E-Commerce"),
        "TSLA": ("Consumer Cyclical", "Auto Manufacturers"),
        "NVDA": ("Technology", "Semiconductors"),
        "AMD": ("Technology", "Semiconductors"),
        "META": ("Technology", "Internet"),
        # VTSI (example from prompt)
        "VTSI": ("Technology", "Semiconductors"),
        # Financials
        "JPM": ("Financial Services", "Banks"),
        "BAC": ("Financial Services", "Banks"),
        "GS": ("Financial Services", "Capital Markets"),
        # Others
        "XOM": ("Energy", "Oil & Gas"),
        "JNJ": ("Healthcare", "Drug Manufacturers"),
        "PFE": ("Healthcare", "Drug Manufacturers"),
        "V": ("Financial Services", "Credit Services"),
        "MA": ("Financial Services", "Credit Services"),
        "WMT": ("Consumer Defensive", "Retail"),
        "KO": ("Consumer Defensive", "Beverages"),
    }

    @staticmethod
    def get_sector_industry(symbol: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Returns (sector, industry) for a given symbol.
        """
        if not symbol:
            return None, None

        # Strip potential option prefix/suffix to get underlying if needed
        # But usually we map underlying symbols.
        # Simple normalization:
        clean = symbol.upper().replace("O:", "").split(" ")[0] # Basic split just in case

        # If it looks like an option (digits), extract root
        # We can reuse extraction logic or just check map.
        # Assuming we passed the underlying or equity symbol here.

        return SectorMapper.SECTOR_MAP.get(clean, ("Unknown", "Unknown"))
