"""Simple file-based cache for market data"""
import json
import os
from datetime import datetime, timedelta
from typing import Optional, Dict

CACHE_DIR = "market_data_cache"
CACHE_DURATION_HOURS = 24

def get_cache_path(symbols: tuple) -> str:
    """Get cache file path for symbols"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    symbols_key = "_".join(sorted(symbols))
    return os.path.join(CACHE_DIR, f"{symbols_key}.json")

def get_cached_data(symbols: tuple) -> Optional[Dict]:
    """Get cached data if it exists and is fresh"""
    cache_path = get_cache_path(symbols)
    
    if not os.path.exists(cache_path):
        return None
    
    try:
        with open(cache_path, 'r') as f:
            cached = json.load(f)
        
        cached_time = datetime.fromisoformat(cached['timestamp'])
        age_hours = (datetime.now() - cached_time).total_seconds() / 3600
        
        if age_hours < CACHE_DURATION_HOURS:
            print(f"Using cached data (age: {age_hours:.1f} hours)")
            return cached['data']
        else:
            print(f"Cache expired (age: {age_hours:.1f} hours)")
            return None
            
    except Exception as e:
        print(f"Cache read error: {e}")
        return None

def save_to_cache(symbols: tuple, data: Dict):
    """Save data to cache"""
    cache_path = get_cache_path(symbols)
    
    try:
        cached = {
            'timestamp': datetime.now().isoformat(),
            'symbols': list(symbols),
            'data': data
        }
        
        with open(cache_path, 'w') as f:
            json.dump(cached, f)
        
        print(f"Data cached for {', '.join(symbols)}")
    except Exception as e:
        print(f"Cache write error: {e}")
