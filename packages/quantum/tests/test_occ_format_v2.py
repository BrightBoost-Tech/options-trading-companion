import pytest
from packages.quantum.services.options_utils import format_occ_symbol_readable

def test_format_occ_symbol_readable():
    # Test valid OCC symbol
    symbol = "AMZN251219C00255000"
    formatted = format_occ_symbol_readable(symbol)
    assert formatted == "AMZN 12/19/25 C 255"

    # Test with prefix
    symbol_prefix = "O:AMZN251219C00255000"
    formatted_prefix = format_occ_symbol_readable(symbol_prefix)
    assert formatted_prefix == "AMZN 12/19/25 C 255"

    # Test invalid (returns original)
    invalid = "INVALID_SYMBOL"
    assert format_occ_symbol_readable(invalid) == "INVALID_SYMBOL"

    # Test decimal strike
    decimal_strike = "AMZN251219P00255500" # 255.5
    assert format_occ_symbol_readable(decimal_strike) == "AMZN 12/19/25 P 255.5"
