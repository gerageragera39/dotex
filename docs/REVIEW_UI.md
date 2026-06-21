# Formula Review UI guide

The review UI is the human-in-the-loop part of `docx2xelatex`. Use it after OCR/validation/selection, or immediately after `docx2xelatex full`.

Start it locally:

```powershell
docx2xelatex review --workdir $Build --config $Config --host 127.0.0.1 --port 8765
```

Open:

```text
http://127.0.0.1:8765/formulas.html
```

The server binds to `127.0.0.1` by default, so document images and formulas stay local.

---

## Recommended workflow

For each suspicious formula:

1. Compare **Original formula image** with the selected rendered preview.
2. Check all OCR candidates.
3. If no candidate is good, edit the LaTeX textarea.
4. Click **Compile/recompile** to create a manual validated candidate and preview.
5. Click **Select textarea** or **Select candidate**.
6. Choose **Set inline** or **Set display** if the formula is wrapped incorrectly.
7. After all fixes, click **Merge final.md**, **Build**, and **Audit**.

Equivalent CLI tail:

```powershell
docx2xelatex merge --workdir $Build --config $Config --strict
docx2xelatex build --workdir $Build --config $Config --force
docx2xelatex audit --workdir $Build --config $Config
```

---

## Top toolbar

| Control | What it does | When to use it |
| --- | --- | --- |
| Search box | Searches formula id, selected LaTeX, candidates and errors. | Find `f0007`, a symbol, or a suspicious OCR fragment. |
| Filter: all | Shows all formulas. | Normal browsing. |
| Filter: invalid | Shows formulas whose current status is not valid. | Find formulas needing attention. |
| Filter: no selected latex | Shows formulas that will become PNG TODO fallbacks. | Decide whether to leave TODOs or fix manually. |
| Filter: low visual score | Shows selected formulas whose preview does not visually match well. | Catch valid-but-wrong OCR. |
| Filter: manual | Shows formulas selected from manual edits. | Review your hand corrections. |
| Refresh | Reloads `manifest.json` from disk. | Use after external CLI changes. |
| Merge final.md | Runs merge: selected LaTeX replaces formula images; unresolved formulas become PNG TODO fallbacks. | After selecting/fixing formulas. |
| Build | Runs the final build step. | After merge, to regenerate final TeX/PDF. |
| Audit | Reports unresolved formulas, stale artifacts, missing previews, invalid selected formulas and final build status. | Final quality check. |

---

## Formula card sections

### Original formula image

This is the PNG rendered from the DOCX formula image. It is the ground truth you compare against.

Buttons:

| Button | Meaning |
| --- | --- |
| Fit panel | Scales the image to fit the card. Good for normal formulas. |
| Actual size | Shows the PNG at original pixel size. Use this when a long formula looks too small. The panel becomes scrollable. |
| Open image | Opens the source PNG in a new browser tab for full-size inspection. |
| Set inline | Use inline math wrappers in final Markdown: `\( latex \)`. |
| Set display | Use display math wrappers in final Markdown: `\[ latex \]`. |

### Selected LaTeX / manual edit

This panel shows the currently selected LaTeX. Edit it when OCR is wrong.

Buttons:

| Button | Meaning |
| --- | --- |
| Compile/recompile | Compiles the textarea as a new manual candidate, stores validation status, log and rendered preview. It does not necessarily select it unless you select it. |
| Select textarea | Compiles the textarea and selects it as the current manual candidate for final output. |

Keyboard shortcut: **Ctrl+Enter** in the textarea runs compile/recompile.

### All candidates

Each candidate has:

- OCR/manual source (`texteller`, `pix2tex`, `ollama_qwen`, `manual`, repair variants, etc.);
- validation status;
- visual score if available;
- candidate LaTeX;
- rendered preview PNG when validation succeeded;
- validation error if it failed.

Button:

| Button | Meaning |
| --- | --- |
| Select candidate | Makes this candidate the formula used by merge/build. |

### Status / errors

Shows formula-level validation errors and selection rejection reasons. If a formula is unresolved, merge keeps the original formula PNG as a TODO fallback instead of leaving WMF/EMF in the final document.

---

## Inline vs display: what it means

This setting controls how the formula is inserted into Markdown and how it is validated.

### Inline

Inline formulas stay inside a paragraph:

```tex
Текст до \( a+b \) текст после.
```

Use **inline** for small formulas that are part of a sentence, for example `x`, `a_i`, `s \in S`, short inequalities, or small fractions that do not need their own line.

### Display

Display formulas become standalone equation blocks:

```tex
\[
a+b=c
\]
```

Use **display** for formulas that were visually on their own line in the DOCX, tall fractions, sums/integrals, matrices, multi-line equations, or formulas that should be centered/separated from text.

### Why this matters

Wrong inline/display can make the final document look bad or compile differently:

- a tall formula marked inline can stretch a text line;
- a sentence formula marked display can break paragraph flow;
- validation is more realistic when it uses the same wrapper as final merge.

The manifest stores:

```text
display_type_auto     # guessed by the pipeline
display_type_manual   # your override from UI
display_type          # effective value: manual if set, otherwise auto
```

---

## What is safe to leave unresolved?

If OCR cannot recover a formula confidently, it is okay to leave it unresolved. Merge will insert a PNG fallback and a marker like:

```text
TODO_FORMULA_f0001
```

This keeps the final document buildable while making the unresolved formula easy to find later.

---

## Common review decisions

| Situation | Recommended action |
| --- | --- |
| Candidate compiles and visually matches original | Select it. |
| Candidate compiles but visual preview is clearly wrong | Do not select; try another candidate or manual edit. |
| OCR contains prose or wrapper fragments like `\)htarrow` | Leave rejected; use a repair/manual candidate if it validates. |
| Original image is too small in UI | Click **Actual size** or **Open image**. |
| Formula is in a sentence | Click **Set inline**. |
| Formula is standalone or tall | Click **Set display**. |
| Nothing is recoverable | Leave as unresolved PNG TODO fallback. |

---

## After review

Run:

```powershell
docx2xelatex merge --workdir $Build --config $Config --strict
docx2xelatex build --workdir $Build --config $Config --force
docx2xelatex audit --workdir $Build --config $Config
```

Open:

```powershell
Start-Process "$Build\final.pdf"
```
