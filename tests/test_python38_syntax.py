# SPDX-License-Identifier: GPL-3.0-only

import ast
import pathlib
import unittest


class Python38SyntaxTests(unittest.TestCase):
    def test_repository_python_parses_as_python38(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        failures = []
        for path in sorted(root.rglob("*.py")):
            if any(part in {".git", ".venv", "venv", "build", "dist"} for part in path.parts):
                continue
            source = path.read_text(encoding="utf-8")
            try:
                ast.parse(source, filename=str(path), feature_version=(3, 8))
            except SyntaxError as exc:
                failures.append("{}:{}: {}".format(path.relative_to(root), exc.lineno, exc.msg))
        self.assertEqual(failures, [], "Python 3.8 syntax failures:\n" + "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
