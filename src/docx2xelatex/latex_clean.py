from __future__ import annotations

import re

REFUSAL_PATTERNS = [
    "i cannot",
    "i can't",
    "cannot determine",
    "sorry",
    "не могу",
    "невозможно распознать",
]

UNICODE_MATH_MAP = {
    "−": "-",
    "–": "-",
    "—": "-",
    "×": r"\times",
    "·": r"\cdot",
    "≤": r"\leq",
    "≥": r"\geq",
    "≠": r"\neq",
    "≈": r"\approx",
    "∞": r"\infty",
    "∈": r"\in",
    "∉": r"\notin",
    "⊂": r"\subset",
    "⊆": r"\subseteq",
    "∑": r"\sum",
    "∏": r"\prod",
    "∫": r"\int",
    "√": r"\sqrt",
    "α": r"\alpha",
    "β": r"\beta",
    "γ": r"\gamma",
    "δ": r"\delta",
    "ε": r"\varepsilon",
    "θ": r"\theta",
    "λ": r"\lambda",
    "μ": r"\mu",
    "π": r"\pi",
    "ρ": r"\rho",
    "σ": r"\sigma",
    "φ": r"\varphi",
    "ω": r"\omega",
    "Γ": r"\Gamma",
    "Δ": r"\Delta",
    "Θ": r"\Theta",
    "Λ": r"\Lambda",
    "Π": r"\Pi",
    "Σ": r"\Sigma",
    "Φ": r"\Phi",
    "Ω": r"\Omega",
}


def strip_markdown_fences(text: str) -> str:
    s = text.strip()
    m = re.search(r"```(?:latex|tex|math)?\s*(.*?)```", s, flags=re.S | re.I)
    if m:
        return m.group(1).strip()
    return s.replace("```", "").strip()


def strip_math_wrappers(text: str) -> str:
    s = text.strip()
    pairs = [(r"\\\[", r"\\\]"), (r"\\\(", r"\\\)"), (r"\$\$", r"\$\$"), (r"\$", r"\$")]
    changed = True
    while changed:
        changed = False
        for left, right in pairs:
            pattern = rf"^\s*{left}\s*(.*?)\s*{right}\s*$"
            m = re.match(pattern, s, flags=re.S)
            if m:
                s = m.group(1).strip()
                changed = True
    return s


def _remove_explanatory_lines(s: str) -> str:
    lines = [ln.strip() for ln in s.splitlines()]
    kept: list[str] = []
    for ln in lines:
        if not ln:
            continue
        ln = re.sub(r"^[-*#>]+\s*", "", ln).strip()
        if re.match(r"^(latex|tex|answer|formula|result|output)\s*[:：]", ln, flags=re.I):
            ln = re.sub(r"^[^:：]{1,40}[:：]\s*", "", ln).strip()
        lower = ln.lower()
        if any(p in lower for p in REFUSAL_PATTERNS):
            continue
        has_math = bool(re.search(r"[\\_^={}\[\]()+\-*/<>]|\d", ln))
        prose_words = re.findall(r"[A-Za-zА-Яа-яЁё]{3,}", ln)
        command_words = re.findall(r"\\[A-Za-z]+", ln)
        prose_score = max(0, len(prose_words) - len(command_words))
        if not has_math and prose_score >= 2:
            continue
        if prose_score >= 8 and len(ln) > 80 and "\\" not in ln:
            continue
        kept.append(ln)
    return "\n".join(kept).strip()


def _extract_delimited_math_from_prose(s: str) -> str:
    for pat in [r"\\\[(.*?)\\\]", r"\\\((.*?)\\\)", r"\$\$(.*?)\$\$", r"(?<!\\)\$(?!\$)(.*?)(?<!\\)\$"]:
        m = re.search(pat, s, flags=re.S)
        if not m:
            continue
        outside = (s[: m.start()] + " " + s[m.end() :]).strip()
        # Extract from explanatory prose, but do not silently drop OCR fragments
        # such as "\(s\)htarrow A" that contain math-like suffixes.
        if not outside or not re.search(r"[\\_^={}\[\]()+\-*/<>]|\d|(?:h?t?arrow)", outside):
            return m.group(1).strip()
    return s


def normalize_unicode_math(s: str) -> str:
    for src, dst in UNICODE_MATH_MAP.items():
        s = s.replace(src, dst)
    return s


def clean_latex_candidate(text: str) -> str:
    s = strip_markdown_fences(text or "")
    s = s.strip().strip("`").strip()
    s = _extract_delimited_math_from_prose(s)
    s = normalize_unicode_math(s)
    s = s.replace(r"\textless", "<").replace(r"\textgreater", ">")
    s = s.replace("&lt;", "<").replace("&gt;", ">")
    s = strip_math_wrappers(s)
    s = _remove_explanatory_lines(s)
    s = strip_math_wrappers(s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


def generate_repair_candidates(latex: str) -> list[str]:
    """Return conservative repaired variants without replacing the original OCR.

    Repairs are deliberately candidates, not mutations: selection still requires
    validation and rejection filters.
    """
    base = clean_latex_candidate(latex)
    variants: list[str] = []

    def add(value: str) -> None:
        value = clean_latex_candidate(value)
        if value and value != base and value not in variants:
            variants.append(value)

    # Whole-candidate wrappers are safe to unwrap; embedded wrappers are only
    # flattened as an alternate repair candidate.
    add(strip_math_wrappers(base))
    embedded = re.sub(r"\\[\(\[]\s*", "", base)
    embedded = re.sub(r"\s*\\[\)\]]", "", embedded)
    embedded = re.sub(r"(?<!\\)(?<![A-Za-z])htarrow", r"\\rightarrow", embedded)
    embedded = re.sub(r"(?<!\\)(?<![A-Za-z])rightarrow", r"\\rightarrow", embedded)
    embedded = re.sub(r"([A-Za-zА-Яа-я0-9\}\]])\^\{\}(?=\s*(?:[\\_\{\}\]\[=+\-*/]|$))", r"\1", embedded)
    add(embedded)

    repaired = normalize_unicode_math(base)
    replacements = [
        (r"(?<!\\)(?<![A-Za-z])rightarrow", r"\\rightarrow"),
        (r"(?<!\\)(?<![A-Za-z])htarrow", r"\\rightarrow"),
        (r"(?<!\\)(?<![A-Za-z])leftarrow", r"\\leftarrow"),
        (r"(?<!\\)(?<![A-Za-z])Rightarrow", r"\\Rightarrow"),
    ]
    for pat, repl in replacements:
        repaired = re.sub(pat, repl, repaired)
    # Common OCR fragment: closing inline wrapper immediately before h/rightarrow.
    repaired = repaired.replace(r"\)htarrow", r" \rightarrow")
    repaired = repaired.replace(r"\)rightarrow", r" \rightarrow")
    repaired = re.sub(r"([A-Za-zА-Яа-я0-9\}\]])\^\{\}(?=\s*(?:[\\_\{\}\]\[=+\-*/]|$))", r"\1", repaired)
    add(repaired)

    repaired2 = re.sub(r"\\[\(\[]\s*", "", repaired)
    repaired2 = re.sub(r"\s*\\[\)\]]", "", repaired2)
    add(repaired2)
    return variants


def contains_embedded_math_wrappers(s: str) -> bool:
    return bool(re.search(r"\\[\(\)\[\]]|\$\$|(?<!\\)\$(?!\$)", s or ""))


def braces_balanced(s: str) -> bool:
    stack: list[str] = []
    pairs = {"}": "{", "]": "[", ")": "("}
    escaped = False
    for ch in s:
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch in "{[(":
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack[-1] != pairs[ch]:
                return False
            stack.pop()
    return not stack


def looks_like_refusal(s: str) -> bool:
    lower = (s or "").lower()
    return any(p in lower for p in REFUSAL_PATTERNS)
