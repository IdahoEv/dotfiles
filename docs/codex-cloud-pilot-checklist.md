# Codex Cloud phone-to-PR pilot checklist

Status recorded during implementation of dotfiles issue #74. These are observations from the implementation session, not a substitute for the real phone-launched pilot required by the issue's definition of done.

| Check | Result | Evidence / next step |
|---|---|---|
| Mobile launch | **Not verified** | This task was executed through ChatGPT's GitHub repository integration, not a phone-launched Codex Cloud coding task. Start one from the ChatGPT mobile app after both PRs are merged. |
| Repository access / permissions | **Partially verified** | The connected GitHub integration could read both repositories and create branches/files/PRs. This does not establish that Codex Cloud has Kardashev checkout access or credentials to push. Verify in the real cloud task. |
| Runtime workflow retrieval | **Not run** | Bootstrap is implemented to resolve `main` to a full commit SHA, fetch the workflow at that immutable SHA, validate contract markers, and fail closed. Execute it in the target Codex Cloud environment. |
| Test execution | **Not run** | The mocked bootstrap test is committed, but this session had no checked-out working tree/shell attached to the GitHub repositories, so it was not executed here. Run `bash -n tools/codex-cloud-bootstrap.sh tools/codex-cloud-bootstrap.test.sh` and `bash tools/codex-cloud-bootstrap.test.sh`; then run Kardashev's quiet Core test command in the pilot. |
| Branch / PR creation | **Partially verified** | This session successfully created review branches and open PRs via GitHub integration. Codex Cloud's own `git push` / `gh pr create` permissions and project branch conventions remain unverified in the target runtime. |
| Workflow SHA traceability | **Partially verified** | The implementation PR identifies its branch commit as `a628e74686caef3381b45493fefe8e5ec97f6050`. The bootstrap prints the exact SHA fetched from `main`; verify the real pilot's output and that same SHA in its Kardashev PR description. |

## Pilot completion rule

Do not mark issue #74 complete until one suitable, low-risk Kardashev issue has been launched from a phone, implemented in an isolated branch, checked as supported, pushed, and opened as an unmerged PR whose description and task output contain the exact fetched dotfiles workflow commit SHA.
