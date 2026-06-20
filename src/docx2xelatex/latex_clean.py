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
        if m:
            return m.group(1).strip()
    return s


def clean_latex_candidate(text: str) -> str:
    s = strip_markdown_fences(text or "")
    s = s.strip().strip("`").strip()
    s = _extract_delimited_math_from_prose(s)
    s = s.replace("\u2212", "-").replace("−", "-").replace("–", "-")
    s = s.replace(r"\textless", "<").replace(r"\textgreater", ">")
    s = s.replace("&lt;", "<").replace("&gt;", ">")
    s = strip_math_wrappers(s)
    s = _remove_explanatory_lines(s)
    s = strip_math_wrappers(s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


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
