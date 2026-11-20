# Friction: opencode-local

Entries follow the template in [README.md](README.md).

### Built-in general subagent cannot delegate
- What happened: a review-cycle manager launched as the built-in `general` subagent received no subagent tool, so reviewer fan-out was impossible and the cycle stopped with independent review not performed.
- Where: local OpenCode TUI session on the shared background server (v2.3.2).
- Cause (if known): the built-in `general` agent is documented as unable to launch further subagents; `experimental.subagent_depth: 2` does not lift that restriction.
- Workaround used: custom `workflow-manager` agent (mode `all`, `subagent` permission allow) in global `opencode.json`; adapter updated to require a delegation-capable manager agent.
- Suggested fix: deploy OpenCode config and agents through chezmoi so every machine gets the delegation-capable manager agent.
- Owner: dotfiles
- Status: open

### Subagents have no question tool
- What happened: the manager subagent's tool catalog had no question tool, so approval checkpoints inside a child session cannot prompt the user directly.
- Where: local OpenCode TUI session (v2.3.2).
- Cause (if known): child sessions appear to exclude interactive user-input tools by design.
- Workaround used: adapter routes decisions up — the subagent reports the required decision to the parent, which asks via the question tool.
- Suggested fix: none needed if the parent-asks mapping holds; revisit if unattended child runs need mid-run approvals.
- Owner: harness
- Status: open
