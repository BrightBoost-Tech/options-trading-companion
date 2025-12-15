import types
import sys
import packages.quantum
from packages.quantum import paper_endpoints

def test_paper_endpoints_lazy_imports_use_packages_quantum_api(monkeypatch):
    fake_api = types.ModuleType("packages.quantum.api")

    sentinel_supabase = object()
    sentinel_analytics = object()

    fake_api.supabase_admin = sentinel_supabase
    fake_api.analytics_service = sentinel_analytics

    # Ensure the import machinery finds our stub
    monkeypatch.setitem(sys.modules, "packages.quantum.api", fake_api)
    monkeypatch.setattr(packages.quantum, "api", fake_api, raising=False)

    assert paper_endpoints.get_supabase() is sentinel_supabase
    assert paper_endpoints.get_analytics_service() is sentinel_analytics
