import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone
from packages.quantum.jobs.handlers.regression_determinism import run

@patch("packages.quantum.jobs.handlers.regression_determinism.create_supabase_admin_client")
@patch("packages.quantum.jobs.handlers.regression_determinism.AuditLogService")
@patch("packages.quantum.jobs.handlers.regression_determinism.get_code_sha")
@patch("packages.quantum.jobs.handlers.regression_determinism.LineageSigner")
def test_regression_determinism_run(mock_lineage_signer, mock_get_code_sha, mock_audit_service_cls, mock_get_client):
    # Setup mocks
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client

    mock_audit_service = MagicMock()
    mock_audit_service_cls.return_value = mock_audit_service

    mock_get_code_sha.return_value = "sha123"

    # Mock LineageSigner.verify_with_hash
    # Returns (is_valid, computed_hash, status)
    mock_lineage_signer.verify_with_hash.return_value = (True, "hash123", "VERIFIED")

    # Mock Supabase response
    mock_table = MagicMock()
    mock_client.table.return_value = mock_table
    mock_select = MagicMock()
    mock_table.select.return_value = mock_select
    mock_gte = MagicMock()
    mock_select.gte.return_value = mock_gte

    # Sample data
    suggestions_data = [
        {
            "id": "s1",
            "trace_id": "t1",
            "features_hash": "fh1",
            "lineage_hash": "lh1",
            "code_sha": "sha123", # Matches
            "data_hash": "dh1",
            "lineage_sig": "sig1",
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": "s2",
            "trace_id": "t2",
            # Missing features_hash
            "lineage_hash": "lh2",
            "code_sha": "shaOLD", # Mismatch
            "data_hash": "dh2",
            "lineage_sig": "sig2",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
    ]

    mock_execute = MagicMock()
    mock_execute.data = suggestions_data
    mock_gte.execute.return_value = mock_execute

    # Mock s2 signature failure for variety (optional, but let's stick to mocks above)
    # Actually mock_lineage_signer.verify_with_hash is static/class method usually,
    # but patch mocks the class so calls on it work.
    # However, verify_with_hash is called with different args.
    # Let's make it return False for s2 if we can.

    def verify_side_effect(stored_hash, stored_signature, data=None):
        if stored_hash == "lh2":
            return (False, "lh2", "TAMPERED")
        return (True, stored_hash, "VERIFIED")

    mock_lineage_signer.verify_with_hash.side_effect = verify_side_effect

    # Run
    payload = {"lookback_days": 1}
    result = run(payload)

    # Assertions
    assert result["status"] == "completed"
    stats = result["result"]["stats"]

    # s1: OK
    # s2: Missing features_hash (integrity failure) AND code mismatch (code drift) AND sig mismatch (data drift)

    # Total checked: 2
    assert stats["total_checked"] == 2

    # Integrity failures: s2 is missing features_hash
    assert stats["integrity_failures"] == 1

    # Code drift: s2 has shaOLD != sha123
    assert stats["code_drift_count"] == 1

    # Data drift: s2 has TAMPERED signature
    assert stats["data_drift_count"] == 1

    # Verify audit event logged
    mock_audit_service.log_audit_event.assert_called_once()
    call_args = mock_audit_service.log_audit_event.call_args
    assert call_args[1]["event_name"] == "v4_regression_report"
