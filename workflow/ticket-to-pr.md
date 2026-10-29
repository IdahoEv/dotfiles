<!-- workflow-contract: ticket-to-pr/v1 -->

# Ticket-to-PR workflow

This is the host-neutral minimum workflow. Host adapters must retrieve this committed file at task startup and preserve its source commit SHA in the final report and PR description. Project instructions remain authoritative for project-specific ticket, branch, build, test, and environment conventions.

## Required behavior

1. Require one explicit issue/ticket number from the user. Do not discover or choose work automatically.
2. Before editing, read the issue from the project's configured tracker, verify it is open/actionable, and read the repository's project instructions and kickoff guidance. If the tracker, issue, or instructions cannot be read, stop and explain the blocker.
3. Confirm the checked-out repository, base branch, and current worktree state. Work on an isolated task branch/workspace following the project's branch convention. Never edit the default branch directly; preserve unrelated existing changes.
4. Implement only the issue's scope and acceptance criteria. Keep project-specific decisions and commands in the project repository. Do not assume tools, commands, agents, hooks, or MCP integrations from another host exist.
5. Run relevant checks supported by the environment. Report each important check as passed, failed, or not run, with the reason for any unavailable check. Do not represent unavailable environment-dependent checks as passed.
6. Review the diff for scope, correctness, accidental files/secrets, and consistency with project conventions. Commit and push the task branch, then open a reviewable PR with an explicit title and a concise summary, checks, limitations, and a link to the issue where supported.
7. Include the exact `dotfiles` workflow source commit SHA supplied by the bootstrap in the PR description and completion report.
8. Stop with the PR open. Never merge it, close unrelated issues, or perform post-merge cleanup.

## Safety boundaries

- Treat the issue and project instructions as the scope authority; ask before broadening scope.
- If workflow retrieval or validation fails, stop. Do not use a cached, copied, or stale workflow.
- If repository permissions do not permit required reads, pushes, or PR creation, report the exact blocked step and leave changes unclaimed as delivered.
- Do not claim an end-to-end phone-to-PR pilot until a real phone-launched cloud task has completed the full flow.

## Completion report

Return the PR URL (if created), issue number, concise change summary, branch, workflow source repository and full commit SHA, checks run and results, unavailable checks, and any remaining pilot validation. Confirm that the PR remains open.
