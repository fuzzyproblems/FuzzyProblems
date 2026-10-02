# Commands

Run from the project root with Python 3.12. Below, `python` means `python3.12` on macOS/Linux or `py -3.12` on Windows. Quote paths containing spaces. The launcher locates its own root, so an absolute path to `pipeline.py` also works from another working directory.

```text
python pipeline.py init --host claude
python pipeline.py init --host codex
python pipeline.py host --host claude
python pipeline.py host --host claude --sync-delivery
python pipeline.py doctor
python pipeline.py intake
python pipeline.py source-check
python pipeline.py intake-view SOURCE_ID --start 1 --limit 3
python pipeline.py register-source work/source.json
python pipeline.py register-style work/style.json
python pipeline.py register-unit work/unit.json
python pipeline.py prepare --lesson UNIT_ID --preview
python pipeline.py prepare --lesson UNIT_ID --pack PACK
python pipeline.py prepare --lesson UNIT_ID --pack PACK --objectives 1 2 --scope-reason "Requested objectives 1 and 2"
python pipeline.py anki-tags PACK --course COURSE --lesson-label TOPIC --use-defaults
python pipeline.py search "search terms" --limit 8
python pipeline.py page SOURCE_ID 1 --context 1
python pipeline.py render SOURCE_ID 1 work/page.png
python pipeline.py ocr SOURCE_ID 1
python pipeline.py entry-inputs ENTRY_ID
python pipeline.py preflight PACK
python pipeline.py review-handoff PACK
python pipeline.py review-view PACK
python pipeline.py review-view PACK --section SELECTOR --start 0 --limit 8
python pipeline.py review-changes PACK
python pipeline.py check-entry ENTRY_ID
python pipeline.py review-request PACK
python pipeline.py build PACK
python pipeline.py check PACK
python pipeline.py publish PACK --folder LESSON_VERSION
python pipeline.py catalogue
python pipeline.py archive PACK --name LESSON_VERSION.zip
python pipeline.py impact
```

Choose one init host; reruns without --host preserve selection. Startup skills are `/fuzzy-start` in Claude Code and `$fuzzy-start` in Codex. `host` works before installing dependencies and never authenticates or calls an AI model. See [SETUP](foundation/guidance/SETUP.md).

All operations retain original sources. Source/unit/style JSON records follow [PDF_INTAKE](foundation/guidance/PDF_INTAKE.md). Authored content and independent receipts follow [FORMAT](foundation/library/FORMAT.md). No command creates educational approval. `entry-inputs` returns `entry_hash` and `dependencies`; copy only the returned dependencies into the entry, and use both in its receipt after independent review.

Select practice types before authoring with `prepare --practice-types short_answer sba` or supported essay, calculation, data_interpretation and practical types. Full lessons omit `--objectives`; partial requests require an explicit reason. Use `anki-tags --prompt` interactively, or supply selected labels. `--use-defaults` requires actual user acceptance or delegated choice.

`search --role textbooks` is the default; `--recovery` includes navigation/non-teaching material. `intake --scan-only` inventories without extraction, and `intake --ocr skip` records native-only discovery. Read every required intake/review page via bounded continuation; snippets never prove complete coverage.

`qa PACK` validates HTML/data. `qa PACK --render --files objective-01.html` is optional, using local wkhtmltopdf for a detected presentation concern. `inputs PACK --full`, `preflight PACK --full` and `review-view PACK --receipt` provide bounded diagnostics when needed. Local diagnostic counters stay in `.diagnostics/`; `STUDY_DIAGNOSTICS=0` disables them without changing command results. `rebuild-cache --check` checks source-keyed indexes; `rebuild-cache --rebuild` reconstructs only derived indexes from intact caches.

The standard-library catalogue can also run directly: `python regenerate_study_guide.py`, from any working directory when the script path is supplied. It scans its sibling `output/`, writes root `StudyGuide.html` and nonempty grouping `navigation.html` pages at every depth. Each page links immediate guides/groups and parent/main navigation. A guide with exactly one conforming chapter-list item labelled `Objective N · topic` opens its existing, exact-case, regular sibling HTML chapter directly, including earlier versions. Multiple chapters, malformed lists, unsafe links, missing targets and nonconforming labels retain `index.html`. Refresh after additions, moves, renames or removal; only generator-owned stale navigation pages are removed, including obsolete grouping `StudyGuide.html` pages. Unrelated files and study content are preserved. Moving a guide deeper requires checked relative-source links in that guide; catalogue refresh changes navigation only.

Initial generation, publication refresh and manual regeneration use natural numeric ordering for objective and grouping folder names at every depth: `Objective-1`, `Objective-2`, `Objective-3`, … `Objective-17`; `Year2` precedes `Year10`. Versions remain grouped locally with the newest version first. Existing folder names and study content are preserved.

## Checked publication destinations

For separate objectives within one lesson collection, use matching destinations:

```text
python pipeline.py build PACK --folder Example-Lesson/Objective-1-v1
python pipeline.py check PACK
python pipeline.py publish PACK --folder Example-Lesson/Objective-1-v1
```

The destination is relative to `output/`; omit that prefix in `--folder`. Use forward slashes and portable folder components. Absolute paths, traversal, empty components, Windows device names, case conflicts and symlink/junction paths are rejected. Publication always creates a new version and never replaces an existing delivery.

`build --folder` stores the checked destination in internal `delivery.json`. Later builds without `--folder` retain that choice. Publication must match the whole configured destination, even when another folder has the same depth. Changing the destination requires `build --folder NEW_DESTINATION` and current checks. Without a delivery configuration, the original flat-folder route remains available. A configured flat destination also requires an exact match. The optional Codex-only `review-run --publish` shortcut reuses this binding; bind a nested destination with `build --folder` before using that shortcut.

Original textbook links use the checked depth: `../../Textbooks/...` for a flat version, `../../../Textbooks/...` for the two-component example above. Evidence links stay within the delivery. Copying a project preserves these links only when the relative output and `Textbooks/` layout is retained. Moving only an existing guide to another depth needs a new checked export; refreshing the catalogue never rewrites its citations or learner files.

## Catalogue diagnostics and sharing

The generator writes `output/diagnostics.txt` with relative discovery decisions and structured failure categories. It omits absolute paths, the working directory, raw exception messages and tracebacks. Failures return a nonzero exit status; diagnostic-write failures use the same sanitized format. Relative folder labels remain user-supplied data. Keep diagnostics internal: both `output/` and `.diagnostics/` are Git-ignored, and learner publication/archives contain only the explicit learner allowlist. Manually sharing an entire working folder bypasses those boundaries.

## Delivery regression tests

With the initialized project's Python interpreter, run `.venv/bin/python -X utf8 -B -m unittest discover -s scripts -p 'test_*.py'` on macOS/Linux, or `.venv\Scripts\python.exe -X utf8 -B -m unittest discover -s scripts -p 'test_*.py'` on Windows. The fixtures create disposable synthetic PDFs, packs, receipts and catalogues. They never approve real educational material or regenerate the installed catalogue. No OCR, model account or private inputs are required. A skipped OS-specific check is missing coverage; use actual native runs on all three platforms before claiming platform verification.

For targeted revision, preserve a genuinely accepted baseline receipt and its `review/accepted` snapshot in a new working version. Run `review-request PACK --baseline baseline.json`; only the independent reviewer may retain unchanged records after current dependency, complete-wording and depth assessment. Follow the full contract; an earlier unaccepted draft cannot donate approval.

## Native hosts and optional CLI commands

Normal production follows the shared [job queue](foundation/guidance/JOB_QUEUE.md),
with [Claude](foundation/guidance/HOST_CLAUDE.md) or [Codex](foundation/guidance/HOST_CODEX.md)
native workers. Both complete intake, preparation, authoring, independent review,
revisions, build, validation, publication and continuation.

`review-run` and detached `queue` are Codex-only. They fail early with an actionable
message for a selected Claude host, including dry-run/validate-only routes; use
the shared `check PACK` to validate current records without launching a model.
An explicit `--host codex` selects the optional Codex transport. No command turns
author self-review into acceptance.

## Standalone release verification

Run `python scripts/check.py --strict` with the project interpreter. See
[PLATFORM_SUPPORT](PLATFORM_SUPPORT.md) for native commands, OCR requirements and
what synthetic checks establish. Build a reusable archive with
`python scripts/package_distribution.py`; use a new output name or explicit
`--replace`. Only [distribution-files.json](distribution-files.json) members ship.
The builder rejects unsafe paths/symlinks/case conflicts, constructs neutral ZIP
fields and checks exact members and bytes before publishing the archive.
