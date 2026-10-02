# Runtime setup

Use macOS, Windows or Linux with Python 3.12, `venv`, `pip` and SQLite FTS5. On Linux the Python installation may need its distribution’s `python3.12-venv` package. Python installers and package managers remain the recipient’s choice. Paths may contain spaces or Unicode. Invoke commands with Python; executable permissions, shell activation and Git are unnecessary.

Choose your host and initialize:

| Platform | Claude Code | Codex |
| --- | --- | --- |
| macOS / Linux | `python3.12 pipeline.py init --host claude` | `python3.12 pipeline.py init --host codex` |
| Windows PowerShell | `py -3.12 pipeline.py init --host claude` | `py -3.12 pipeline.py init --host codex` |

The startup skills run these same commands: `/fuzzy-start` in Claude, `$fuzzy-start` in Codex. Open the extracted project root, retaining all hidden directories. Installation creates only a project-local environment and missing operational files. `--wheelhouse PATH` installs from local dependency wheels with no package network access. `--no-install` checks an existing environment. Initialization does not ingest PDFs or require credentials. It leaves inputs, receipts, configuration and existing packs intact.

The pinned packages in `requirements.txt` provide PDF processing and image handling. They are installed by pip with their upstream distribution notices. Use your own document rights and applicable package license terms when operating or extending the project. No separate web service, embedding provider, database server or account lookup is needed.

For OCR install Tesseract and its language data through your platform’s supported installer/package manager. Make `tesseract` available on PATH. If detection cannot find the language file, set `STUDY_TESSDATA` to the directory containing the selected `.traineddata` file. Configure one installed language code in `bootstrap-settings.json` (default `eng`). `pipeline.py doctor` reports native and OCR readiness separately. `intake --ocr skip` is explicitly native-text-only; scanned content remains a gap until local OCR and original inspection are available. Never use model transcription.

The default route supports Claude Code 2.1.251+ or Codex with independent native
workers and local file/shell tools. No host authentication is needed to initialize
Python. Sign in through the selected host's normal process; never put credentials
in the project. Claude needs no Codex binary or OpenAI access. Both hosts use the
same [roles](AGENT_ROLES.md), [queue](JOB_QUEUE.md), educational rules and pipeline.

Select the author/reviewer model and supported effort in the host session. Their
workers inherit it. Explicit user overrides take precedence; use supported native
model/effort settings, not prompt text pretending to change runtime. Record actual
exposed provenance once; an unavailable value is `unverified`, with an explanation.

`pipeline-config.json` stores recipient choices. Initialization creates it only
when absent; `init --host HOST` updates just the selected host. New examples use
`hosts.codex.delivery` and `hosts.claude.delivery`. Legacy top-level `delivery`
still configures Codex. Claude selection never reuses that OpenAI-specific pair.
Codex delivery defaults to `gpt-6-sol` / `medium`; Claude explicitly defaults to
`inherit` / `inherit`. Configure only a model/effort actually available to you.

For a Claude delivery override, edit `hosts.claude.delivery` and run
`python pipeline.py host --host claude --sync-delivery`. It generates only the
ignored local delivery worker; dispatch the returned worker name. Unsupported
Claude effort syntax fails without rewriting configuration. Per-model support
and organization policy are checked in Claude. See [HOST_CLAUDE](HOST_CLAUDE.md)
and [HOST_CODEX](HOST_CODEX.md); no effort equivalence between providers is assumed.

`pipeline.py doctor` reports local dependency/FTS5/OCR readiness separately from
host adapter files. `pipeline.py host --host HOST` also runs a bounded CLI version
probe, without authentication, account lookup or AI calls; `--no-probe` reads
only local files. Missing CLI, old Claude, missing hidden adapters and unsupported
configuration are distinct results. CLI presence is not authentication or proof
that workers can execute. A Codex desktop session may provide native workers even
when its CLI is not on PATH.

The optional reviewer fallback and detached queue are **Codex-only**. Use the
public `codex` CLI with your own access. Set `CODEX_CLI_PATH` or pass `--cli`
at invocation time if needed. Commands retain workspace-write sandboxing and
`--skip-git-repo-check`; downloaded ZIPs need no Git history. After selecting
Claude, these optional commands reject execution and point to native `/job-queue`.
Use `--host codex` only when explicitly intending that fallback. No automatic
fallback invokes a different provider. Normal permissions remain in force.

PDF extraction/OCR/search/validation/export are local. AI workers process the
prompts, passages, images and drafts they read through the selected provider.
Package installation may download Python dependencies. No extra telemetry,
upload service, embedding provider or MCP server is introduced; Claude project
settings disable nonessential traffic and OpenTelemetry. Host/provider policies,
retention and user-installed tools remain outside this project's control.

Normal artifact validation uses HTML/data, without a browser renderer. Optional `qa --render` desktop diagnostics require locally installed `wkhtmltopdf`; this is not an installation or production gate. Browser Print handles printable HTML without that tool. Original-page evidence PDFs always use the local PDF runtime.

After relocation on the same machine, rerun initialization and source checks. Between operating systems, transfer source/input/working files, omit the local `.venv`, and initialize a new environment. If an environment is incomplete or incompatible, move only `.venv` aside and initialize again. Do not move or overwrite source PDFs or working records. Treat case-only filename changes deliberately on case-sensitive systems.

## Troubleshooting and continuation

- Missing Python 3.12: install it through your platform's supported installer; do
  not silently use a different Python. On Linux install its venv package too.
- Missing dependencies: rerun init, or supply a local wheelhouse. `--no-install`
  never downloads. A missing host does not prevent environment initialization.
- Missing OCR: install local Tesseract/language data. Native-only intake may
  proceed explicitly with `--ocr skip`; scanned requirements remain gaps.
- Missing Claude skill/worker: open the standalone root, check hidden files,
  reopen Claude and use `/agents`. A global project skill is not a prerequisite.
- Model unavailable/substituted: select an available supported pair in the host.
  Do not claim a requested flag was observed runtime, or silently use another model.
- Permission denied: use the host's normal permission flow. Never disable
  protections, change global account settings or start unapproved background work.
- Resume: read the job checkpoint, preserve receipts/exports and follow the same
  worker's continuation handle. If switching hosts, contexts cannot transfer:
  start fresh workers with the existing files, disclose lost continuity and retain
  only genuinely current acceptance under the existing dependency contract.

Release maintainers use the explicit package builder and [platform checks](../../PLATFORM_SUPPORT.md).
Never copy recipient configuration or a populated working directory into a release.
