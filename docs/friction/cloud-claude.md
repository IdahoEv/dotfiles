# Friction: cloud-claude

Entries follow the template in [README.md](README.md). From the first full cloud run; fixed by #242.

### `gh` shim not on the agent's PATH
- What happened: `gh issue view --json ...` failed with a GraphQL 403.
- Cause: the bootstrap put the shim on PATH via `~/.bashrc`, which the agent's Bash tool never reads.
- Workaround used: project-local command copies and improvised MCP calls.
- Suggested fix: install the shim as the system `gh`, real binary kept as `gh.real`.
- Owner: dotfiles
- Status: closed (#242)

### `/land`, `/merge`, `/sync`, `/pick` marked not available
- What happened: the adapter skipped them, so the agent improvised.
- Suggested fix: run `merge-run.sh` through the shim (REST `pr merge`); `/pick` read-only with PR/branch in-flight detection.
- Owner: dotfiles
- Status: closed (#242)

### Push limited to the assigned branch
- What happened: session instructions said to push only the assigned branch; the git proxy did not enforce it.
- Suggested fix: standing owner permission in the adapter and global instructions. The instruction text itself comes from session/environment configuration.
- Owner: environment
- Status: open (remove the text at its source)

### Approval pauses and permission prompts mid-sequence
- What happened: kickoff text demanded approval before commit/push; multi-repo sessions did not read repo allow rules.
- Suggested fix: plan-gate sequence in every kickoff; bootstrap installs allow-only cloud settings.
- Owner: dotfiles
- Status: closed (#242)

### Stop hook "uncommitted changes, please commit and push"
- Cause: not in this repo or plugins; location unknown.
- Suggested fix: find it in environment/account/project settings and align it with the sequence.
- Owner: environment
- Status: open

### Epic/sub-issue lookup overflowed the tool result
- What happened: the MCP sub-issue listing returned about 376,000 characters for one epic.
- Suggested fix: `/start` does no epic lookup.
- Owner: dotfiles
- Status: closed (#242)

### Toolchain missing from the cloud image
- Suggested fix: setup script or SessionStart hook; `/pick` marks affected tickets "unverifiable here".
- Owner: environment
- Status: closed (#242, documented)

### Project-board fields cannot be set
- Cause: GraphQL is blocked and MCP has no project support.
- Suggested fix: set milestones over REST; report board fields for the owner to set.
- Owner: harness
- Status: closed (#242)
