# docx2xelatex

`docx2xelatex` — локальный, конфиденциальный pipeline для перевода старых русскоязычных научных DOCX в контролируемый Markdown, LaTeX-формулы и чистый XeLaTeX/PDF.

Главная идея: не доверять одному «магическому» конвертеру. Текст и структуру извлекает Pandoc, каждая формула проходит отдельный жизненный цикл:

```text
image → png → candidates → validation → selection → merge
```

Если отдельная формула не распознана или не компилируется, документ не ломается: исходная картинка остаётся в Markdown, рядом добавляется `TODO_FORMULA_f0001`, а проблема видна в HTML-отчёте.

## Почему финальный `.tex` от docx2tex не используется

`docx2tex` иногда умеет извлекать формулы из старых OLE/MathType/Equation Editor объектов, но его полный `.tex` часто грязный, нестабильный и плохо компилируется. В этом проекте `.tex` от `docx2tex` используется только как дополнительный источник кандидатов формул. Финальный документ строится заново: `Pandoc Markdown → final.md → clean final.tex → XeLaTeX`.

## Конфиденциальность

- Документы, изображения, формулы и текст не отправляются во внешние API.
- OCR формул обращается только к локальному Ollama по `http://localhost:11434`.
- Код специально отказывается работать с не-localhost Ollama URL.
- Интернет нужен только вам вручную для установки внешних зависимостей, если они ещё не установлены.

## Установка зависимостей

Установите локально:

1. **Python 3.11+**
2. **Pandoc** — для DOCX → Markdown и final Markdown → TeX.
3. **MiKTeX** или **TeX Live** с `xelatex` и пакетами `fontspec`, `amsmath`, `mathtools`, `upgreek`, `tensor`, `xfrac`.
4. **ImageMagick** с командой `magick` — для WMF/EMF → PNG.
5. **Ollama**.
6. Модель **qwen3-vl:8b** в Ollama:

```powershell
ollama pull qwen3-vl:8b
```

Проверьте, что Ollama слушает `localhost:11434`.

## PowerShell quickstart

Из папки проекта:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .

docx2xelatex doctor
docx2xelatex init-config --out config.yaml

docx2xelatex full `
  --input "C:\path\to\work.docx" `
  --workdir "C:\path\to\build" `
  --config config.yaml
```

Артефакты будут лежать в `--workdir`.

## Пошаговый запуск

Пошаговый режим удобен для контроля качества и ручной правки формул:

```powershell
docx2xelatex pandoc-md --input "C:\path\to\work.docx" --workdir "C:\path\to\build" --config config.yaml

docx2xelatex manifest --markdown "C:\path\to\build\text.md" --workdir "C:\path\to\build" --config config.yaml

docx2xelatex render-images --workdir "C:\path\to\build" --config config.yaml

docx2xelatex ocr --workdir "C:\path\to\build" --config config.yaml

docx2xelatex validate --workdir "C:\path\to\build" --config config.yaml

docx2xelatex select --workdir "C:\path\to\build" --config config.yaml

docx2xelatex report --workdir "C:\path\to\build" --config config.yaml

docx2xelatex merge --workdir "C:\path\to\build" --config config.yaml

docx2xelatex build --workdir "C:\path\to\build" --config config.yaml
```

## Команды CLI

- `doctor` — проверяет Python, `pandoc`, `magick`, `xelatex`, доступность Ollama и наличие модели. Ничего не устанавливает.
- `init-config --out config.yaml` — создаёт YAML-конфиг.
- `inspect-docx --input work.docx --workdir build` — анализирует DOCX без вывода текста: считает `word/media/*.wmf`, `*.emf`, `word/embeddings/oleObject*.bin`, OMML `<m:oMath>`.
- `pandoc-md` — создаёт `build/text.md` и `build/media/...`.
- `manifest` — ищет image-формулы в Markdown и создаёт `build/formulas/manifest.json`.
- `render-images` — конвертирует изображения формул в `build/formulas/png/f0001.png`.
- `ocr` — отправляет PNG в локальный Ollama/qwen3-vl и сохраняет кандидатов; показывает progress bar и пишет status JSON перед каждым запросом.
- `add-docx2tex-candidates` — добавляет кандидатов из `.tex`, полученного `docx2tex`.
- `validate` — компилирует каждый кандидат отдельным минимальным XeLaTeX-файлом.
- `select` — выбирает лучший валидный кандидат по приоритету.
- `report` — создаёт `build/report/formulas.html`.
- `merge` — создаёт `build/final.md`.
- `build` — создаёт `build/final.tex` и, если включено, `build/final.pdf`.
- `full` — запускает основной pipeline последовательно.

Для инспекции без OCR/валидации есть `--dry-run` у команд `ocr` и `validate`. Для подробного OCR-лога используйте:

```powershell
docx2xelatex ocr --workdir "C:\path\to\build" --config config.yaml --verbose

# Если отдельная формула считается дольше 10 минут:
docx2xelatex ocr --workdir "C:\path\to\build" --config config.yaml --verbose --timeout-seconds 1200
```

OCR выполняется последовательно, не параллельно. Во время обработки каждой формулы файл статуса создаётся заранее:

```text
build/formulas/ocr/f0001_ollama_qwen.json
```

В нём видно `status: running`, `done` или `error`, путь к исходному PNG, путь к уменьшенной OCR-копии и время выполнения. Если процесс был прерван, последняя формула может остаться со статусом `running`; при следующем запуске она будет обработана заново, если candidate ещё не записан в `manifest.json`.

## Подключение `.tex` от docx2tex

Если вы отдельно получили `.tex` через `docx2tex`, добавьте его как источник кандидатов:

```powershell
docx2xelatex add-docx2tex-candidates `
  --workdir "C:\path\to\build" `
  --docx2tex-tex "C:\path\to\out\work.tex" `
  --config config.yaml

# Затем заново проверьте и выберите кандидаты:
docx2xelatex validate --workdir "C:\path\to\build" --config config.yaml
docx2xelatex select --workdir "C:\path\to\build" --config config.yaml
docx2xelatex report --workdir "C:\path\to\build" --config config.yaml
```

Сопоставление идёт по порядку найденных математических фрагментов и формул в manifest. Это намеренно простой и проверяемый механизм: результат обязательно смотрите в HTML-отчёте.

## Ручная правка плохих формул

1. Откройте:

```text
build/report/formulas.html
```

2. Найдите красные строки или неверный LaTeX.
3. Отредактируйте вручную `build/formulas/manifest.json`:
   - поле `selected_latex`;
   - при необходимости `selected_source`, например `manual`;
   - можно оставить `validation_status` как есть, но лучше после правки запустить `validate`/`select` заново, если правка добавлена как candidate.
4. Пересоберите только хвост pipeline:

```powershell
docx2xelatex merge --workdir "C:\path\to\build" --config config.yaml
docx2xelatex build --workdir "C:\path\to\build" --config config.yaml
```

Если `selected_latex` заполнен вручную, `merge` вставит его в `final.md`. Если поле пустое, исходная картинка останется с `TODO_FORMULA_...`.

## Где лежат артефакты

```text
build/
  text.md                         # Markdown после Pandoc
  media/                          # извлечённые Pandoc изображения
  formulas/
    manifest.json                 # жизненный цикл всех формул
    png/f0001.png                 # PNG для OCR/проверки
    ocr/f0001_ollama_qwen.json    # raw OCR-ответы
    validate/f0001/               # отдельные TeX/log/pdf для кандидатов
  report/formulas.html            # HTML-отчёт ручной проверки
  final.md                        # Markdown с LaTeX-формулами или TODO
  final.tex                       # чистый TeX от Pandoc
  final.pdf                       # итоговый PDF, если XeLaTeX собрался
  final.log                       # лог итоговой сборки
```

## Конфиг

Создайте стартовый конфиг:

```powershell
docx2xelatex init-config --out config.yaml
```

Важные поля:

```yaml
candidate_selection:
  priority: ["docx2tex", "ollama_qwen"]

ollama:
  base_url: "http://localhost:11434"
  model: "qwen3-vl:8b"
  timeout_seconds: 600
  num_predict: null      # null = не ограничивать ответ модели вручную
  resize_image: false    # quality-first: отправлять оригинальный PNG
  max_image_side: 2400   # используется только если resize_image: true

latex:
  engine: xelatex
  mainfont: "Times New Roman"
  build_pdf: true
```

Если хотите предпочитать qwen3-vl вместо docx2tex, поменяйте порядок:

```yaml
candidate_selection:
  priority: ["ollama_qwen", "docx2tex"]
```

## Idempotent/resumable поведение

- Если `text.md`, PNG или candidate уже существуют, этапы не делают повторную работу без `--force`.
- OCR-кандидаты и `manifest.json` сохраняются после каждой формулы, а не только в конце команды.
- Пустой или error-кандидат `ollama_qwen` не считается успешно распознанным и будет переобработан при следующем `ocr` без обязательного `--force`.
- Ошибка одной формулы записывается в `manifest.json` и `build/formulas/ocr/*.json`, но не останавливает весь документ.
- Все промежуточные файлы сохраняются для аудита.

## Future-ready OCR engines

Интерфейс движка находится в:

```text
src/docx2xelatex/engines/base.py
```

Для подключения `pix2tex` или `TexTeller` добавьте новый модуль в `src/docx2xelatex/engines/`, верните `Candidate(source="...", latex="...")`, затем добавьте CLI-команду или включите движок в общий OCR stage.

## Troubleshooting

### `Pandoc not found`

Установите Pandoc и убедитесь, что `pandoc.exe` доступен в `PATH`. Проверьте:

```powershell
pandoc --version
docx2xelatex doctor
```

### `magick not found`

Установите ImageMagick. На Windows важно, чтобы команда называлась именно `magick` и была доступна в новом PowerShell.

```powershell
magick -version
```

### `xelatex not found`

Установите MiKTeX или TeX Live и проверьте:

```powershell
xelatex --version
```

Если в конфиге указан другой engine, `doctor` проверит его.

### Ollama unavailable

Проверьте, что Ollama запущен локально:

```powershell
ollama list
```

`docx2xelatex` использует только `http://localhost:11434`. Внешние URL отклоняются.

### Нет модели `qwen3-vl:8b`

```powershell
ollama pull qwen3-vl:8b
docx2xelatex doctor
```

### OCR очень долго грузит GPU или кажется, что завис

Это ожидаемо для vision-модели: один запрос к `qwen3-vl:8b` может занимать десятки секунд или минуты, особенно если PNG получился очень большим. Команда теперь показывает progress bar и пишет status JSON до обращения к Ollama. Проверьте текущую формулу:

```powershell
Get-Content "C:\path\to\build\formulas\ocr\f0001_ollama_qwen.json"
```

По умолчанию OCR использует оригинальный PNG из `build/formulas/png/`, потому что качество важнее скорости. Уменьшенная копия создаётся только если вы явно включили:

```yaml
ollama:
  resize_image: true
  max_image_side: 2400
```

Настройки качества/скорости:

```yaml
ollama:
  resize_image: false      # лучший default для качества
  max_image_side: 2400     # применяется только при resize_image: true
  num_predict: null        # не ограничивать генерацию вручную
  retry_empty_with_original: true
```

Если очень большие PNG действительно тормозят, сначала попробуйте `resize_image: true` и `max_image_side: 2400`. Если качество распознавания падает или появляются пустые ответы — верните `resize_image: false`.

### Ollama request timed out

По умолчанию timeout одного OCR-запроса — 600 секунд. Для сложных формул или медленного GPU можно увеличить без правки YAML:

```powershell
docx2xelatex ocr --workdir "C:\path\to\build" --config config.yaml --verbose --timeout-seconds 1200
```

Или в `config.yaml`:

```yaml
ollama:
  timeout_seconds: 1200
```

### qwen возвращает текст вместо формулы

OCR prompt уже требует только LaTeX без Markdown fences и без `$`. Если модель всё равно добавляет пояснения, они частично чистятся в `latex_clean.py`, но обязательно смотрите `report/formulas.html`. Плохую формулу лучше исправить вручную в `manifest.json`.

### WMF conversion fails

Проверьте ImageMagick policy/делегаты и попробуйте уменьшить density в конфиге:

```yaml
images:
  imagemagick_density: 600
```

Исходная картинка всё равно останется в manifest, ошибка будет в `png_error`.

### formula validation fails

Откройте соответствующие файлы:

```text
build/formulas/validate/f0001/candidate_ollama_qwen_1.tex
build/formulas/validate/f0001/candidate_ollama_qwen_1.log
```

Исправьте формулу или добавьте ручной candidate.

### final PDF fails, но final.tex существует

Это нормальный recoverable результат. Откройте:

```text
build/final.tex
build/final.log
```

Проект не удаляет `final.tex`, даже если PDF не собрался.

## Разработка

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
pytest
```
