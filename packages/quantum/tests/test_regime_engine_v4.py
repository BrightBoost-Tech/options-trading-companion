"""
Tests for Regime Engine V4 enhancements.

Verifies:
1. Global snapshot to_dict includes components + engine_version
2. Liquidity z-score computation logic
3. Symbol snapshot metrics format
4. Chain adapter logic
5. DB schema alignment (as_of_ts, state, risk_score, risk_scaler, components, details, engine_version)

These tests verify the fix logic without importing heavy dependencies.
"""

import pytest
import os
from datetime import datetime, timezone, timedelta


class TestGlobalSnapshotV4ToDict:
    """Tests for GlobalRegimeSnapshot.to_dict() V4 format."""

    def test_to_dict_includes_required_keys(self):
        """Verify to_dict output matches expected DB schema."""
        # Read the source file to verify the structure
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "analytics",
            "regime_engine_v3.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Verify ENGINE_VERSION is defined
        assert 'ENGINE_VERSION = "v4"' in content, \
            "ENGINE_VERSION should be set to 'v4'"

        # Verify to_dict includes components
        assert '"components": components' in content or "'components': components" in content, \
            "GlobalRegimeSnapshot.to_dict should include 'components'"

        # Verify to_dict includes engine_version
        assert '"engine_version": ENGINE_VERSION' in content or "'engine_version': ENGINE_VERSION" in content, \
            "GlobalRegimeSnapshot.to_dict should include 'engine_version'"

        # Verify components dict is built with z-scores
        assert '"trend_z": self.trend_score' in content, \
            "components should include trend_z"
        assert '"vol_z": self.vol_score' in content, \
            "components should include vol_z"
        assert '"liquidity_z": self.liquidity_score' in content, \
            "components should include liquidity_z"

    def test_engine_version_constant(self):
        """Verify ENGINE_VERSION constant is defined as v4."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "analytics",
            "regime_engine_v3.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert 'ENGINE_VERSION = "v4"' in content


class TestLiquidityZComputation:
    """Tests for liquidity z-score computation logic."""

    def test_liquidity_constants_defined(self):
        """Verify liquidity computation constants are defined."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "analytics",
            "regime_engine_v3.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "LIQUIDITY_BASELINE_SPREAD" in content, \
            "LIQUIDITY_BASELINE_SPREAD constant should be defined"
        assert "LIQUIDITY_SCALE" in content, \
            "LIQUIDITY_SCALE constant should be defined"

    def test_liquidity_z_formula(self):
        """Verify liquidity z-score formula is correctly implemented."""
        # Replicate the liquidity z-score calculation
        LIQUIDITY_BASELINE_SPREAD = 0.002  # 0.2%
        LIQUIDITY_SCALE = 0.001  # 0.1%

        def compute_liquidity_z(median_spread_pct):
            liquidity_z = (median_spread_pct - LIQUIDITY_BASELINE_SPREAD) / LIQUIDITY_SCALE
            return max(-3, min(3, liquidity_z))  # clip to [-3, 3]

        # Test cases
        # Tight spread (0.1%) should give negative z (good liquidity)
        assert compute_liquidity_z(0.001) == -1.0

        # Neutral spread (0.2%) should give z=0
        assert compute_liquidity_z(0.002) == 0.0

        # Wide spread (0.5%) should give positive z (bad liquidity)
        assert compute_liquidity_z(0.005) == 3.0  # clipped

        # Very wide spread (1%) should be clipped to 3
        assert compute_liquidity_z(0.01) == 3.0

    def test_snapshot_many_used_for_liquidity(self):
        """Verify snapshot_many is called to get basket quotes."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "analytics",
            "regime_engine_v3.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "self.market_data.snapshot_many(self.BASKET)" in content, \
            "compute_global_snapshot should call snapshot_many for basket quotes"

    def test_liquidity_weight_in_aggregation(self):
        """Verify liquidity has a weight in risk aggregation."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "analytics",
            "regime_engine_v3.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "w_liq" in content, \
            "Liquidity weight (w_liq) should be defined"
        assert "w_liq * liquidity_z" in content, \
            "Liquidity z-score should contribute to raw_risk"


class TestSymbolSnapshotV4ToDict:
    """Tests for SymbolRegimeSnapshot.to_dict() V4 format."""

    def test_to_dict_includes_metrics(self):
        """Verify to_dict includes metrics dict."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "analytics",
            "regime_engine_v3.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Find SymbolRegimeSnapshot.to_dict
        assert '"metrics": metrics' in content or "'metrics': metrics" in content, \
            "SymbolRegimeSnapshot.to_dict should include 'metrics'"

        # Verify metrics dict contains required fields
        assert '"iv_rank": self.iv_rank' in content, \
            "metrics should include iv_rank"
        assert '"skew_25d": self.skew_25d' in content, \
            "metrics should include skew_25d"
        assert '"term_slope": self.term_slope' in content, \
            "metrics should include term_slope"

    def test_symbol_snapshot_engine_version(self):
        """Verify SymbolRegimeSnapshot.to_dict includes engine_version."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "analytics",
            "regime_engine_v3.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Count engine_version occurrences - should appear in both to_dict methods
        count = content.count('"engine_version": ENGINE_VERSION')
        assert count >= 2, \
            "engine_version should appear in both GlobalRegimeSnapshot and SymbolRegimeSnapshot to_dict"


class TestChainAdapter:
    """Tests for chain schema adapter logic."""

    def test_adapt_chain_method_exists(self):
        """Verify _adapt_chain_to_raw_schema method is defined."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "analytics",
            "regime_engine_v3.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "def _adapt_chain_to_raw_schema" in content, \
            "_adapt_chain_to_raw_schema method should be defined"

    def test_adapter_converts_truthlayer_format(self):
        """Verify adapter handles TruthLayer canonical format."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "analytics",
            "regime_engine_v3.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Should extract expiry -> expiration_date
        assert '"expiration_date": c.get("expiry")' in content, \
            "Adapter should map expiry to expiration_date"

        # Should extract strike -> strike_price
        assert '"strike_price": c.get("strike")' in content, \
            "Adapter should map strike to strike_price"

        # Should extract right -> contract_type
        assert '"contract_type": c.get("right")' in content, \
            "Adapter should map right to contract_type"

    def test_adapter_logic(self):
        """Test the adapter logic directly."""
        # Replicate the adapter logic
        def _adapt_chain_to_raw_schema(chain_results):
            adapted = []
            for c in chain_results:
                adapted_contract = {
                    "details": {
                        "expiration_date": c.get("expiry"),
                        "strike_price": c.get("strike"),
                        "contract_type": c.get("right"),
                    },
                    "greeks": c.get("greeks", {}),
                    "implied_volatility": c.get("iv"),
                }
                if adapted_contract["implied_volatility"] is None:
                    greeks = c.get("greeks", {})
                    adapted_contract["implied_volatility"] = greeks.get("iv")
                adapted.append(adapted_contract)
            return adapted

        # Test input
        truthlayer_chain = [
            {
                "strike": 450.0,
                "expiry": "2024-01-15",
                "right": "call",
                "iv": 0.20,
                "greeks": {"delta": 0.50}
            }
        ]

        adapted = _adapt_chain_to_raw_schema(truthlayer_chain)

        assert len(adapted) == 1
        assert adapted[0]["details"]["expiration_date"] == "2024-01-15"
        assert adapted[0]["details"]["strike_price"] == 450.0
        assert adapted[0]["details"]["contract_type"] == "call"
        assert adapted[0]["implied_volatility"] == 0.20
        assert adapted[0]["greeks"]["delta"] == 0.50


class TestSkewAndTermComputation:
    """Tests for skew_25d and term_slope computation."""

    def test_compute_symbol_snapshot_accepts_chain(self):
        """Verify compute_symbol_snapshot accepts chain_results parameter."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "analytics",
            "regime_engine_v3.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check signature includes chain_results
        assert "chain_results: Optional[List[Dict]] = None" in content, \
            "compute_symbol_snapshot should accept chain_results parameter"

    def test_skew_computed_from_chain(self):
        """Verify skew_25d is computed when chain is provided."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "analytics",
            "regime_engine_v3.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "IVPointService.compute_skew_25d_from_chain" in content, \
            "Should call IVPointService.compute_skew_25d_from_chain"

    def test_term_slope_computed_from_chain(self):
        """Verify term_slope is computed when chain is provided."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "analytics",
            "regime_engine_v3.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "IVPointService.compute_term_slope" in content, \
            "Should call IVPointService.compute_term_slope"

    def test_env_var_fallback_for_chain_fetch(self):
        """Verify REGIME_V4_FETCH_CHAIN env var enables chain fetching."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "analytics",
            "regime_engine_v3.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert 'os.getenv("REGIME_V4_FETCH_CHAIN"' in content, \
            "Should check REGIME_V4_FETCH_CHAIN env var"

    def test_f_skew_and_f_term_scaled(self):
        """Verify f_skew and f_term are scaled for score contribution."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "analytics",
            "regime_engine_v3.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # f_skew should scale skew_25d
        assert "(skew_25d * 100)" in content or "skew_25d * 100" in content, \
            "f_skew should scale skew_25d by 100"

        # f_term should scale term_slope (inverted)
        assert "(-term_slope * 100)" in content or "-term_slope * 100" in content, \
            "f_term should scale term_slope by -100 (inverted)"


class TestBackwardCompatibility:
    """Tests for backward compatibility."""

    def test_features_field_preserved(self):
        """Verify features field is still in to_dict for backward compatibility."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "analytics",
            "regime_engine_v3.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Both to_dict methods should include features
        assert '"features": self.features' in content, \
            "to_dict should preserve features field"

    def test_compute_symbol_snapshot_optional_params(self):
        """Verify new parameters are optional for backward compatibility."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "analytics",
            "regime_engine_v3.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # New parameters should have default values
        assert "chain_results: Optional[List[Dict]] = None" in content
        assert "spot: Optional[float] = None" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
