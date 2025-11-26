import os
import time
import requests
import numpy as np
from qci_client import QciClient

class QciDiracAdapter:
    def __init__(self):
        self.token = os.getenv("QCI_API_TOKEN")
        self.api_url = os.getenv("QCI_API_URL", "https://api.qci-prod.com")

        if not self.token:
            raise ValueError("QCI_API_TOKEN not found.")

        self.client = QciClient(api_token=self.token, url=self.api_url)

    def solve_portfolio(self, mu, sigma, coskew, settings):
        """
        Trial-Optimized Solver for Dirac-3.
        Minimizes credit usage by requesting fewer samples and filtering noise.
        """
        num_assets = len(mu)
        budget = 100.0

        # --- TRIAL OPTIMIZATION 1: REDUCE PRECISION ---
        # Rounding float inputs prevents creating essentially duplicate terms
        # that bloat the problem file size.
        mu = np.round(mu, 6)
        sigma = np.round(sigma, 6)

        # Coefficients
        alpha = 1.0
        beta = settings.get('risk_aversion', 1.0)
        gamma = settings.get('skew_preference', 0.0)
        penalty_strength = settings.get('penalty_strength', 500.0)

        polynomial = []

        # Helper to add terms only if they matter (Save bandwidth)
        def add_term(coef, terms):
            if abs(coef) > 1e-6: # Ignore tiny noise
                polynomial.append({"coef": float(coef), "terms": terms})

        # 1. Constraint: (Sum(w) - 100)^2
        # Linear part
        for i in range(num_assets):
            add_term(-2.0 * penalty_strength * budget, [i])
        # Quadratic part
        for i in range(num_assets):
            for j in range(num_assets):
                add_term(penalty_strength, [i, j])

        # 2. Return (Linear)
        for i in range(num_assets):
            add_term(-1.0 * alpha * mu[i], [i])

        # 3. Variance (Quadratic)
        for i in range(num_assets):
            for j in range(num_assets):
                add_term(beta * sigma[i][j], [i, j])

        # 4. Skewness (Cubic) - The expensive part
        if gamma > 0:
            for i in range(num_assets):
                for j in range(num_assets):
                    for k in range(num_assets):
                        # AGGRESSIVE FILTERING for Trial
                        # Only include significant skew interactions
                        if abs(coskew[i][j][k]) > 1e-5:
                            add_term(-1.0 * gamma * coskew[i][j][k], [i, j, k])

        try:
            print(f"📡 Uploading {len(polynomial)} terms to QCI (Trial Mode)...")
            file_resp = self.client.upload_file(
                file={"polynomial": polynomial},
                file_type="polynomial_json"
            )

            # --- TRIAL OPTIMIZATION 2: JOB CONFIG ---
            job_body = self.client.build_job_body(
                job_type="sample-hamiltonian-integer",
                job_params={
                    "device_type": "dirac-3",
                    # KEY CHANGE: Only ask for 1 sample.
                    # Trials often cap total samples per day. We just need the best one.
                    "num_samples": 1,
                    "constraints": {
                        "var_min": 0,
                        "var_max": int(settings.get('max_position_pct', 0.40) * 100)
                    }
                },
                polynomial_file_id=file_resp["file_id"]
            )

            job_resp = self.client.submit_job(job_body)
            job_id = job_resp['job_id']

            # --- TRIAL OPTIMIZATION 3: GENTLE POLLING ---
            # Don't hammer their API; wait 2s between checks to avoid Rate Limits (429)
            start_time = time.time()
            while True:
                if time.time() - start_time > 60: # 60s Timeout for Trial
                    raise TimeoutError("QCI Job timed out (Trial restriction)")

                time.sleep(2)
                job_info = self.client.get_job_status(job_id)
                status = job_info['status']

                if status == "COMPLETED":
                    break
                if status == "ERROR":
                    # Check for quota errors
                    err_msg = job_info.get('error', '')
                    if "quota" in err_msg.lower() or "limit" in err_msg.lower():
                        raise ConnectionRefusedError(f"Trial Quota Exceeded: {err_msg}")
                    raise Exception(f"QCI Job Failed: {err_msg}")

            results = self.client.get_job_results(job_id)

            if not results.get('samples'):
                raise Exception("No solution found")

            # Return best sample, normalized to 0.0-1.0
            return [x / 100.0 for x in results['samples'][0]]

        except requests.exceptions.HTTPError as e:
            if e.response.status_code in [402, 403]:
                raise ConnectionRefusedError("Trial Expired or Payment Required")
            raise e