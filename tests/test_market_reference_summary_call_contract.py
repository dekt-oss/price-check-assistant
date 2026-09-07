import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TARGET = "render_market_reference_summary"


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


def test_all_market_reference_summary_calls_pass_query_keyword() -> None:
    """Keep quote/product context wired into the research-basis renderer at every call site."""

    found: list[tuple[Path, ast.Call]] = []
    for path in SRC.rglob("*.py"):
        found.extend((path, call) for call in _target_calls(path))

    assert found, f"No {TARGET} call sites found under {SRC}"

    missing = [
        f"{path.relative_to(ROOT)}:{getattr(call, 'lineno', '?')}"
        for path, call in found
        if not any(keyword.arg == "query" for keyword in call.keywords)
    ]
    assert missing == [], (
        f"Every {TARGET} call must pass query= so the displayed basis is tied to the quote item. "
        f"Missing at: {', '.join(missing)}"
    )
