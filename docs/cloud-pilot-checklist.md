# Cloud workflow pilot checklist (Codex Cloud)

Results from the real phone-launched pilot required by issue #74. Fill in each row from the actual run; source-control tests do not count.

| Check | Result | Evidence |
| --- | --- | --- |
| Mobile launch | Not run | |
| Outbound HTTPS to `api.github.com` and `codeload.github.com` in the agent phase | Not run | If blocked, move the fetch to a setup script and update the bootstrap docs. |
| Repository access and push/PR credentials | Not run | |
| Tarball retrieval at a recorded SHA | Not run | |
| `/start` and `/open-pr` executed from the fetched command files | Not run | Note any step the adapter had to stop on. |
| Test execution | Mocked suites pass locally (`tools/cloud-workflow-bootstrap.test.sh`, `tools/cloud-workflow-adapter.test.sh`); project checks in the cloud task: Not run | |
| Branch / PR creation | Not run | |
| Workflow SHA traceability | Not run | Same SHA in task output and PR body. |

## Completion rule

Issue #74 is complete when one low-risk issue in the target project has been launched from a phone, implemented on an isolated branch, checked as supported, pushed, and opened as an unmerged PR whose description and task output contain the fetched dotfiles commit SHA.
