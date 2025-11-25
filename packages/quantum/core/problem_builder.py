def build_polynomial(mu, sigma, coskew, lambda_risk=1.0, gamma_skew=0.0):
    """
    Constructs the polynomial terms for the objective function.
    Objective: Minimize (-Return + Lambda*Var - Gamma*Skew)

    Args:
        mu (1D): Expected returns
        sigma (2D): Covariance
        coskew (3D): Co-skewness
        lambda_risk: Penalty for variance (Risk Aversion)
        gamma_skew: Reward for positive skew (Tail Risk preference)
    """
    polynomial = []
    num_assets = len(mu)

    # 1. Linear Terms (Expected Return)
    # We want to MAXIMIZE return, so we MINIMIZE negative return.
    for i in range(num_assets):
        polynomial.append({
            "coef": -1.0 * mu[i],
            "terms": [i]
        })

    # 2. Quadratic Terms (Variance)
    # We want to MINIMIZE Variance.
    for i in range(num_assets):
        for j in range(num_assets):
            val = sigma[i][j]
            if abs(val) > 1e-8:
                polynomial.append({
                    "coef": lambda_risk * val,
                    "terms": [i, j]
                })

    # 3. Cubic Terms (Skewness)
    # We want to MAXIMIZE Positive Skewness, so we MINIMIZE negative Skew.
    if gamma_skew != 0:
        for i in range(num_assets):
            for j in range(num_assets):
                for k in range(num_assets):
                    val = coskew[i][j][k]
                    # Filter tiny floating point noise
                    if abs(val) > 1e-6:
                        polynomial.append({
                            "coef": -1.0 * gamma_skew * val,
                            "terms": [i, j, k]
                        })

    return polynomial
