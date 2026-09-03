from purchase_price.scripts import doctor
from purchase_price.scripts.doctor import CheckResult, format_report, run_checks


def test_required_failure_blocks_but_optional_skip_does_not() -> None:
    required_fail = CheckResult("package", doctor.FAIL, "missing")
    optional_fail = CheckResult("database", doctor.SKIP, "not reachable", required=False)

    assert required_fail.blocking
    assert not optional_fail.blocking
    assert not CheckResult("python", doctor.OK, "3.11").blocking


def test_report_marks_blocked_when_a_required_check_fails() -> None:
    report = format_report(
        [
            CheckResult("python", doctor.OK, "3.11.9"),
            CheckResult("package", doctor.FAIL, "not importable", hint='pip install -e ".[dev]"'),
            CheckResult("database", doctor.SKIP, "not reachable", required=False),
        ]
    )

    assert "doctor_status=blocked failed=package" in report
    assert 'pip install -e ".[dev]"' in report


def test_report_is_ready_when_only_optional_checks_are_skipped() -> None:
    report = format_report(
        [
            CheckResult("python", doctor.OK, "3.11.9"),
            CheckResult("database", doctor.SKIP, "not reachable", required=False),
        ]
    )

    assert "doctor_status=ready optional_unavailable=database" in report
    assert "blocked" not in report


def test_real_environment_has_no_blocking_check(capsys) -> None:
    # The checked-out repo must always be workable without a database or a service key.
    results = run_checks()
    blocking = [result.name for result in results if result.blocking]

    assert blocking == [], f"blocking checks in a clean checkout: {blocking}"
    assert doctor.main([]) == 0
    assert "doctor_status=" in capsys.readouterr().out


def test_service_key_value_is_never_printed(monkeypatch) -> None:
    from purchase_price.config import Settings, get_settings

    secret = "SUPER-SECRET-KEY-VALUE"
    get_settings.cache_clear()
    monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", secret)
    try:
        assert Settings().data_go_kr_service_key == secret
        report = format_report(run_checks())
    finally:
        get_settings.cache_clear()

    assert secret not in report


def test_database_error_reports_a_reason_for_an_unreachable_url(monkeypatch) -> None:
    from purchase_price.config import get_settings
    from purchase_price.scripts.doctor import database_error

    get_settings.cache_clear()
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://nobody:nobody@127.0.0.1:1/does_not_exist"
    )
    try:
        reason = database_error()
    finally:
        get_settings.cache_clear()

    assert reason is not None
    assert len(reason.splitlines()) == 1
