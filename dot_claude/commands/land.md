# Land the PR: merge, then finalize

The normal end of a workstream. Sequences two commands and adds no logic of its own. Run
from the PR's worktree.

1. Follow `merge.md` in full (`merge-run.sh` and its exit-code handling), except its
   exit-0 "Stop": here a merge continues to step 2.
2. **Merged** (exit 0): follow `finalize.md` in full. It removes this worktree and ends the
   session, so relay the `merge-run.sh` line first, then run it.
3. **Not merged** (any other exit): relay the stop reason as `merge.md` directs and stop.
   Do not run `/finalize`.
