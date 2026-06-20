from docx2xelatex.latex_clean import braces_balanced, clean_latex_candidate


def test_clean_removes_fences_and_wrappers():
    raw = """```latex
\\[ a_i = \\frac{1}{2} \\]
```"""
    assert clean_latex_candidate(raw) == r"a_i = \frac{1}{2}"


def test_clean_removes_explanation_and_unicode_minus():
    raw = "Here is the formula: $x − y < z$"
    assert clean_latex_candidate(raw) == "x - y < z"


def test_braces_balanced():
    assert braces_balanced(r"\frac{a}{b}")
    assert not braces_balanced(r"\frac{a}{b")
