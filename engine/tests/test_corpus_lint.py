"""Acceptance test for corpus linting (WP-5.4, WP-9.1)."""
from __future__ import annotations

from pathlib import Path
import sys

ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))

from tools.corpus_lint import lint_corpus


def test_corpus_lint_passes_with_zero_errors():
    exit_code = lint_corpus()
    assert exit_code == 0, "Corpus lint failed with errors"
