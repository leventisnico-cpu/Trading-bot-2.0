"""§8 meta-checks: no vacuous assertions anywhere in the suite."""
from __future__ import annotations

import re
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

VACUOUS = [
    re.compile(r"\bassert\s+True\b"),
    re.compile(r"\bassert\b[^\n#]*\bor\s+True\b"),
    re.compile(r"\bassert\s+1\s*==\s*1\b"),
]


def test_no_vacuous_assertions():
    offenders = []
    scanned = 0
    for path in TESTS_DIR.glob("test_*.py"):
        text = path.read_text()
        scanned += 1
        for lineno, line in enumerate(text.splitlines(), 1):
            for pat in VACUOUS:
                if pat.search(line):
                    offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert scanned >= 4, "test files were not actually scanned"
    assert not offenders, "vacuous assertions found:\n" + "\n".join(offenders)
