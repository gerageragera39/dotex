from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .audit import audit_workdir
from .build_latex import build as build_stage
from .config import load_config
from .latex_validate import validate_formula_candidate
from .manifest import formula_display_type, load_manifest, save_manifest, set_display_type_manual
from .merge_markdown import merge_markdown
from .paths import WorkPaths
from .select_candidate import compile_manual_candidate, select_candidate
from .utils import write_json_atomic


def _formula_by_id(manifest: dict[str, Any], formula_id: str) -> dict[str, Any]:
    for f in manifest.get("formulas", []):
        if str(f.get("id")) == formula_id:
            return f
    raise KeyError(formula_id)


def _rel_asset(path: str | None, wp: WorkPaths) -> str | None:
    if not path:
        return None
    try:
        rel = Path(path).resolve().relative_to(wp.root.resolve()).as_posix()
    except Exception:
        return None
    return "/assets/" + rel


def _public_formula(formula: dict[str, Any], wp: WorkPaths) -> dict[str, Any]:
    data = dict(formula)
    data["png_url"] = _rel_asset(formula.get("png_path"), wp)
    for c in data.get("candidates", []):
        artifacts = c.get("artifacts") or {}
        c["preview_url"] = _rel_asset(artifacts.get("preview_png"), wp)
    return data


FORMULAS_HTML = r'''<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>docx2xelatex formula review</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f7fb;
      --panel: #ffffff;
      --ink: #172033;
      --muted: #64748b;
      --line: #d8e0ee;
      --blue: #2563eb;
      --blue-dark: #1d4ed8;
      --green: #059669;
      --amber: #b45309;
      --red: #b91c1c;
      --shadow: 0 10px 28px rgba(15, 23, 42, .10);
      font-family: Inter, "Segoe UI", Arial, sans-serif;
      background: var(--bg);
      color: var(--ink);
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); }
    .top {
      position: sticky; top: 0; z-index: 20;
      background: linear-gradient(135deg, #0f172a, #1e293b);
      color: white; padding: 12px 18px; box-shadow: 0 4px 18px rgba(0,0,0,.24);
    }
    .top-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    .brand { font-weight: 800; letter-spacing: .2px; margin-right: 12px; }
    .top input, .top select, .top button {
      padding: 8px 10px; border-radius: 10px; border: 1px solid rgba(255,255,255,.28);
      background: rgba(255,255,255,.10); color: white;
    }
    .top input::placeholder { color: rgba(255,255,255,.68); }
    .top option { color: #111827; }
    .top button { background: rgba(37, 99, 235, .92); border: 0; }
    .top button.secondary { background: rgba(100, 116, 139, .9); }
    .top button.ok { background: rgba(5, 150, 105, .95); }
    .status { margin-left: auto; font-size: 13px; color: #dbeafe; }
    .wrap { padding: 18px; max-width: 1900px; margin: 0 auto; }
    details.guide {
      background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 16px;
      margin: 0 0 18px; padding: 12px 14px; box-shadow: var(--shadow);
    }
    details.guide summary { cursor: pointer; font-weight: 800; color: #1e3a8a; }
    .guide-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; margin-top: 10px; }
    .guide-card { background: white; border: 1px solid #dbeafe; border-radius: 12px; padding: 10px 12px; }
    .guide-card h4 { margin: 0 0 6px; }
    .guide-card ul { margin: 6px 0 0 18px; padding: 0; }
    .card {
      background: var(--panel); border: 1px solid var(--line); border-radius: 18px;
      margin: 18px 0; padding: 16px; box-shadow: var(--shadow);
    }
    .card-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 12px; }
    .card h3 { margin: 0 10px 0 0; font-size: 22px; }
    .grid {
      display: grid;
      grid-template-columns: minmax(360px, 520px) minmax(280px, .9fr) minmax(340px, 1.1fr) minmax(260px, .8fr);
      gap: 16px; align-items: start;
    }
    @media (max-width: 1250px) { .grid { grid-template-columns: 1fr 1fr; } }
    @media (max-width: 820px) { .grid { grid-template-columns: 1fr; } .status { margin-left: 0; width: 100%; } }
    .panel { border: 1px solid #e2e8f0; border-radius: 14px; padding: 12px; background: #fbfdff; }
    .panel h4 { margin: 0 0 8px; font-size: 15px; }
    .help { color: var(--muted); font-size: 12px; line-height: 1.35; margin: 6px 0 10px; }
    .image-stage {
      min-height: 220px; max-height: 430px; overflow: auto; background: white;
      border: 1px dashed #cbd5e1; border-radius: 12px; padding: 12px;
      display: flex; align-items: center; justify-content: center;
    }
    .image-stage.actual { justify-content: flex-start; align-items: flex-start; }
    .formula-img {
      display: block; background: white; border: 1px solid #e5e7eb; border-radius: 8px;
      max-width: min(100%, 760px); max-height: 360px; min-width: 260px; object-fit: contain;
    }
    .image-stage.actual .formula-img { max-width: none; max-height: none; min-width: 320px; }
    .preview {
      max-width: 100%; max-height: 180px; min-width: 120px; background: white;
      border: 1px solid #e5e7eb; border-radius: 8px; padding: 4px;
    }
    textarea {
      width: 100%; min-height: 130px; resize: vertical;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      border: 1px solid #cbd5e1; border-radius: 10px; padding: 10px; background: white;
    }
    button {
      cursor: pointer; background: var(--blue); color: white; border: 0; border-radius: 10px;
      padding: 8px 11px; margin: 3px 4px 3px 0; font-weight: 650;
    }
    button:hover { background: var(--blue-dark); }
    button.secondary { background: #64748b; }
    button.secondary:hover { background: #475569; }
    button.ok { background: var(--green); }
    button.warn { background: var(--amber); }
    button.ghost { background: #e2e8f0; color: #172033; }
    a.button { display: inline-block; text-decoration: none; background: #e2e8f0; color: #172033; border-radius: 10px; padding: 8px 11px; margin: 3px 4px 3px 0; font-weight: 650; }
    .pill { display: inline-block; padding: 3px 8px; border-radius: 999px; background: #e5e7eb; margin: 2px; font-size: 12px; }
    .valid { background: #dcfce7; color: #14532d; }
    .invalid, .error { background: #fee2e2; color: #7f1d1d; }
    .pending { background: #fef3c7; color: #78350f; }
    .manual { background: #e0e7ff; color: #312e81; }
    .selected-pill { background: #dbeafe; color: #1e3a8a; }
    .cand { border-top: 1px solid #edf0f7; margin-top: 10px; padding-top: 10px; }
    .cand.selected { outline: 2px solid #60a5fa; border-radius: 12px; padding: 10px; background: #eff6ff; }
    .small { color: var(--muted); font-size: 12px; }
    pre { white-space: pre-wrap; max-height: 160px; overflow: auto; background: #f8fafc; padding: 9px; border-radius: 10px; border: 1px solid #e2e8f0; }
    .empty { color: var(--muted); font-style: italic; padding: 10px; }
  </style>
</head>
<body>
  <div class="top">
    <div class="top-row">
      <span class="brand">docx2xelatex formula review</span>
      <input id="q" placeholder="Search id or LaTeX" oninput="render()" title="Search formula id, selected LaTeX, OCR candidate text or errors">
      <select id="filter" onchange="render()" title="Filter formulas">
        <option>all</option>
        <option>invalid</option>
        <option>no selected latex</option>
        <option>low visual score</option>
        <option>manual</option>
      </select>
      <button class="secondary" onclick="load()" title="Reload manifest from disk">Refresh</button>
      <button onclick="api('/api/merge',{}).then(load)" title="Regenerate final.md from selected formulas and TODO fallbacks">Merge final.md</button>
      <button class="ok" onclick="api('/api/build',{}).then(load)" title="Run final Markdown/TeX/PDF build">Build</button>
      <button class="secondary" onclick="api('/api/audit',{}).then(showAudit)" title="Check unresolved formulas, stale artifacts and final build status">Audit</button>
      <span id="status" class="status"></span>
    </div>
  </div>

  <div class="wrap">
    <details class="guide" open>
      <summary>How to use this page / Что означают кнопки</summary>
      <div class="guide-grid">
        <div class="guide-card">
          <h4>Recommended workflow</h4>
          <ul>
            <li>Look at the large <b>Original formula image</b>.</li>
            <li>Compare it with <b>Selected rendered preview</b> and OCR candidates.</li>
            <li>If wrong, edit the textarea, click <b>Compile/recompile</b>, then <b>Select textarea</b>.</li>
            <li>When done, click <b>Merge final.md</b>, <b>Build</b>, then <b>Audit</b>.</li>
          </ul>
        </div>
        <div class="guide-card">
          <h4>Inline vs display</h4>
          <p><b>Inline</b> means the formula stays inside a sentence: <code>text \(a+b\) text</code>.</p>
          <p><b>Display</b> means a separate centered equation block: <code>\[a+b\]</code>.</p>
          <p>Use <b>inline</b> for small formulas in running text. Use <b>display</b> for standalone equations, tall fractions, sums, matrices or numbered-looking equations.</p>
        </div>
        <div class="guide-card">
          <h4>Formula buttons</h4>
          <ul>
            <li><b>inline/display</b>: changes the wrapper used in final Markdown and validation.</li>
            <li><b>Compile/recompile</b>: validates the textarea LaTeX and creates a manual candidate preview.</li>
            <li><b>Select textarea</b>: compiles and selects the textarea as the chosen manual formula.</li>
            <li><b>Select</b> on a candidate: chooses that OCR/manual candidate.</li>
          </ul>
        </div>
        <div class="guide-card">
          <h4>Top buttons</h4>
          <ul>
            <li><b>Refresh</b>: reloads current manifest.</li>
            <li><b>Merge final.md</b>: replaces formula images with selected LaTeX or PNG TODO fallbacks.</li>
            <li><b>Build</b>: generates/compiles final TeX/PDF.</li>
            <li><b>Audit</b>: checks unresolved formulas, stale artifacts, previews and final build status.</li>
          </ul>
        </div>
      </div>
    </details>
    <div id="list"></div>
  </div>

<script>
let formulas = [];
let imageMode = {};

async function load() {
  let r = await fetch('/api/formulas');
  formulas = await r.json();
  document.getElementById('status').textContent = `loaded ${formulas.length} formulas`;
  render();
}

async function api(url, body) {
  document.getElementById('status').textContent = 'running...';
  let r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body||{})});
  let j = await r.json();
  document.getElementById('status').textContent = j.status || j.validation_status || (r.ok ? 'ok' : 'failed');
  if(!r.ok) console.error(j);
  return j;
}

function showAudit(j) {
  const lines = [
    `audit: ${j.status || 'unknown'}`,
    `total formulas: ${j.total_formulas ?? ''}`,
    `unresolved TODO: ${j.unresolved_todo_formulas ?? ''}`,
    `stale artifacts: ${(j.candidates_with_stale_artifacts || []).length}`,
    `missing previews: ${(j.selected_candidates_without_preview || []).length}`,
    `final tex: ${(j.final_tex_compile_result || {}).status || 'unknown'}`
  ];
  document.getElementById('status').textContent = lines.join(' | ');
}

function matches(f) {
  let q = document.getElementById('q').value.toLowerCase();
  let fl = document.getElementById('filter').value;
  let text = (f.id+' '+(f.selected_latex||'')+' '+JSON.stringify(f.candidates||[])).toLowerCase();
  if(q && !text.includes(q)) return false;
  if(fl === 'invalid' && f.validation_status === 'valid') return false;
  if(fl === 'no selected latex' && f.selected_latex) return false;
  if(fl === 'manual' && f.selected_source !== 'manual') return false;
  if(fl === 'low visual score') {
    let c = (f.candidates||[]).find(c => c.candidate_key === f.selected_candidate_key) || {};
    if((c.visual_score || 1) >= 0.70) return false;
  }
  return true;
}

function esc(s) {
  return (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function setImageMode(id, mode) { imageMode[id] = mode; render(); }

function candidateHtml(f, c) {
  const selected = c.candidate_key && c.candidate_key === f.selected_candidate_key;
  const cls = selected ? 'cand selected' : 'cand';
  const preview = c.preview_url ? `<p><img class="preview" src="${c.preview_url}" alt="rendered preview for ${esc(c.candidate_key || '')}"></p>` : '<p class="small">no rendered preview</p>';
  const error = c.validation_error ? `<details><summary class="small">validation error</summary><pre>${esc(c.validation_error)}</pre></details>` : '';
  return `<div class="${cls}">
    <span class="pill ${esc(c.validation_status || 'pending')}">${esc(c.validation_status || 'pending')}</span>
    <span class="pill">${esc(c.source || 'unknown')}/${esc(c.variant || 'original')}</span>
    ${selected ? '<span class="pill selected-pill">currently selected</span>' : ''}
    ${c.source === 'manual' ? '<span class="pill manual">manual</span>' : ''}
    <span class="small">visual score: ${c.visual_score ?? 'not scored'}</span>
    <pre>${esc(c.latex || '')}</pre>
    ${preview}
    <button class="ok" onclick="selectKey('${f.id}','${esc(c.candidate_key || '')}')" title="Choose this candidate as the formula used in final.md">Select candidate</button>
    ${error}
  </div>`;
}

function render() {
  let el = document.getElementById('list');
  el.innerHTML = '';
  const visible = formulas.filter(matches);
  if (!visible.length) {
    el.innerHTML = '<div class="card empty">No formulas match the current filter.</div>';
    return;
  }
  visible.forEach(f => {
    let selected = (f.candidates || []).find(c => c.candidate_key === f.selected_candidate_key) || {};
    let mode = imageMode[f.id] || 'fit';
    let div = document.createElement('div');
    div.className = 'card';
    div.innerHTML = `<div class="card-head">
      <h3 tabindex="0">${esc(f.id)}</h3>
      <span class="pill ${esc(f.validation_status || 'pending')}">${esc(f.validation_status || 'pending')}</span>
      <span class="pill">display type: ${esc(f.display_type || 'auto')}</span>
      ${f.display_type_manual ? `<span class="pill manual">manual ${esc(f.display_type_manual)}</span>` : `<span class="pill">auto ${esc(f.display_type_auto || '')}</span>`}
      ${f.selected_source ? `<span class="pill selected-pill">selected: ${esc(f.selected_source)}</span>` : '<span class="pill invalid">no selected LaTeX</span>'}
    </div>
    <div class="grid">
      <section class="panel">
        <h4>Original formula image</h4>
        <p class="help">This is the source PNG produced from the DOCX formula image. It is intentionally large. Use <b>Actual size</b> if fit-to-panel makes a long formula too small.</p>
        <div class="image-stage ${mode === 'actual' ? 'actual' : ''}">
          ${f.png_url ? `<img class="formula-img" src="${f.png_url}" alt="original formula ${esc(f.id)}">` : '<span class="empty">no original PNG</span>'}
        </div>
        <p>
          <button class="ghost" onclick="setImageMode('${f.id}','fit')" title="Scale image to fit the panel">Fit panel</button>
          <button class="ghost" onclick="setImageMode('${f.id}','actual')" title="Show original PNG pixels; scroll if needed">Actual size</button>
          ${f.png_url ? `<a class="button" href="${f.png_url}" target="_blank" title="Open source formula image in a new tab">Open image</a>` : ''}
        </p>
        <p>
          <button class="secondary" onclick="setDisplay('${f.id}','inline')" title="Use \\( latex \\): formula remains inside a paragraph">Set inline</button>
          <button class="secondary" onclick="setDisplay('${f.id}','display')" title="Use \\[ latex \\]: formula becomes a separate equation block">Set display</button>
        </p>
        <p class="help"><b>Inline</b> = inside text. <b>Display</b> = standalone block equation. This affects both validation and final Markdown wrappers.</p>
      </section>

      <section class="panel">
        <h4>Selected LaTeX / manual edit</h4>
        <p class="help">This textarea starts with the currently selected LaTeX. Edit it when OCR is wrong. Ctrl+Enter also compiles.</p>
        <textarea id="ta-${f.id}" spellcheck="false">${esc(f.selected_latex || '')}</textarea>
        <p>${selected.preview_url ? `<img class="preview" src="${selected.preview_url}" alt="selected rendered preview">` : '<span class="small">no selected rendered preview</span>'}</p>
        <button onclick="compile('${f.id}')" title="Compile textarea LaTeX as a manual candidate and create a preview">Compile/recompile</button>
        <button class="ok" onclick="selectLatex('${f.id}')" title="Compile and select textarea LaTeX as manual candidate">Select textarea</button>
      </section>

      <section class="panel">
        <h4>All candidates</h4>
        <p class="help">Each OCR engine and manual edit can produce candidates. Prefer candidates that are valid and visually match the original image.</p>
        <div>${(f.candidates || []).map(c => candidateHtml(f,c)).join('') || '<div class="empty">no candidates</div>'}</div>
      </section>

      <section class="panel">
        <h4>Status / errors</h4>
        <p class="help">Use this panel for validation errors and selection reasons. If the formula is unresolved, merge will keep a PNG TODO fallback.</p>
        <pre>${esc(f.validation_error || 'No formula-level error.')}</pre>
        ${(f.selection_rejected || []).length ? `<details open><summary>Selection rejected reasons</summary><pre>${esc(JSON.stringify(f.selection_rejected, null, 2))}</pre></details>` : ''}
        <p class="small">Keyboard: Tab/Shift+Tab navigates controls. Ctrl+Enter in textarea compiles.</p>
      </section>
    </div>`;
    el.appendChild(div);
  });
  document.querySelectorAll('textarea').forEach(t => t.onkeydown = e => { if(e.ctrlKey && e.key === 'Enter') compile(t.id.slice(3)); });
}

async function compile(id) {
  let ta = document.getElementById('ta-' + id);
  await api(`/api/formulas/${id}/compile`, {latex: ta.value});
  await load();
}
async function selectLatex(id) {
  let ta = document.getElementById('ta-' + id);
  await api(`/api/formulas/${id}/select`, {latex: ta.value});
  await load();
}
async function selectKey(id, key) {
  await api(`/api/formulas/${id}/select`, {candidate_key: key});
  await load();
}
async function setDisplay(id, t) {
  await api(`/api/formulas/${id}/display-type`, {display_type: t});
  await load();
}
load();
</script>
</body>
</html>'''


class ReviewHandler(BaseHTTPRequestHandler):
    server_version = "docx2xelatex-review/0.1"

    @property
    def wp(self) -> WorkPaths:
        return self.server.wp  # type: ignore[attr-defined]

    @property
    def config(self) -> dict[str, Any]:
        return self.server.config  # type: ignore[attr-defined]

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: Any, status: int = 200) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"), "application/json; charset=utf-8")

    def _body(self) -> dict[str, Any]:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path in {"/", "/formulas.html"}:
                return self._send(200, FORMULAS_HTML.encode("utf-8"), "text/html; charset=utf-8")
            if parsed.path == "/api/formulas":
                manifest = load_manifest(self.wp.root)
                return self._json([_public_formula(f, self.wp) for f in manifest.get("formulas", [])])
            if parsed.path.startswith("/api/formulas/"):
                fid = parsed.path.rsplit("/", 1)[-1]
                return self._json(_public_formula(_formula_by_id(load_manifest(self.wp.root), fid), self.wp))
            if parsed.path.startswith("/assets/"):
                rel = unquote(parsed.path[len("/assets/"):])
                target = (self.wp.root / rel).resolve()
                if not str(target).startswith(str(self.wp.root.resolve())) or not target.exists():
                    return self._json({"error": "not found"}, 404)
                return self._send(200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream")
            return self._json({"error": "not found"}, 404)
        except Exception as exc:
            return self._json({"error": str(exc)}, 500)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        body = self._body()
        try:
            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) == 4 and parts[:2] == ["api", "formulas"] and parts[3] == "compile":
                fid = parts[2]
                latex = str(body.get("latex") or "")
                display_type = body.get("display_type")
                if display_type:
                    manifest = load_manifest(self.wp.root)
                    f = _formula_by_id(manifest, fid)
                    set_display_type_manual(f, str(display_type))
                    write_json_atomic(self.wp.manifest_json, manifest)
                result = compile_manual_candidate(self.wp.root, fid, latex, self.config)
                return self._json({"status": result.get("validation_status"), "validation_status": result.get("validation_status"), "error": result.get("validation_error"), "preview_png": (result.get("artifacts") or {}).get("preview_png"), "preview_png_url": _rel_asset((result.get("artifacts") or {}).get("preview_png"), self.wp), "latex_hash": result.get("latex_hash"), "candidate_key": result.get("candidate_key")})
            if len(parts) == 4 and parts[:2] == ["api", "formulas"] and parts[3] == "select":
                fid = parts[2]
                formula = select_candidate(self.wp.root, fid, candidate_key=body.get("candidate_key"), latex=body.get("latex"), config=self.config if body.get("latex") is not None else None)
                return self._json(_public_formula(formula, self.wp))
            if len(parts) == 4 and parts[:2] == ["api", "formulas"] and parts[3] == "display-type":
                manifest = load_manifest(self.wp.root)
                formula = _formula_by_id(manifest, parts[2])
                set_display_type_manual(formula, str(body.get("display_type")))
                write_json_atomic(self.wp.manifest_json, manifest)
                return self._json(_public_formula(formula, self.wp))
            if parsed.path == "/api/merge":
                out = merge_markdown(self.wp.root, self.config, strict=True)
                return self._json({"status": "ok", "final_md": str(out)})
            if parsed.path == "/api/build":
                return self._json(build_stage(self.wp.root, self.config, force=True))
            if parsed.path == "/api/audit":
                return self._json(audit_workdir(self.wp.root, self.config))
            return self._json({"error": "not found"}, 404)
        except Exception as exc:
            return self._json({"status": "failed", "error": str(exc)}, 500)


def run_review_server(workdir: str | Path, config: dict[str, Any], host: str = "127.0.0.1", port: int = 8765) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Review server is local-only by default; bind to 127.0.0.1 unless you understand the privacy risk.")
    wp = WorkPaths.from_workdir(workdir)
    wp.ensure()
    server = ThreadingHTTPServer((host, int(port)), ReviewHandler)
    server.wp = wp  # type: ignore[attr-defined]
    server.config = config  # type: ignore[attr-defined]
    print(f"docx2xelatex review server: http://{host}:{port}/formulas.html")
    server.serve_forever()
