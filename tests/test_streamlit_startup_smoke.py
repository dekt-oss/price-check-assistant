from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
APP_FILES = (ROOT / "Home.py", *sorted((ROOT / "pages").glob("*.py")))


@pytest.mark.parametrize("app_path", APP_FILES, ids=lambda path: path.name)
def test_streamlit_page_starts_without_runtime_exception(app_path: Path) -> None:
    """Run every Streamlit entrypoint in a real ScriptRunner without clicking live actions.

    This catches production-only startup failures such as missing runtime dependencies at module
    import time. External API searches remain untouched because AppTest does not click buttons.
    """

    app = AppTest.from_file(str(app_path), default_timeout=15)
    app.run()

    errors = [str(item.value) for item in app.exception]
    assert errors == [], f"{app_path.relative_to(ROOT)} startup failed: {errors}"
