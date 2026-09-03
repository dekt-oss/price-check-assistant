"""Report whether this machine can run the project, without changing anything.

Required checks must pass before code work is meaningful (interpreter, package import,
lint/test tooling, data registries). Optional checks describe capabilities that only some
tasks need: a PostgreSQL connection is needed for the Streamlit demo and ingestion, a
data.go.kr service key is needed only for live G2B calls, and a .env file only overrides
settings that already have working defaults. Optional failures are reported as SKIP so a
developer without Docker or without a key, and CI without a .env, still get a usable verdict.

The service key is never printed; only whether one is configured.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MIN_PYTHON = (3, 11)

OK = "OK"
FAIL = "FAIL"
SKIP = "SKIP"


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str
    hint: str | None = None
    required: bool = True

    @property
    def blocking(self) -> bool:
        return self.required and self.status == FAIL


def _python_check() -> CheckResult:
    version = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info < MIN_PYTHON:
        return CheckResult(
            "python",
            FAIL,
            f"{version} (need >= {'.'.join(str(p) for p in MIN_PYTHON)})",
            hint="Install Python 3.11+ and recreate .venv with it.",
        )
    in_venv = sys.prefix != sys.base_prefix
    detail = f"{version}{'' if in_venv else ' (not in a virtualenv)'}"
    hint = None if in_venv else "Activate the project venv so tools resolve from it."
    return CheckResult("python", OK, detail, hint=hint)


def _package_check() -> CheckResult:
    try:
        import purchase_price  # noqa: F401
    except ImportError as exc:
        return CheckResult(
            "package",
            FAIL,
            f"purchase_price is not importable: {exc}",
            hint='Run: pip install -e ".[dev]"',
        )
    return CheckResult("package", OK, f"purchase_price from {PROJECT_ROOT}")


def _tooling_check() -> CheckResult:
    missing = [name for name in ("ruff", "pytest") if shutil.which(name) is None]
    # A console script can be absent while the module is importable (e.g. `python -m pytest`).
    missing = [name for name in missing if importlib.util.find_spec(name) is None]
    if missing:
        return CheckResult(
            "dev tooling",
            FAIL,
            f"missing: {', '.join(missing)}",
            hint='Run: pip install -e ".[dev]"',
        )
    return CheckResult("dev tooling", OK, "ruff and pytest available")


def _streamlit_check() -> CheckResult:
    if importlib.util.find_spec("streamlit") is None:
        return CheckResult(
            "streamlit",
            FAIL,
            "streamlit is not installed",
            hint='Run: pip install -e ".[dev]"',
        )
    return CheckResult("streamlit", OK, "importable; run `streamlit run Home.py`")


def _env_file_check() -> CheckResult:
    """A .env only overrides defaults, so its absence is reported, never treated as broken.

    Settings falls back to the values in Settings itself and to the process environment, which
    is how CI runs the whole suite without a .env at all.
    """

    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        return CheckResult("env file", OK, f"{env_path.name} present", required=False)
    return CheckResult(
        "env file",
        SKIP,
        ".env not found; using built-in defaults and the process environment",
        hint="Copy .env.example to .env to change DATABASE_URL or add a service key. Never commit the real key.",
        required=False,
    )


def _count_csv_rows(path: Path, predicate=None) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return sum(1 for row in rows if predicate is None or predicate(row))


def _data_registry_check() -> CheckResult:
    products = PROJECT_ROOT / "data" / "phase0_products.csv"
    mappings = PROJECT_ROOT / "data" / "g2b_product_mappings.csv"
    ground_truth = PROJECT_ROOT / "data" / "phase0_match_ground_truth.csv"
    missing = [p.name for p in (products, mappings, ground_truth) if not p.exists()]
    if missing:
        return CheckResult(
            "data registries",
            FAIL,
            f"missing: {', '.join(missing)}",
            hint="Re-clone or restore the data/ directory from git.",
        )
    try:
        benchmark_rows = _count_csv_rows(products)
        verified = _count_csv_rows(
            mappings,
            lambda row: (row.get("mapping_status") or "").strip().casefold() == "verified",
        )
        gt_rows = _count_csv_rows(ground_truth)
    except (OSError, csv.Error) as exc:
        return CheckResult("data registries", FAIL, f"unreadable: {exc}")
    return CheckResult(
        "data registries",
        OK,
        f"benchmark={benchmark_rows} verified_g2b_mappings={verified} ground_truth={gt_rows}",
    )


def _service_key_check() -> CheckResult:
    try:
        from purchase_price.config import get_settings

        configured = bool(get_settings().data_go_kr_service_key)
    except Exception as exc:  # settings parsing is the only thing that can fail here
        return CheckResult("g2b service key", SKIP, f"settings unreadable: {exc}", required=False)
    if configured:
        # Never print the value, only that one is present.
        return CheckResult("g2b service key", OK, "configured (value not shown)", required=False)
    return CheckResult(
        "g2b service key",
        SKIP,
        "not configured; live G2B calls unavailable",
        hint="Local live calls need DATA_GO_KR_SERVICE_KEY in .env. Everything else works without it.",
        required=False,
    )


def database_error() -> str | None:
    """Return None when DATABASE_URL accepts a connection, else a one-line reason.

    The setup scripts call this to decide whether to apply migrations, so that a developer
    running a local PostgreSQL without Docker is not treated as having no database.
    """

    try:
        from sqlalchemy import create_engine, text

        from purchase_price.config import get_settings
    except ImportError as exc:
        return f"SQLAlchemy unavailable: {exc}"

    try:
        engine = create_engine(
            get_settings().database_url, connect_args={"connect_timeout": 3}
        )
        with engine.connect() as connection:
            connection.execute(text("select 1"))
    except Exception as exc:
        return str(exc).splitlines()[0][:160]
    return None


def _database_check() -> CheckResult:
    reason = database_error()
    if reason is None:
        return CheckResult("database", OK, "connected", required=False)
    return CheckResult(
        "database",
        SKIP,
        f"not reachable: {reason}",
        hint="Start it with `docker compose up -d db`, or point DATABASE_URL at a local PostgreSQL 16.",
        required=False,
    )


def _migration_check(database_reachable: bool) -> CheckResult:
    if not database_reachable:
        return CheckResult("migrations", SKIP, "database not reachable", required=False)
    try:
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory
        from sqlalchemy import create_engine

        from purchase_price.config import get_settings
    except ImportError as exc:
        return CheckResult("migrations", SKIP, f"alembic unavailable: {exc}", required=False)

    try:
        config = Config(str(PROJECT_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
        heads = set(ScriptDirectory.from_config(config).get_heads())
        engine = create_engine(get_settings().database_url, connect_args={"connect_timeout": 3})
        with engine.connect() as connection:
            current = set(MigrationContext.configure(connection).get_current_heads())
    except Exception as exc:
        return CheckResult(
            "migrations", SKIP, f"could not be read: {str(exc).splitlines()[0][:160]}", required=False
        )

    if not current:
        return CheckResult(
            "migrations",
            SKIP,
            "no migration applied yet",
            hint="Run: python -m purchase_price.scripts.init_db",
            required=False,
        )
    if current != heads:
        return CheckResult(
            "migrations",
            SKIP,
            f"applied={sorted(current)} head={sorted(heads)}",
            hint="Run: python -m purchase_price.scripts.init_db",
            required=False,
        )
    return CheckResult("migrations", OK, f"at head {sorted(heads)}", required=False)


def run_checks() -> list[CheckResult]:
    results = [
        _python_check(),
        _package_check(),
        _tooling_check(),
        _streamlit_check(),
        _env_file_check(),
        _data_registry_check(),
        _service_key_check(),
    ]
    database = _database_check()
    results.append(database)
    results.append(_migration_check(database.status == OK))
    return results


def format_report(results: list[CheckResult]) -> str:
    width = max(len(result.name) for result in results)
    lines = []
    for result in results:
        lines.append(f"[{result.status:<4}] {result.name.ljust(width)}  {result.detail}")
        if result.hint and result.status != OK:
            lines.append(f"{' ' * (width + 10)}→ {result.hint}")
    blocking = [result for result in results if result.blocking]
    skipped = [result for result in results if result.status == SKIP]
    lines.append("")
    if blocking:
        lines.append(f"doctor_status=blocked failed={','.join(r.name for r in blocking)}")
    elif skipped:
        lines.append(f"doctor_status=ready optional_unavailable={','.join(r.name for r in skipped)}")
    else:
        lines.append("doctor_status=ready")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Check whether this machine can run the project. Required checks gate the exit "
            "code; the database and the G2B service key are optional and reported as SKIP."
        )
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Also exit 1 when an optional capability (database, service key) is unavailable.",
    )
    args = parser.parse_args(argv)

    results = run_checks()
    print(format_report(results))

    if any(result.blocking for result in results):
        return 1
    if args.strict and any(result.status == SKIP for result in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
