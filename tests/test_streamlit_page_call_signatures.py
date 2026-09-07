"""Bind every Streamlit page call to the real callable signature.

`pages/*.py` and `Home.py` are executed by Streamlit at runtime and are never imported by
pytest, so a keyword-only parameter added to a `purchase_price` helper can break Production
while the whole unit suite stays green. That is how the quick-search research-basis crash
shipped: `render_market_reference_summary` gained a required `query` keyword, `ui/` call sites
were updated, `pages/3_빠른_검색.py` was not, and the page raised `TypeError` as soon as
shopping research returned a result.

This test resolves each imported `purchase_price` name and binds the call site's arity and
keyword names against `inspect.signature`. Argument *values* are never evaluated, so no
Streamlit runtime or API key is required.
"""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PREFIX = "purchase_price"


def streamlit_entrypoints() -> list[Path]:
    return sorted(ROOT.glob("pages/*.py")) + [ROOT / "Home.py"]


def _imported_callables(tree: ast.Module) -> dict[str, tuple[str, str]]:
    """Map local name -> (module, attribute) for `from purchase_price... import ...` names."""

    imported: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if not node.module or not node.module.startswith(PACKAGE_PREFIX):
            continue
        for alias in node.names:
            if alias.name == "*":
                continue
            imported[alias.asname or alias.name] = (node.module, alias.name)
    return imported


def _binding_errors(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported = _imported_callables(tree)
    errors: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        target = imported.get(node.func.id)
        if target is None:
            continue
        module_name, attribute = target
        function = getattr(importlib.import_module(module_name), attribute, None)
        if not callable(function):
            continue
        try:
            signature = inspect.signature(function)
        except (TypeError, ValueError):  # pragma: no cover - builtins without signatures
            continue

        # `*args`/`**kwargs` unpacking at a call site hides the real arity from AST alone.
        if any(isinstance(argument, ast.Starred) for argument in node.args):
            continue
        if any(keyword.arg is None for keyword in node.keywords):
            continue

        positional = [None] * len(node.args)
        keywords = {keyword.arg: None for keyword in node.keywords if keyword.arg}
        try:
            signature.bind(*positional, **keywords)
        except TypeError as exc:
            errors.append(
                f"{path.relative_to(ROOT).as_posix()}:{node.lineno} "
                f"{module_name}.{attribute}{signature} -> {exc}"
            )
    return errors


def test_streamlit_pages_call_purchase_price_helpers_with_valid_signatures() -> None:
    entrypoints = streamlit_entrypoints()
    assert entrypoints, "No Streamlit entrypoints found"

    errors = [error for path in entrypoints if path.exists() for error in _binding_errors(path)]
    assert errors == [], (
        "Streamlit pages are not covered by imports in the unit suite, so a signature change "
        "here reaches Production as a runtime TypeError. Fix these call sites:\n"
        + "\n".join(errors)
    )
