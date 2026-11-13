"""Every module, class and function in src/ has a docstring, private ones included.

ruff's D rules (run on every edit by the hook) only cover public names; this test covers the rest.
"""

import ast

from tests.conftest import REPO

SRC = REPO / "src" / "yellow"
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def test_everything_in_src_has_a_docstring() -> None:
    missing: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.relative_to(REPO)
        if not ast.get_docstring(tree):
            missing.append(f"{rel}:1 (module)")
        missing += [
            f"{rel}:{node.lineno} {node.name}"
            for node in ast.walk(tree)
            if isinstance(node, _DEFS) and not ast.get_docstring(node)
        ]
    assert not missing, "missing docstrings:\n" + "\n".join(missing)
