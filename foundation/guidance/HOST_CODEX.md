# Codex adapter

Open the standalone root. `$fuzzy-start` initializes with `--host codex`;
`$job-queue` uses the shared [queue](JOB_QUEUE.md) and [roles](AGENT_ROLES.md).
Codex discovers `.agents/skills/` and `.codex/agents/*.toml`. No desktop-private
tools or global project skills are required.

Use named project roles when the host offers them. With a generic native spawn
tool, assign the shared role explicitly and use `fork_turns="none"` only when
that parameter is exposed, omitting model/effort overrides for author/reviewer
inheritance. The current desktop API supports this combination. Do not assume
another CLI build has the same tool schema: inspect its exposed tool once. Keep
one worker active and continue the same author/reviewer for revisions.

`python pipeline.py host --host codex` resolves delivery settings. Existing
top-level `delivery` configurations remain Codex settings; new configurations use
`hosts.codex.delivery`. Default delivery remains `gpt-6-sol` / `medium`. Dispatch
a fresh delivery worker with that explicit supported pair (or the user's override).
If the host cannot apply it, resolve the capability/configuration limitation; do
not silently change models. No model tier minimum is imposed.

The optional `review-run` and detached `queue` commands use the public Codex CLI,
with explicit model/effort, workspace-write sandbox and `--skip-git-repo-check`.
Use them only when requested. `CODEX_CLI_PATH` / `--cli` is a runtime executable
choice; new queue state does not store machine paths. Existing queue state remains
readable. CLI settings are requested provenance, not proof of actual runtime.

References: [subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents),
[skills](https://learn.chatgpt.com/docs/build-skills),
[noninteractive CLI](https://learn.chatgpt.com/docs/non-interactive-mode).
Tool and flag availability must also match the installed host.
