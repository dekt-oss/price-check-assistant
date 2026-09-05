import importlib
import pathlib

AppTest = importlib.import_module("streamlit.testing.v1").AppTest
ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_FILES = (ROOT / "Home.py", *sorted((ROOT / "pages").glob("*.py")))


def test_all_streamlit_pages_start_without_runtime_exception() -> None:
    """Run every Streamlit entrypoint in a real ScriptRunner without clicking live actions.

    This catches production-only startup failures such as missing runtime dependencies at module
    import time. External API searches remain untouched because AppTest does not click buttons.
    All page failures are aggregated so one CI run reports the full startup regression set.
    """

    failures: list[str] = []
    for app_path in APP_FILES:
        app = AppTest.from_file(str(app_path), default_timeout=15)
        app.run()
        errors = [str(item.value) for item in app.exception]
        if errors:
            failures.append(f"{app_path.relative_to(ROOT)}: {errors}")

    assert failures == [], "Streamlit startup failures:\n" + "\n".join(failures)
