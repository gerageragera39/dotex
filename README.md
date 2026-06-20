# dotex — DOCX → XeLaTeX for old mathematical papers

<p align="center">
  <b>Local-first pipeline for converting legacy mathematical DOCX papers with WMF/OLE formulas into clean Markdown, LaTeX formulas and XeLaTeX/PDF.</b>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11%2B-blue">
  <img alt="Local first" src="https://img.shields.io/badge/local--first-privacy-green">
  <img alt="XeLaTeX" src="https://img.shields.io/badge/output-XeLaTeX-orange">
  <img alt="Ollama" src="https://img.shields.io/badge/Ollama-qwen3--vl%3A8b-black">
</p>

---

## What is this?

`dotex` / `docx2xelatex` is a local, controllable conversion pipeline for old scientific DOCX documents, especially mathematical papers where formulas are stored as legacy **WMF/OLE MathType / Equation Editor objects**.

The goal is not just “convert DOCX to PDF”. The goal is to recover a real, editable, modern XeLaTeX document:

```text
old DOCX → clean Markdown → recognized LaTeX formulas → final.md → final.tex → final.pdf
```

The project is designed for documents like old Russian-language mathematical papers, where the text is still readable by Pandoc, but formulas are embedded as images such as:

```markdown
![](media/image4.wmf)
```

Instead of trusting one magic converter, `dotex` treats every formula as a separate recoverable object.

---

## Why I created this

I had several old mathematical scientific papers written in DOCX. They contain a lot of formulas, but most of them are not modern Word OMML equations. They are old embedded objects with WMF previews.

I tried different tools and workflows:

* Pandoc
* MarkItDown
* MinerU
* Nougat
* PDF-based extraction
* DOCX → PDF → OCR approaches
* direct DOCX → LaTeX converters

They all helped in some places, but none of them gave a clean, reliable XeLaTeX result for this exact case.

Typical problems were:

* formulas became images instead of LaTeX;
* old WMF/OLE formulas were not recovered;
* generated `.tex` was too dirty to maintain;
* XeLaTeX compilation failed on broken formulas;
* formatting, italics and structure were partially lost;
* one bad formula could break the whole document.

So I built this project around a different idea:

> Use Pandoc for what it is good at — text and document structure.
> Use local vision/OCR models for what they are good at — formula recognition.
> Validate every formula independently.
> Never let one broken formula destroy the whole paper.

---

## Core idea

Each formula goes through its own lifecycle:

```text
image → png → candidates → validation → selection → merge
```

If a formula cannot be recognized or compiled, the final document is still generated. The original formula image stays in the Markdown and receives a `TODO_FORMULA_f0001` marker, so it can be fixed manually later.

This makes the pipeline practical for real archival work.

---

## How it works

```mermaid
flowchart TD
    A[DOCX] --> B[Pandoc]
    B --> C[text.md + media/]
    C --> D[Formula manifest]
    D --> E[WMF/EMF → PNG]
    E --> F[Local OCR via Ollama qwen3-vl:8b]
    F --> G[LaTeX candidates]
    H[Optional docx2tex .tex] --> G
    G --> I[Per-formula XeLaTeX validation]
    I --> J[Best candidate selection]
    J --> K[HTML review report]
    J --> L[final.md]
    L --> M[Pandoc]
    M --> N[clean final.tex]
    N --> O[XeLaTeX final.pdf]
```

### What each tool does

| Component                | Role                                                                                      |
| ------------------------ | ----------------------------------------------------------------------------------------- |
| **Pandoc**               | Extracts text, paragraphs, lists, italics, bold text and media from DOCX                  |
| **ImageMagick**          | Converts WMF/EMF formula previews into PNG                                                |
| **Ollama + qwen3-vl:8b** | Recognizes formula images locally                                                         |
| **XeLaTeX**              | Validates every candidate formula and builds final PDF                                    |
| **docx2tex**             | Optional: used only as an additional formula candidate source, not as final TeX generator |

---

## Why not use final `.tex` from docx2tex?

`docx2tex` can sometimes extract useful math from old OLE/MathType formulas, but its full generated `.tex` can be unstable and hard to maintain.

In this project, `docx2tex` is treated as an optional formula source only:

```text
docx2tex output → extract formula candidates → validate → maybe use
```

The final document is rebuilt cleanly:

```text
Pandoc Markdown → final.md → clean final.tex → XeLaTeX
```

---

## Privacy model

`dotex` is designed for confidential documents.

* Your DOCX files are processed locally.
* Formula images are processed locally.
* OCR uses local Ollama at `http://localhost:11434`.
* The project intentionally rejects non-localhost Ollama URLs.
* No document text, formulas or images are sent to external APIs.

Internet access is only needed when you install dependencies yourself.

---

## Requirements

Install these tools locally:

| Tool               | Purpose                              |
| ------------------ | ------------------------------------ |
| Python 3.11+       | Main project runtime                 |
| Pandoc             | DOCX → Markdown and Markdown → LaTeX |
| MiKTeX or TeX Live | XeLaTeX compilation                  |
| ImageMagick        | WMF/EMF → PNG                        |
| Ollama             | Local vision model runtime           |
| `qwen3-vl:8b`      | Local formula OCR model              |

Install the model:

```powershell
ollama pull qwen3-vl:8b
```

Check that Ollama is running:

```powershell
ollama list
```

---

## Installation

Clone the repository:

```powershell
git clone https://github.com/gerageragera39/dotex.git
cd dotex
```

Create a virtual environment:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the project:

```powershell
pip install -e .
```

Check your environment:

```powershell
docx2xelatex doctor
```

Expected checks:

* Python
* Pandoc
* ImageMagick `magick`
* XeLaTeX
* Ollama
* `qwen3-vl:8b`

---

## Quickstart

Create config:

```powershell
docx2xelatex init-config --out config.yaml
```

Run the full pipeline:

```powershell
docx2xelatex full `
  --input "C:\path\to\work.docx" `
  --workdir "C:\path\to\build" `
  --config config.yaml
```

Your output will be in:

```text
build/
  text.md
  formulas/
  report/formulas.html
  final.md
  final.tex
  final.pdf
```

---

## Recommended controlled workflow

For real documents, step-by-step mode is better than `full`, because you can inspect formulas before building the final TeX.

Set paths:

```powershell
$Docx = "C:\path\to\work.docx"
$Build = "C:\path\to\build"
$Config = "C:\path\to\config.yaml"
```

Inspect DOCX internals:

```powershell
docx2xelatex inspect-docx --input $Docx --workdir $Build
```

This counts:

* `word/media/*.wmf`
* `word/media/*.emf`
* `word/embeddings/oleObject*.bin`
* OMML equations such as `<m:oMath>`

Create Markdown with formula images:

```powershell
docx2xelatex pandoc-md --input $Docx --workdir $Build --config $Config
```

Create formula manifest:

```powershell
docx2xelatex manifest `
  --markdown "$Build\text.md" `
  --workdir $Build `
  --config $Config
```

Render formula images:

```powershell
docx2xelatex render-images --workdir $Build --config $Config
```

Run local OCR:

```powershell
docx2xelatex ocr --workdir $Build --config $Config --verbose
```

Validate all candidates:

```powershell
docx2xelatex validate --workdir $Build --config $Config
```

Select best formulas:

```powershell
docx2xelatex select --workdir $Build --config $Config
```

Generate review report:

```powershell
docx2xelatex report --workdir $Build --config $Config
Start-Process "$Build\report\formulas.html"
```

After reviewing formulas, merge and build:

```powershell
docx2xelatex merge --workdir $Build --config $Config
docx2xelatex build --workdir $Build --config $Config
```

---

## Formula review report

The HTML report is one of the most important parts of the project.

It shows:

* formula id;
* original image;
* selected LaTeX;
* candidate source;
* validation status;
* validation errors;
* links to validation logs.

Open it after OCR and validation:

```powershell
Start-Process "$Build\report\formulas.html"
```

A good workflow is:

1. Open the report.
2. Check red rows.
3. Fix bad formulas manually in `manifest.json`.
4. Re-run only the final stages.

---

## Manual formula correction

If OCR fails or produces a wrong formula, edit:

```text
build/formulas/manifest.json
```

Find the formula:

```json
{
  "id": "f0001",
  "selected_latex": null,
  "selected_source": null
}
```

Set:

```json
{
  "selected_latex": "\\frac{a}{b}",
  "selected_source": "manual"
}
```

Then rebuild only the tail:

```powershell
docx2xelatex merge --workdir $Build --config $Config
docx2xelatex build --workdir $Build --config $Config
```

---

## Optional: use docx2tex as a formula source

If you already generated a `.tex` file with `docx2tex`, you can add it as an additional source of formula candidates:

```powershell
docx2xelatex add-docx2tex-candidates `
  --workdir $Build `
  --docx2tex-tex "C:\path\to\docx2tex\out\work.tex" `
  --config $Config
```

Then rerun:

```powershell
docx2xelatex validate --workdir $Build --config $Config
docx2xelatex select --workdir $Build --config $Config
docx2xelatex report --workdir $Build --config $Config
```

Candidate priority can be controlled in `config.yaml`:

```yaml
candidate_selection:
  priority: ["ollama_qwen", "docx2tex"]
```

or:

```yaml
candidate_selection:
  priority: ["docx2tex", "ollama_qwen"]
```

For my documents, `docx2tex` is usually more useful as a fallback candidate source than as the main converter.

---

## Project artifacts

Typical workdir structure:

```text
build/
  text.md                         # Markdown generated by Pandoc
  media/                          # extracted DOCX images
  formulas/
    manifest.json                 # lifecycle state of every formula
    png/
      f0001.png                   # rendered formula image
    ocr/
      f0001_ollama_qwen.json      # raw OCR status/result
    validate/
      f0001/
        candidate_*.tex           # minimal validation files
        candidate_*.log           # XeLaTeX logs
        candidate_*.pdf           # rendered candidate if valid
  report/
    formulas.html                 # visual formula review report
  final.md                        # Markdown with LaTeX formulas or TODOs
  final.tex                       # clean Pandoc-generated XeLaTeX
  final.pdf                       # final PDF if build succeeds
  final.log                       # final XeLaTeX log
```

---

## Configuration

Create default config:

```powershell
docx2xelatex init-config --out config.yaml
```

Important options:

```yaml
ollama:
  base_url: "http://localhost:11434"
  model: "qwen3-vl:8b"
  timeout_seconds: 600
  resize_image: false
  max_image_side: 2400
  num_predict: null

candidate_selection:
  priority: ["ollama_qwen", "docx2tex"]

latex:
  engine: xelatex
  mainfont: "Times New Roman"
  sansfont: "Arial"
  monofont: "Courier New"
  build_pdf: true
```

If OCR is too slow, try:

```yaml
ollama:
  resize_image: true
  max_image_side: 2400
```

If recognition quality drops, switch back to:

```yaml
ollama:
  resize_image: false
```

---

## CLI commands

| Command                   | Description                                                       |
| ------------------------- | ----------------------------------------------------------------- |
| `doctor`                  | Check local dependencies                                          |
| `init-config`             | Create YAML config                                                |
| `inspect-docx`            | Count DOCX formula/media internals without printing document text |
| `pandoc-md`               | Convert DOCX to Markdown and extract media                        |
| `manifest`                | Find formula images and create manifest                           |
| `render-images`           | Convert WMF/EMF formulas to PNG                                   |
| `ocr`                     | Run local formula OCR via Ollama/qwen3-vl                         |
| `add-docx2tex-candidates` | Add candidates from docx2tex-generated `.tex`                     |
| `validate`                | Compile every candidate formula separately                        |
| `select`                  | Select the best valid candidate                                   |
| `report`                  | Generate HTML formula review report                               |
| `merge`                   | Replace image formulas with LaTeX in Markdown                     |
| `build`                   | Generate clean final TeX/PDF                                      |
| `full`                    | Run the main pipeline                                             |

Useful OCR options:

```powershell
docx2xelatex ocr --workdir $Build --config $Config --verbose
docx2xelatex ocr --workdir $Build --config $Config --timeout-seconds 1200
```

---

## Troubleshooting

### `magick` not found

Install ImageMagick and restart PowerShell:

```powershell
magick -version
docx2xelatex doctor
```

### `xelatex` not found

Install MiKTeX or TeX Live:

```powershell
xelatex --version
```

### Ollama unavailable

Check Ollama:

```powershell
ollama list
```

The project only supports local Ollama URLs such as:

```text
http://localhost:11434
```

### Model not found

Install the model:

```powershell
ollama pull qwen3-vl:8b
```

### OCR is slow

Vision models can be slow on large formula images. Use verbose mode:

```powershell
docx2xelatex ocr --workdir $Build --config $Config --verbose
```

Check current OCR status:

```powershell
Get-Content "$Build\formulas\ocr\f0001_ollama_qwen.json"
```

### A formula fails validation

Open the validation files:

```text
build/formulas/validate/f0001/
```

Then either:

* fix the candidate manually in `manifest.json`;
* add a better candidate;
* leave the original image with `TODO_FORMULA_f0001`.

### Final PDF fails but `final.tex` exists

This is recoverable. Open:

```text
build/final.tex
build/final.log
```

The project keeps intermediate files so the result can be debugged.

---

## Development

Install dev dependencies:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
```

Run tests:

```powershell
pytest
```

---

## Roadmap

Planned improvements:

* additional OCR engines such as `pix2tex` or `TexTeller`;
* better formula candidate ranking;
* side-by-side formula rendering comparison;
* batch processing for multiple papers;
* improved table handling;
* better support for numbered equations;
* optional manual review UI.

---

## Philosophy

This project is built around one practical principle:

> A document conversion pipeline should be inspectable, resumable and recoverable.

Old scientific documents are messy. Formula extraction will not be perfect. But a good pipeline should make every failure visible, local and fixable — instead of producing one giant broken `.tex` file.
