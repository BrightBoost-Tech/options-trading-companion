import argparse
import json
import time
import os
import sys
from typing import List, Dict, Any

# Ensure project root is in sys.path
# This assumes the script is located at packages/quantum/discrete/benchmarks/run_benchmarks.py
# and the project root is 4 levels up.
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, "../../../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from packages.quantum.discrete.benchmarks.scenarios import (
    generate_cash_tight_knapsack,
    generate_greek_tight,
    generate_tail_coupled,
    Scenario
)
from packages.quantum.discrete.polynomial_builder import build_discrete_polynomial, DiscreteOptimizationRequest

# Attempt to import QCI client, handle if missing
try:
    from qci_client import QciClient
    QCI_AVAILABLE = True
except ImportError:
    QCI_AVAILABLE = False

def run_classical_baseline(scenario: Scenario) -> Dict[str, Any]:
    """
    Greedy solver: Sort by EV/Premium ratio and fill until constraint met.
    """
    req = scenario.request
    start_time = time.time()

    candidates = sorted(
        req.candidates,
        key=lambda c: c.ev / (c.premium if c.premium > 0 else 0.001),
        reverse=True
    )

    selected_indices = []
    current_cash = 0.0
    limit_cash = req.max_cash if req.max_cash is not None else float('inf')

    for i, cand in enumerate(candidates):
        if current_cash + cand.premium <= limit_cash:
            selected_indices.append(cand.id)
            current_cash += cand.premium

    runtime_ms = (time.time() - start_time) * 1000.0

    # Calculate Objective Value
    utility = sum(c.ev - c.premium for c in req.candidates if c.id in selected_indices)
    tail_sum = sum(c.tail_risk for c in req.candidates if c.id in selected_indices)
    prem_sum = sum(c.premium for c in req.candidates if c.id in selected_indices)

    penalty_tail = req.lambda_tail * (tail_sum ** 2)
    penalty_cash = 0.0
    if req.max_cash:
        overage = max(0.0, prem_sum - req.max_cash)
        penalty_cash = req.lambda_cash * (overage ** 2)

    objective_value = -utility + penalty_tail + penalty_cash

    total_ev = sum(c.ev for c in req.candidates if c.id in selected_indices)
    total_premium = sum(c.premium for c in req.candidates if c.id in selected_indices)

    return {
        "solver": "classical_greedy",
        "selected_count": len(selected_indices),
        "total_ev": total_ev,
        "total_premium": total_premium,
        "objective_value": objective_value,
        "runtime_ms": runtime_ms,
        "feasible": total_premium <= limit_cash
    }

def run_dirac_solver(
    scenario: Scenario,
    token: str,
    num_samples: int,
    timeout_sec: int
) -> Dict[str, Any]:
    """
    Runs the scenario on QCI Dirac-3 (or mock if smoke mode requires it).
    """
    if not QCI_AVAILABLE:
        return {
            "solver": "dirac_3",
            "status": "skipped",
            "reason": "qci_client_missing"
        }

    if not token:
        return {
            "solver": "dirac_3",
            "status": "skipped",
            "reason": "missing_token"
        }

    req = scenario.request

    # Build polynomial
    start_build = time.time()
    terms, scale_info, index_map = build_discrete_polynomial(req)
    build_ms = (time.time() - start_build) * 1000.0

    if not terms:
         return {
            "solver": "dirac_3",
            "status": "error",
            "reason": "empty_polynomial"
        }

    client = QciClient(api_token=token)

    try:
        # Upload
        file_resp = client.upload_file(
            file={"polynomial": terms},
            file_type="polynomial_json"
        )

        # Submit Job
        job_body = client.build_job_body(
            job_type="sample-hamiltonian-integer",
            job_params={
                "device_type": "dirac-3",
                "num_samples": num_samples,
                "constraints": {
                    "var_min": 0,
                    "var_max": 1 # Binary selection
                }
            },
            polynomial_file_id=file_resp["file_id"]
        )

        job_resp = client.submit_job(job_body)
        job_id = job_resp['job_id']

        # Poll
        start_poll = time.time()

        while True:
            if time.time() - start_poll > timeout_sec:
                return {"solver": "dirac_3", "status": "timeout"}

            status_resp = client.get_job_status(job_id)
            status = status_resp['status']

            if status == "COMPLETED":
                break
            if status == "ERROR":
                return {"solver": "dirac_3", "status": "error", "details": status_resp.get('error')}

            time.sleep(1)

        results = client.get_job_results(job_id)
        samples = results.get('samples', [])

        if not samples:
            return {"solver": "dirac_3", "status": "no_solution"}

        best_sample = samples[0] # List of integers

        # Map back to candidates
        rev_map = {v: k for k, v in index_map.items()}
        selected_ids = []

        for i, val in enumerate(best_sample):
            if val >= 1: # binary 1
                if i in rev_map:
                    selected_ids.append(rev_map[i])

        # Calculate metrics
        total_ev = sum(c.ev for c in req.candidates if c.id in selected_ids)
        total_premium = sum(c.premium for c in req.candidates if c.id in selected_ids)
        tail_sum = sum(c.tail_risk for c in req.candidates if c.id in selected_ids)

        utility = sum(c.ev - c.premium for c in req.candidates if c.id in selected_ids)
        penalty_tail = req.lambda_tail * (tail_sum ** 2)
        penalty_cash = 0.0
        if req.max_cash:
            overage = max(0.0, total_premium - req.max_cash)
            penalty_cash = req.lambda_cash * (overage ** 2)

        objective_value = -utility + penalty_tail + penalty_cash

        return {
            "solver": "dirac_3",
            "selected_count": len(selected_ids),
            "total_ev": total_ev,
            "total_premium": total_premium,
            "objective_value": objective_value,
            "runtime_ms": (time.time() - start_poll) * 1000.0,
            "build_ms": build_ms,
            "feasible": True
        }

    except Exception as e:
        return {
            "solver": "dirac_3",
            "status": "exception",
            "details": str(e)
        }

def main():
    parser = argparse.ArgumentParser(description="Discrete Selection Benchmark Harness")
    parser.add_argument("--mode", choices=["classical", "dirac-smoke", "full"], default="classical")
    args = parser.parse_args()

    mode = args.mode

    # Configuration based on mode
    if mode == "dirac-smoke":
        scenario_configs = [
            ("cash_tight_knapsack", 25, 500.0),
            ("greek_tight", 20, 50.0)
        ]
        max_dirac_calls = 2
        num_samples = 5
        timeout_sec = 8
    elif mode == "full":
        scenario_configs = [
            ("cash_tight_knapsack", 50, 1000.0),
            ("greek_tight", 40, 100.0),
            ("tail_coupled", 30, 0.0)
        ]
        max_dirac_calls = 10
        num_samples = 20
        timeout_sec = 60
    else: # classical
        scenario_configs = [
            ("cash_tight_knapsack", 50, 1000.0),
            ("greek_tight", 40, 100.0),
            ("tail_coupled", 30, 0.0)
        ]
        max_dirac_calls = 0
        num_samples = 0
        timeout_sec = 0

    results = {
        "mode": mode,
        "scenarios": []
    }

    qci_token = os.getenv("QCI_API_TOKEN")
    dirac_calls_made = 0

    sys.stderr.write(f"Running Benchmark in {mode} mode...\n")

    for name, n, param in scenario_configs:
        seed = 42 # Deterministic

        if name == "cash_tight_knapsack":
            scen = generate_cash_tight_knapsack(seed, n, param)
        elif name == "greek_tight":
            scen = generate_greek_tight(seed, n, param)
        elif name == "tail_coupled":
            scen = generate_tail_coupled(seed, n)
        else:
            continue

        scen_result = {
            "name": name,
            "description": scen.description,
            "classical": run_classical_baseline(scen)
        }

        # Run Dirac if mode allows and budget permits
        if mode in ["dirac-smoke", "full"]:
            if dirac_calls_made < max_dirac_calls:
                d_res = run_dirac_solver(scen, qci_token, num_samples, timeout_sec)
                scen_result["dirac"] = d_res

                if d_res.get("status") not in ["skipped", "error", "exception"]:
                    dirac_calls_made += 1
            else:
                 scen_result["dirac"] = {"status": "budget_exceeded"}

        results["scenarios"].append(scen_result)

    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    main()
