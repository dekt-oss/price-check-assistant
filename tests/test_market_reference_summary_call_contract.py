import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TARGET = "render_market_reference_summary"
QUOTE_UI = SRC / "purchase_price" / "ui" / "quote_market_research.py"


def _streamlit_entrypoints() -> list[Path]:
    """Return the Streamlit page modules pytest never imports.

    `pages/` is executed by Streamlit at runtime, not collected by pytest. A keyword-only
    parameter added to a `ui/` renderer therefore breaks Production while every unit test stays
    green, which is exactly how the quick-search research-basis crash shipped.
    """

    return sorted(ROOT.glob("pages/*.py")) + [ROOT / "Home.py"]


def _call_sites() -> list[Path]:
    return sorted(SRC.rglob("*.py")) + _streamlit_entrypoints()


def _target_calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == TARGET:
            calls.append(node)
        elif isinstance(func, ast.Attribute) and func.attr == TARGET:
            calls.append(node)
    return calls


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def test_all_market_reference_summary_calls_pass_query_keyword() -> None:
    """Keep quote/product context wired into the research-basis renderer at every call site."""

    found: list[tuple[Path, ast.Call]] = []
    for path in _call_sites():
        found.extend((path, call) for call in _target_calls(path))

    assert found, f"No {TARGET} call sites found under {SRC} or the Streamlit entrypoints"

    missing = [
        f"{path.relative_to(ROOT)}:{getattr(call, 'lineno', '?')}"
        for path, call in found
        if not any(keyword.arg == "query" for keyword in call.keywords)
    ]
    assert missing == [], (
        f"Every {TARGET} call must pass query= so the displayed basis is tied to the quote item. "
        f"Missing at: {', '.join(missing)}"
    )


def test_quote_item_research_sections_keep_decision_useful_order() -> None:
    """Lock the item screen order: basis, direct price, alternatives, then procurement context."""

    tree = ast.parse(QUOTE_UI.read_text(encoding="utf-8"), filename=str(QUOTE_UI))
    render_item = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_render_item_result"
    )
    lines = {
        name: call.lineno
        for call in ast.walk(render_item)
        if isinstance(call, ast.Call)
        and (name := _call_name(call))
        in {
            "render_market_reference_summary",
            "assess_prices",
            "render_model_price_research_summary",
            "render_market_alternative_candidates",
            "render_procurement_research",
        }
    }
    expected = [
        "render_market_reference_summary",
        "assess_prices",
        "render_model_price_research_summary",
        "render_market_alternative_candidates",
        "render_procurement_research",
    ]
    assert set(expected) <= lines.keys(), f"Missing required quote item section calls: {lines}"
    assert [lines[name] for name in expected] == sorted(lines[name] for name in expected)
