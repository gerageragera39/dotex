from docx2xelatex.config import DEFAULT_CONFIG
from docx2xelatex.engines.ollama_qwen import OllamaQwenEngine, _has_usable_candidate


def test_default_ollama_quality_first_options():
    engine = OllamaQwenEngine(DEFAULT_CONFIG)
    assert engine.num_predict is None
    assert DEFAULT_CONFIG["ollama"]["resize_image"] is False


def test_empty_or_error_candidate_is_not_usable():
    formula = {
        "candidates": [
            {"source": "ollama_qwen", "latex": "", "validation_status": "error"},
            {"source": "docx2tex", "latex": "x"},
        ]
    }
    assert not _has_usable_candidate(formula, "ollama_qwen")


def test_nonempty_candidate_is_usable():
    formula = {"candidates": [{"source": "ollama_qwen", "latex": r"x^2"}]}
    assert _has_usable_candidate(formula, "ollama_qwen")
