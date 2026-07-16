"""Calibration report distinguishes fetch failure from an empty cohort."""

from packages.quantum.analytics.calibration_service import CalibrationService


class _FetchControlledCalibrationService(CalibrationService):
    def __init__(self, outcome):
        super().__init__(None)
        self.outcome = outcome

    def _fetch_outcomes(self, user_id, window_days):
        return self.outcome


def test_report_fetch_failure_is_typed_error_not_green_no_data():
    result = _FetchControlledCalibrationService(None).compute_calibration_report(
        "user", window_days=30
    )

    assert result == {
        "status": "error",
        "reason": "fetch_failed",
        "window_days": 30,
    }


def test_report_legitimate_empty_cohort_remains_no_data():
    result = _FetchControlledCalibrationService([]).compute_calibration_report(
        "user", window_days=30
    )

    assert result == {
        "status": "no_data",
        "sample_size": 0,
        "window_days": 30,
    }
