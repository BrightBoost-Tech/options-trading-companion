"""First honest challenger: risk-neutral-ish lognormal terminal distribution.

MATH (reused, verified honest): the probability kernel is the same lognormal
d2 machinery as the dormant scorer kernel (analytics/opportunity_scorer.py:
143-180 ``get_prob_itm`` and :50-57 ``_fast_norm_cdf`` — exact erf-based
normal CDF):

    d2(k) = (ln(S/k) + (mu - sigma^2/2) T) / (sigma sqrt(T))
    P(S_T > k) = N(d2(k))            =>  cdf(k) = P(S_T <= k) = N(-d2(k))

plus the standard lognormal partial expectation for exact payoff integration:

    F = S e^{mu T},  d1 = d2 + sigma sqrt(T)
    E[S_T * 1{S_T <= k}] = F * N(-d1(k))

WHAT WAS **NOT** REUSED from that kernel (H9 — each is a fabrication):
    - ``iv or 0.30``: a missing IV became a 30%-vol guess. Here: ABSTAIN
      (typed ``missing_iv``/``invalid_iv``).
    - ``mu = expected_return or 0.05``: a hardcoded equity-drift assumption.
      Here: drift is the risk-free rate from DistributionInputs (default 0.0
      — "risk-neutral-ish"), never a return forecast.
    - ``except: return 0.5``: numeric failure became a coin flip. Here:
      inputs are validated up front and the closed forms cannot fail on
      validated inputs.
    - Percent-vs-decimal auto-rescale (``iv/100`` when iv > 5): a silent
      reinterpretation of ambiguous input. Here: IV outside the plausible
      decimal range ABSTAINS instead of being reinterpreted.

CALL/PUT-AWARENESS lives in the integration layer: payoff.py chooses the
profitable side of each breakeven from structure orientation and queries this
distribution's CDF accordingly (the dormant kernel computed P(S_T > K)
regardless of option type; here puts profit on the ``cdf`` side, calls on the
``1 - cdf`` side, per structure).

DOCUMENTED MODEL ASSUMPTIONS (challenger "lognormal_v1"):
    1. Single flat sigma per structure: the EQUAL-WEIGHT MEAN of all leg IVs.
       The vol smile/skew across strikes is deliberately ignored in v1; every
       leg must carry a valid IV or the model abstains (no partial averages).
    2. Drift = risk_free_rate (default 0.0), i.e. approximately the
       risk-neutral measure with rates ~0 over short DTEs. No equity risk
       premium, no forecast drift.
    3. Continuous lognormal terminal density — no jumps, no earnings
       component, no fat tails. (The charter's ensemble spec — EWMA/GARCH,
       HAR, earnings-jump, uncertainty buffer — is future work layered on the
       same contract, not this module.)
    4. European-style terminal evaluation at expiry; early exercise and
       path-dependent exits are out of scope for the terminal distribution.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Union

from packages.quantum.analytics.terminal_distribution.contract import (
    CONTRACT_VERSION,
    DistributionInputs,
    EvalOutcome,
    Provenance,
    StructureSpec,
    Unavailable,
    params_hash,
)
from packages.quantum.analytics.terminal_distribution.payoff import integrate_structure

CHALLENGER_SOURCE = "challenger_lognormal"
CHALLENGER_VERSION = f"lognormal_v1@{CONTRACT_VERSION}"
MODEL_NAME = "lognormal_v1"

# Plausibility bound for an ANNUALIZED DECIMAL implied vol. Above this we
# refuse to guess whether the caller meant percent (30.0 for 30%) — abstain.
IV_PLAUSIBLE_MAX = 3.0
_SQRT2 = math.sqrt(2.0)


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via math.erf — exact to ~1e-15 (same formula as
    opportunity_scorer._fast_norm_cdf)."""
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


@dataclass(frozen=True)
class LognormalTerminal:
    """Lognormal terminal distribution: S_T = spot * exp((mu - sigma^2/2) T + sigma sqrt(T) Z)."""

    spot: float
    sigma: float
    t_years: float
    mu: float
    provenance: Provenance

    def _d2(self, k: float) -> float:
        return (math.log(self.spot / k) + (self.mu - 0.5 * self.sigma ** 2) * self.t_years) / (
            self.sigma * math.sqrt(self.t_years)
        )

    def cdf(self, strike: float) -> float:
        """P(S_T <= strike). Zero mass at or below 0 (positive support)."""
        if strike <= 0.0:
            return 0.0
        return _norm_cdf(-self._d2(strike))

    def partial_expectation(self, lo: Optional[float], hi: Optional[float]) -> float:
        """E[S_T * 1{lo < S_T <= hi}]; lo=None -> 0, hi=None -> +inf.

        partial_expectation(None, None) == forward == spot * e^{mu T}."""
        forward = self.spot * math.exp(self.mu * self.t_years)

        def below_mass(k: float) -> float:
            # E[S_T * 1{S_T <= k}] / forward = N(-d1(k))
            if k <= 0.0:
                return 0.0
            d1 = self._d2(k) + self.sigma * math.sqrt(self.t_years)
            return _norm_cdf(-d1)

        hi_mass = 1.0 if hi is None else below_mass(hi)   # hi=None -> +inf
        lo_mass = 0.0 if lo is None else below_mass(lo)   # lo=None -> 0
        return forward * (hi_mass - lo_mass)


def build_lognormal(
    structure: StructureSpec,
    inputs: Optional[DistributionInputs],
) -> Union[LognormalTerminal, Unavailable]:
    """Build the v1 lognormal from typed inputs, abstaining on anything the
    model cannot honestly use (H9 — see module docstring for what is refused)."""
    source = CHALLENGER_SOURCE
    if inputs is None:
        return Unavailable("missing_inputs", "DistributionInputs required for the lognormal challenger", source)
    if not inputs.known_at or not isinstance(inputs.known_at, str):
        return Unavailable("missing_known_at", "known_at (ISO-8601 as-of timestamp) is required provenance", source)
    spot = inputs.spot
    if spot is None or not isinstance(spot, (int, float)) or not math.isfinite(spot) or spot <= 0:
        return Unavailable("missing_spot", f"spot must be finite and > 0, got {spot!r}", source)
    dte = inputs.dte_days
    if dte is None or not isinstance(dte, (int, float)) or not math.isfinite(dte) or dte <= 0:
        return Unavailable("invalid_dte", f"dte_days must be finite and > 0, got {dte!r}", source)
    if not structure.legs:
        return Unavailable("missing_legs", "structure has no legs", source)

    ivs = []
    for leg in structure.legs:
        iv = leg.iv
        if iv is None:
            return Unavailable(
                "missing_iv",
                f"leg {leg.action} {leg.option_type} {leg.strike} has no IV — abstaining, never defaulting",
                source,
            )
        if not isinstance(iv, (int, float)) or not math.isfinite(iv) or iv <= 0:
            return Unavailable("invalid_iv", f"leg IV must be finite and > 0, got {iv!r}", source)
        if iv > IV_PLAUSIBLE_MAX:
            return Unavailable(
                "invalid_iv",
                f"leg IV {iv} > {IV_PLAUSIBLE_MAX} — plausibly percent-not-decimal; refusing to reinterpret",
                source,
            )
        ivs.append(float(iv))

    sigma = sum(ivs) / len(ivs)  # documented assumption 1: equal-weight mean, all legs present
    t_years = float(dte) / 365.0
    mu = float(inputs.risk_free_rate)  # documented assumption 2: risk-neutral-ish drift
    prov = Provenance(
        source=source,
        version=CHALLENGER_VERSION,
        params_hash=params_hash(
            {
                "spot": float(spot),
                "sigma": sigma,
                "t_years": t_years,
                "mu": mu,
                "known_at": inputs.known_at,
            }
        ),
    )
    return LognormalTerminal(spot=float(spot), sigma=sigma, t_years=t_years, mu=mu, provenance=prov)


def challenger_lognormal_evaluate(
    structure: StructureSpec,
    inputs: Optional[DistributionInputs],
) -> EvalOutcome:
    """End-to-end challenger evaluation: build the lognormal (or abstain),
    then exact common payoff integration. Emits basis="raw" only."""
    dist = build_lognormal(structure, inputs)
    if isinstance(dist, Unavailable):
        return dist
    return integrate_structure(dist, structure, model=MODEL_NAME)
