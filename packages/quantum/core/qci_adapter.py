import os
import time
import numpy as np
from qci_client import QciClient

class QciDiracAdapter:
    def __init__(self):
        # API Token must be in .env: QCI_API_TOKEN=...
        self.token = os.getenv("QCI_API_TOKEN")
        self.api_url = os.getenv("QCI_API_URL", "https://api.qci-prod.com")

        if not self.token:
            print("WARNING: No QCI_API_TOKEN found. Quantum calls will fail.")

        self.client = QciClient(api_token=self.token, url=self.api_url)

    def solve_portfolio(self, mu, sigma, coskew, settings):
        """
        Submits a job to Dirac-3.
        Variables w_i are Integers [0, 100] representing percentage weight.
        """
        num_assets = len(mu)
        budget = 100.0 # Total weights must sum to 100

        # Coefficients
        alpha = 1.0  # Return weight
        # Risk aversion (Lambda) matches user setting
        beta = settings.get('risk_aversion', 1.0)
        # Skew preference (Gamma) matches user setting
        gamma = settings.get('skew_preference', 0.0)
        # Constraint Penalty (Must be huge to force sum=100)
        penalty_strength = settings.get('penalty_strength', 500.0)

        # --- BUILD THE POLYNOMIAL ---
        # Objective: Min( -Alpha*Return + Beta*Risk - Gamma*Skew + Penalty*(Sum(w)-Budget)^2 )
        polynomial = []

        # 1. EXPAND CONSTRAINT: P * (Sum(w) - B)^2
        # (Sum w)^2 - 2B(Sum w) + B^2
        # = Sum(w_i^2) + Sum(w_i w_j) - 2B Sum(w_i)

        # 1a. Linear Constraint Term: -2 * P * B * w_i
        for i in range(num_assets):
            term_val = -2.0 * penalty_strength * budget
            self._add_term(polynomial, term_val, [i])

        # 1b. Quadratic Constraint Terms: P * w_i * w_j (and w_i^2)
        for i in range(num_assets):
            for j in range(num_assets):
                self._add_term(polynomial, penalty_strength, [i, j])

        # 2. EXPECTED RETURN (Linear): -Alpha * mu_i * w_i
        for i in range(num_assets):
            term_val = -1.0 * alpha * mu[i]
            self._add_term(polynomial, term_val, [i])

        # 3. VARIANCE (Quadratic): Beta * sigma_ij * w_i * w_j
        for i in range(num_assets):
            for j in range(num_assets):
                term_val = beta * sigma[i][j]
                self._add_term(polynomial, term_val, [i, j])

        # 4. SKEWNESS (Cubic): -Gamma * phi_ijk * w_i * w_j * w_k
        # This is the Dirac-3 special ability
        if gamma > 0:
            for i in range(num_assets):
                for j in range(num_assets):
                    for k in range(num_assets):
                        if abs(coskew[i][j][k]) > 1e-7: # Optimization: Ignore zero terms
                            term_val = -1.0 * gamma * coskew[i][j][k]
                            self._add_term(polynomial, term_val, [i, j, k])

        # --- SUBMIT JOB ---
        print(f"Submitting job to Dirac-3 with {len(polynomial)} terms...")

        # Upload the problem definition
        file_resp = self.client.upload_file(
            file={"polynomial": polynomial},
            file_type="polynomial_json"
        )

        # Define Job
        job_body = self.client.build_job_body(
            job_type="sample-hamiltonian-integer",
            job_params={
                "device_type": "dirac-3",
                "num_samples": 5, # We only need the best few samples
                # Constraints on individual variables (0% to 100%)
                "constraints": {
                    "var_min": 0,
                    "var_max": int(settings.get('max_position_pct', 0.40) * 100)
                }
            },
            polynomial_file_id=file_resp["file_id"]
        )

        # Submit
        job_resp = self.client.submit_job(job_body)
        job_id = job_resp['job_id']

        # Poll for results
        status = "QUEUED"
        while status in ["QUEUED", "RUNNING", "SUBMITTED"]:
            time.sleep(1) # Don't spam API
            job_info = self.client.get_job_status(job_id)
            status = job_info['status']
            if status == "COMPLETED":
                break
            if status == "ERROR":
                raise Exception(f"QCI Job Failed: {job_info.get('error')}")

        # Get Results
        results = self.client.get_job_results(job_id)

        # Parse: results['samples'] is a list of lists of integers
        # We take the one with the lowest energy (best objective)
        best_sample = results['samples'][0]

        # Convert integers (0-100) back to floats (0.0-1.0)
        return [x / 100.0 for x in best_sample]

    def _add_term(self, polynomial, coef, indices):
        """Helper to append or merge terms in the sparse polynomial format"""
        # Simple append for clarity; QCI client usually handles summing duplicates automatically
        # or we could implement a dictionary merge here for efficiency.
        if abs(coef) > 1e-9:
            polynomial.append({"coef": coef, "terms": indices})
