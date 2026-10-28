"""Review E-01: the diagnostics readout names the runtime without secrets."""

import platform

from purchase_price.ui import memory_diagnostic


def test_runtime_line_names_python_os_and_key_packages(monkeypatch) -> None:
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "never-shown")
    line = memory_diagnostic.runtime_line()

    assert line.startswith(f"RUNTIME python={platform.python_version()} · os=")
    for name in memory_diagnostic.RUNTIME_PACKAGES:
        assert f" · {name}=" in line
    assert "never-shown" not in line
