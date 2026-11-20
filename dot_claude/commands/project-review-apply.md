---
description: Run /project-review, then act on its report per project-review.md § Actions (file tickets, queue closures, deliver the report)
argument-hint: "[--force] [--window N]"
---

# Project Review Apply

```text
/project-review-apply               # review, then act per § Actions and § Delivery
/project-review-apply --force       # bypass the activity gate
```

The scheduled-run entry point: a scheduler's stored prompt is this command alone. All logic lives in `project-review-apply-procedure`; this session is the launcher.

Load the `project-review-apply-procedure` skill and follow it with the arguments given. In a cloud session, run the host adapter's run protocol first (`workflow/adapters/claude-cloud.md`) so the workflow tools and the `gh` shim are on `PATH`.
