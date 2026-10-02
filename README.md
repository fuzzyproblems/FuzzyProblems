# FuzzyProblems: AI Study Guide Generator for Claude Code and OpenAI Codex

**FuzzyProblems is an open-source AI study guide generator and source-verification pipeline that turns textbook PDFs and learning objectives into structured, traceable study materials.** Built for students, educators, facilitators and researchers, it combines document retrieval, educational authoring, independent AI review and export in a customisable workflow. Run the complete workflow in **Claude Code or OpenAI Codex**, using your own AI access, textbook PDFs and learning objectives. Define the subject, learner level and scope; the shared Python pipeline handles local PDF extraction, OCR, search and export.

The hope is that people will fork the pipeline, refine, optimize and specialize it for their own courses, whether at school, college, university, medical school, nursing school, business school, or any other professional and higher-education programmes, and share those improvements so future generations don’t have to start from scratch when studying the same course.

Create detailed study guides, practice questions, worked explanations, marking guidance and **Anki flashcards with source references**. Supported practice formats include short answers, multiple-choice questions, essays, calculations, data interpretation and practical tasks. Outputs include portable HTML guides, Anki import files and evidence PDFs containing the original textbook pages, with supporting passages highlighted where reliable matching is available. PDF extraction, OCR and search run locally, while reusable reviewed entries support continuing study.

FuzzyProblems can be particularly useful for gathering and organising study material for **CBL (case-based learning)** and **PBL (problem-based learning)**. Students can prepare background reading, investigate learning objectives, connect foundational concepts and build revision resources for discussion sessions. Tutors and facilitators can assemble source-supported preparation materials, identify gaps and develop questions aligned with supplied case or tutorial requirements.

The workflow can be adapted across disciplines and educational levels when suitable textbooks and learning requirements are available. Applications include medicine and healthcare, science, engineering, computing, business, law, humanities and social sciences—from school and undergraduate study to postgraduate learning and professional development. Other uses include exam preparation, curriculum mapping, seminar preparation, independent learning and textbook-based background research. Researchers can organise foundational reading, compare explanations and develop a reusable evidence library while retaining the supporting sources.

**Source verification is built into the workflow.** Substantive explanations, answers and flashcards require traceable textbook support. Separate author and reviewer agents assess factual support, objective coverage, explanatory depth and educational quality. Original PDF page references, source identity checks and validation of exported content make the evidence inspectable. Missing support and conflicting sources remain explicit, and substantive changes trigger reassessment. Publication requires current review and content checks.

For people exploring NotebookLM alternatives or comparing open-source tools such as Open Notebook, FuzzyProblems offers a powerful, targeted approach to producing reviewed learning materials. Its editable workflow gives you control over learning scope, source rules, review requirements and outputs, with stronger verification controls than a source-only prompt.

The trade-off is additional AI token usage and processing time for evidence inspection, independent review and revisions; the amount depends on the task. When you need study materials with a solid, traceable path back to the original source of information, that additional verification can be well worth the cost.

---

Create source-linked study guides, practice and answers, Anki cards, and original-page evidence PDFs from your own documents. Use your own Claude Code or OpenAI Codex access. Educational facts come only from the textbooks you supply; objectives define learning requirements and past papers inform assessment style.

## Quick start: Claude Code

Extract or clone the complete project, including `.claude/`, `.agents/` and
`.codex/`. Open the **FuzzyProblems directory itself** in Claude Code (2.1.251 or
later), select your model and supported effort, then send this starter prompt:

```text
/fuzzy-start Initialize FuzzyProblems and help me supply my textbook PDFs and learning objectives, choose my study scope, and start the complete workflow.
```

The short command `/fuzzy-start` also works. Use `/job-queue` for production or
ask naturally for an objective or a complete lesson. No Codex installation,
OpenAI credentials, parent project, Git history or global project skills are needed.

## Quick start: OpenAI Codex

Open the same project root in Codex with native subagent support, select your
model and effort, then send:

```text
$fuzzy-start Initialize FuzzyProblems and help me supply my textbook PDFs and learning objectives, choose my study scope, and start the complete workflow.
```

Use `$job-queue` or a natural study-material request for production. The existing
Codex command interface and legacy delivery configuration remain supported.

## Python setup on macOS, Windows and Linux

Install Python 3.12 with `venv`, `pip` and SQLite FTS5. From the project root:

| Host | macOS / Linux | Windows PowerShell |
| --- | --- | --- |
| Claude Code | `python3.12 pipeline.py init --host claude` | `py -3.12 pipeline.py init --host claude` |
| Codex | `python3.12 pipeline.py init --host codex` | `py -3.12 pipeline.py init --host codex` |

Initialization creates a project `.venv`, installs pinned `requirements.txt` and
creates missing input/working directories and empty state. Empty input folders
are valid. Reruns preserve sources, configuration choices, checkpoints, reviews
and outputs; an explicit `--host` changes only the selected host. Omit it to keep
selection (legacy installations default to Codex). No system tools or global
account configuration are installed or changed.

Package installation uses a Python package index, or `init --wheelhouse PATH` for
local wheels. `init --no-install` checks an existing environment without downloading.
Install local Tesseract and language data for scanned PDFs. Python readiness,
OCR readiness and host capabilities are reported separately. Host authentication
is performed by the user in Claude Code or Codex, outside initialization.
See [setup and troubleshooting](foundation/guidance/SETUP.md).

Authors and reviewers inherit the selected host session's model/effort. Delivery
uses host-specific `pipeline-config.json`: Codex retains its configurable Sol
Medium default; Claude defaults to session inheritance. Unsupported settings are
reported, never silently translated between providers. See [Claude configuration](foundation/guidance/HOST_CLAUDE.md)
and [Codex configuration](foundation/guidance/HOST_CODEX.md).

## Use

Supply PDFs in the exact folders `Objectives/`, `Textbooks/` and optionally `PastPapers/`. Objectives may include outcomes, worksheets, tutorials, practical instructions and practice requirements. Tell Claude Code or Codex the learner level, which documents belong together, the requested scope and your Anki tag preferences, or delegate tag choices. Read [START_HERE.md](START_HERE.md) for onboarding and [RUNBOOK.md](RUNBOOK.md) for commands.

The default workflow uses fresh author and independent reviewer agents, then a delivery coordinator. A full lesson includes every original objective. Publication requires current educational acceptance and content/artifact checks. Open root `StudyGuide.html` after publication. HTML works locally; browser Print supports paper or PDF output. Evidence PDFs preserve cited original textbook pages. `anki.html` explains TSV import.

Organise separately published objectives in nested lesson collections using matching `build --folder` and `publish --folder` destinations. The catalogue opens a valid single objective chapter directly, including earlier versions; other guides retain their index. Publication refreshes navigation automatically. After manual folder changes, run `python regenerate_study_guide.py`; changing a guide's depth requires a new checked export to correct its textbook links. See the [publication and navigation commands](RUNBOOK.md#checked-publication-destinations).

Use only documents you are entitled to process and share. Preserve the project’s relative layout for original-source links. Inputs, working records, credentials, environments and outputs are excluded from normal commits by `.gitignore`.

## Privacy, AI processing and reusable distribution

PDF extraction, OCR, indexing, validation and export run locally. **AI authoring
and review use your selected AI provider**: prompts, excerpts, page images and
drafts read by the workers are processed by that provider. Local OCR does not
make the entire workflow local. No extra upload service, telemetry collector,
MCP server or account lookup is introduced. The Claude project configuration
opts out of nonessential host traffic and OpenTelemetry; provider/organization
policies and retention remain outside the pipeline's control.

Learner exports contain only explicitly selected educational fields and
allowlisted regular files, with neutral metadata, relative links and exact-byte
publication checks. Internal prompts, research, reviews, model settings, usage,
checkpoints and engineering records stay internal. Scholarly attribution,
original page content, citations and intentionally supplied Anki labels remain.

`FuzzyProblems/` is the authoritative standalone source. Build a reusable ZIP
with `python scripts/package_distribution.py`; the default destination is
`releases/FuzzyProblems.zip`. Its explicit [file allowlist](distribution-files.json)
includes hidden host adapters and excludes personal PDFs, packs, outputs, caches,
credentials, environments, local settings and transcripts. Never zip an entire
working project. See [distribution and platform checks](PLATFORM_SUPPORT.md).

Optional detached `queue` and CLI `review-run` commands are **Codex-only**. Claude's
normal native-worker route covers onboarding through publication without them.
Native-host smoke testing and native platform CI are distinct from synthetic
checks; tests never grant educational approval.

## Copyright, licence and disclaimer

Copyright © 2026 fuzzyproblems and the respective contributors — [github.com/fuzzyproblems](https://github.com/fuzzyproblems).

**Licence and attribution.** Except where separately identified, FuzzyProblems’ original software and associated documentation are available under the [MIT License](https://opensource.org/license/mit), to the extent that the contributors own or are authorised to license them. Personal, educational, research and commercial use, modification and redistribution are permitted subject to that licence. Copies or substantial portions of the software must retain the complete MIT licence and the copyright notice above, including the attribution to fuzzyproblems and its GitHub address. Merely running the software does not require public attribution. Independently generated outputs do not require attribution under MIT unless they incorporate material subject to its notice requirements. This notice accompanies the full MIT licence and does not replace it.

**Third-party materials and dependencies.** The project’s licence does not grant rights in third-party textbooks, papers, examination materials, source PDFs, figures, datasets, software dependencies, models or services. Their respective rights, licences and terms continue to apply, including any requirements affecting combined distributions or hosted deployments. For example, [PyMuPDF is available under AGPL or commercial licensing terms](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright); FuzzyProblems’ MIT licence does not override those obligations.

Users are responsible for establishing a lawful basis for processing, uploading, reproducing and sharing their inputs and outputs. Citation, highlighting, ownership of a document copy or educational use does not by itself establish permission to redistribute protected material. No guarantee is made concerning ownership, copyrightability or non-infringement of generated outputs.

**Educational purpose and verification limits.** FuzzyProblems supports learning, teaching and research preparation. Its outputs are not professional medical, legal, financial or other regulated advice, diagnosis or treatment. AI generation, OCR, retrieval, citations, highlighting and review processes can produce errors, omissions, unsupported conclusions and outdated information. “Reviewed”, “verified”, “source-supported” and similar descriptions refer to documented project checks, not certification, expert approval or a guarantee of correctness. Users should inspect original sources and obtain appropriate professional review before relying on outputs for consequential decisions.

**User responsibilities and external services.** Users remain responsible for their configuration, deployment, modifications, publication and use of FuzzyProblems, including applicable privacy, data-protection, copyright and academic-integrity obligations. External AI providers and other services may process submitted materials under their own terms and privacy policies and may incur charges. Users should ensure that they are authorised to transmit those materials. Making FuzzyProblems available does not endorse unlawful, harmful or misleading conduct.

**Warranty disclaimer.** TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, the software, documentation and project-provided materials are supplied “AS IS” and “AS AVAILABLE”, without express, implied or statutory warranties, including warranties of merchantability, fitness for a particular purpose, non-infringement, accuracy, completeness, security or uninterrupted operation. No maintenance, support, correction or update commitment is made unless separately agreed in writing.

**Limitation of liability.** TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, the authors, copyright holders, maintainers and contributors disclaim liability for claims, losses, damages, costs or expenses arising from use, inability to use, modification, redistribution or misuse of FuzzyProblems, or reliance on its outputs. This includes legally excludable direct, indirect, incidental and consequential losses, data loss, lost profits, business interruption and third-party claims, regardless of the legal basis of the claim or whether the possibility of loss was disclosed.

**Mandatory legal protections.** Nothing in this notice excludes or restricts rights or liability that applicable law does not permit to be excluded or restricted, including applicable mandatory consumer, product-liability and data-protection rights. Liability for fraud, intentional wrongdoing, gross negligence, death or personal injury remains unaffected wherever exclusion or limitation is prohibited. If a provision is invalid or unenforceable, the remaining provisions continue to apply to the extent permitted by law.

**No endorsement.** Attribution to fuzzyproblems identifies the project’s origin. It does not imply sponsorship, approval, certification or responsibility for any derivative project, deployment or generated material. No trademark or endorsement rights are granted. These explanatory notices do not add restrictions to the permissions granted by the MIT License.
