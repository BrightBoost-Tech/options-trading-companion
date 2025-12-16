import pathlib

def test_orchestrator_no_local_risk_budget_engine():
    p = pathlib.Path("packages/quantum/services/workflow_orchestrator.py")
    src = p.read_text(encoding="utf-8")
    assert "class RiskBudgetEngine" not in src
    assert "from packages.quantum.services.risk_budget_engine import RiskBudgetEngine" in src
