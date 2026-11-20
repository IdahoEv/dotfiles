# Friction logs

One file per environment and backend: `local-cli-claude`, `local-gui-claude`, `mobile-claude`, `local-agy`, `cloud-claude`, `cloud-agy`, `cloud-codex`. Generic only: no project names, private repo details or work-identifying information (this repo is public).

## Entry template

```
### <short title>
- What happened:
- Where:
- Cause (if known):
- Workaround used:
- Suggested fix:
- Owner: dotfiles | project | environment | harness
- Status: open | closed (link the ticket or commit that fixed it)
```

## Triage

An entry is closed by linking the ticket or commit that fixed it. From another repo, where a session can't commit here, file a one-line intake issue titled `[<environment>] <friction>` (`/workflow` does this); the governor folds those into the matching file during triage.
