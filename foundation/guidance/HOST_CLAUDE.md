# Claude Code adapter

Open the standalone root in Claude Code **2.1.251 or later**. Run `/fuzzy-start`;
use `/job-queue` for requested production. `CLAUDE.md` routes to the shared rules.
Project skills live under `.claude/skills/`; custom workers under `.claude/agents/`.
Confirm discovery with `/agents` and the skill menu; reopen the project if missing.

For the shared [queue](JOB_QUEUE.md), explicitly choose the named custom subagent
type `fuzzy-author`, then `fuzzy-reviewer`, then `fuzzy-delivery` using Claude's
native Agent tool. Do not request the `fork` type. These custom agents have fresh
contexts, their own instruction bodies and Read/Glob/Grep/Bash/PowerShell/Write/Edit tools;
they explicitly read the shared [roles](AGENT_ROLES.md). They do not rely on
parent-loaded skills, Codex tools or `fork_turns`. Their tool lists omit delegation,
web/MCP and Skill tools; Bash remains governed by normal host permissions and the
shared ban on nested AI processes. No permission bypass is configured.

Use the shell the host exposes: Bash on macOS/Linux, PowerShell or Git Bash on
Windows. Python commands remain the same; a worker's tool allowlist includes both
shells so native Windows does not require Git Bash. See [Windows setup](https://code.claude.com/docs/en/setup).

Start only one worker at a time and wait for completion/attention. Keep the returned
agent handle internally. Use the host's supported resume/follow-up mechanism to
continue that author or reviewer after consolidated findings; never start a second
review stream in parallel. If a session/worker can no longer be resumed, start a
fresh worker of the same role with the completed checkpoint/handoff/findings and
explicitly record lost continuity. A fresh reviewer must independently establish
any judgments it cannot retain under the accepted-baseline contract.

`model: inherit` and omitted `effort` preserve session selection. Select a supported
model and effort in Claude before the queue; confirm actual exposed worker settings
once (the `/tasks` display can help). Organization policy or environment overrides
may substitute settings; disclose and resolve detected substitutions. Missing
exposure remains `unverified` in internal provenance, never an invented value.

Delivery uses `hosts.claude.delivery`, defaulting explicitly to session inheritance.
For a requested delivery override, set its model and supported effort in
`pipeline-config.json`, then run `python pipeline.py host --host claude --sync-delivery`.
Dispatch the returned `delivery_agent`. This creates only the ignored local
`fuzzy-delivery-local.md` with native model/effort fields; it leaves shipped roles
and author/reviewer selection intact. Claude's supported effort syntax is not
Codex's effort scale. Model-specific availability is confirmed by Claude itself.
Do not use a stale local worker when the returned name is `fuzzy-delivery`.

Detached `queue` and `review-run` are **Codex-only** and reject a selected Claude
host with an actionable message. The complete normal Claude route uses native
workers and the shared Python commands; it needs neither Codex nor OpenAI credentials.
If independent custom workers are unavailable, update/reopen Claude Code. The
smallest manual alternative uses a separate fresh Claude session for each role,
continuing through the same on-disk checkpoints and completed review handoff.
The reviewer receives source access and no author conversation. Preserve the same
review contract; author self-review cannot accept.

Project settings disable nonessential host traffic and OpenTelemetry. No hooks,
servers, uploads or telemetry collectors are added. Selected excerpts, page images,
prompts and drafts read by AI workers go to the configured AI provider. Extraction,
OCR and deterministic export remain local. Host/provider and organization policies
still apply; this project does not control provider retention or machine-wide tools.

References: [native worker behavior](https://code.claude.com/docs/en/sub-agents),
[skills](https://code.claude.com/docs/en/skills),
[model settings](https://code.claude.com/docs/en/model-config),
[environment controls](https://code.claude.com/docs/en/env-vars).
