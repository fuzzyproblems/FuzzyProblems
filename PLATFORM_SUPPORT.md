# Platform support and development checks

Maintain macOS, Windows and Linux support with Python 3.12 and the exact pins in
requirements.txt. Follow [SETUP](foundation/guidance/SETUP.md). Initialization
creates a new local environment; never transfer `.venv` between machines. Keep
UTF-8, portable generated names, project-relative stored paths, safe regular
files and case-correct relative links. Preserve original filenames and bytes.

With the initialized project interpreter:

```bash
# macOS / Linux
.venv/bin/python -X utf8 -B scripts/check.py --strict
```

```powershell
# Windows
.venv\Scripts\python.exe -X utf8 -B scripts/check.py --strict
```

The suite uses synthetic sources and receipts to check native local OCR, startup,
host routing, CLI guards, independent-review rejection/revision/invalidation,
field projection, neutral metadata, symlink/case safety, relative links, Anki,
exact-byte publication and distribution archives. Paths include spaces and Unicode.
Strict mode treats skipped coverage as incomplete. No model account or private
inputs are needed. Synthetic receipts never authorize real educational output.

For an actual fresh environment outside the source tree, package the release with
`python scripts/package_distribution.py`, extract it into a path containing spaces
and Unicode, and run the documented init command. Use `--wheelhouse PATH` for an
offline dependency source; rerun `init --no-install`. Run the strict suite from
that extracted copy as well. This tests a new environment rather than pretending a
copied `.venv` is a portable installation. The package script works without Git and
ships every explicit hidden adapter. `FuzzyProblems/` is the authoritative source;
there is no parent-project generation dependency. Update distribution-files.json
deliberately when adding reusable files, never populate it from a working tree glob.

The included [CI workflow](.github/workflows/portability.yml) runs these checks on
native Ubuntu, macOS and Windows runners. Workflow configuration is not a passing
run: require successful native results on all three before claiming portability
verification. Do not infer Windows/Linux success from a macOS run or a mock.

Changes to learner templates or requested print behavior additionally require
A4/Letter browser-print verification and targeted visual inspection. Ordinary
host/configuration changes do not introduce a per-pack print, screenshot or
privacy-approval gate. Unchanged learner templates retain their print styling.

Live host verification is separate: in a clean synthetic project, launch the
selected authenticated host, invoke its startup skill and request serial native
author/reviewer/delivery handoffs without educational approval. Observe discovery,
fresh contexts, actual model/effort exposure and continuation. Record which host
actually ran. Missing CLI/account access is an unverified live capability, not a
mocked pass. Never include host transcripts or authentication state in releases.
