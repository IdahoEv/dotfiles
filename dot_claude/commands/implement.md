# Implement Plan

You are tasked with executing a detailed implementation plan step-by-step, with automatic verification and progress tracking.

## Initial Setup

When this command is invoked, respond with:
```
I'll help you implement a plan systematically. Please provide:
1. Path to the implementation plan (e.g., docs/plans/YYYY-MM-DD-sc-XXXXX-description.md)
2. OR the Shortcut story ID and I'll search for the plan automatically

Note: This command requires an existing implementation plan created by `/create_plan`.

I'll execute each phase with automated checks and keep the plan updated.
```

Then wait for the user's input.

## Process Steps

### Step 1: Load and Parse the Plan

1. **Read the implementation plan**:
   - If given a path, read that file FULLY
   - If given story ID (sc-XXXXX), search for matching plan in `docs/plans/` with pattern `*sc-[story-id]-*.md`
   - If no plan found, prompt user to create one with `/create_plan`
   - Read the ENTIRE plan file without limit/offset
   - Parse the plan structure: phases, changes, tests, success criteria

2. **Verify plan structure**:
   - Confirm plan has phases with clear success criteria
   - Identify automated vs manual verification steps
   - Check that acceptance criteria are listed
   - Note any dependencies between phases
   - Verify plan references PRD (implementation plans built from PRDs)

3. **Present plan summary to user**:
   ```
   I've loaded the implementation plan for [Feature Name]:

   **Story**: sc-XXXXX
   **Plan**: docs/plans/[filename].md
   **PRD**: [if referenced in plan]
   **Phases**: [List phase names]
   **Total Automated Checks**: X
   **Total Manual Checks**: Y

   I'll execute each phase sequentially, running automated checks after each phase.
   Before starting, please confirm:
   - Should I proceed with all phases, or start with a specific phase?
   - Any special considerations or concerns?
   ```

### Step 2: Setup Progress Tracking

1. **Create todo list** using TodoWrite:
   - One todo per phase (use phase names as todo content)
   - Add "Verify all acceptance criteria" as final todo
   - Set all as "pending" initially

2. **Take baseline measurements**:
   ```bash
   # Get current branch and commit
   git branch --show-current
   git log -1 --oneline

   # Run baseline checks
   yarn tsc --noEmit
   yarn lint
   ```

3. **Create progress tracking comment** (if plan references Shortcut story):
   - Use `short story` to add:
   ```bash
   short story [story-id] --comment $'🤖 Implementation started by Claude Code\n\nPlan: [link to plan file]\nBranch: [current branch]\nStatus: Phase 1 of X in progress'
   ```

### Step 3: Execute Each Phase

For each phase in the plan:

1. **Mark phase as in_progress** in todo list

2. **Announce phase start**:
   ```
   ## Starting Phase [N]: [Phase Name]

   **Changes in this phase**:
   - [List key changes from plan]

   **Tests to write**:
   - [List tests from plan]
   ```

3. **Implement changes from plan**:
   - Follow the plan's specific instructions
   - Use Edit/Write tools for code changes
   - Create migrations if specified
   - Write tests alongside implementation
   - Reference similar patterns noted in plan

4. **Run automated verification** (from plan's "Automated Verification" section):
   ```bash
   # Type checking
   yarn tsc --noEmit

   # Linting
   yarn lint

   # Run specific tests for this phase
   yarn test [path from plan]

   # Database migration if applicable
   yarn db migrate
   ```

5. **Handle verification results**:
   - **If automated checks pass**:
     - Mark automated criteria as complete
     - Present manual verification steps to user
     - Wait for user confirmation

   - **If automated checks fail**:
     - Show errors clearly
     - Analyze the issue
     - Fix the problem
     - Re-run checks
     - DO NOT proceed to next phase until checks pass

6. **Present manual verification checklist**:
   ```
   ✅ Automated checks passed for Phase [N]

   **Manual verification required**:
   - [ ] [Manual check 1 from plan]
   - [ ] [Manual check 2 from plan]
   - [ ] Feature works as expected

   Please test these manually and confirm when ready to proceed.
   Type "continue" to move to next phase, or describe any issues found.
   ```

7. **Wait for user approval** before proceeding to next phase

8. **Mark phase as completed** in todo list

9. **Update Shortcut** (if story referenced):
   ```bash
   short story [story-id] --comment $'Phase [N] of X complete\n- ✅ [Key accomplishment]\n- ✅ Tests passing\n- ⏳ Manual verification pending'
   ```

### Step 4: Final Verification

After all phases complete:

1. **Run comprehensive checks**:
   ```bash
   # Full type check
   yarn tsc --noEmit

   # Full lint check
   yarn lint

   # Run all related tests
   yarn test [paths for this feature]

   # Verify build works
   yarn build
   ```

2. **Verify acceptance criteria**:
   - Read acceptance criteria from plan
   - Check each criterion against implementation
   - Present checklist to user:
   ```
   ## Acceptance Criteria Verification

   From Shortcut story sc-XXXXX:
   - [ ] AC1: [criterion text] - [How to verify]
   - [ ] AC2: [criterion text] - [How to verify]
   - [ ] AC3: [criterion text] - [How to verify]

   Please verify each criterion is met.
   ```

3. **Create implementation summary**:
   ```
   ## Implementation Complete: [Feature Name]

   **Phases Completed**: X of X
   **Files Changed**: [count and key files]
   **Tests Added**: [count and test files]
   **Migrations**: [if applicable]

   **Automated Verification**:
   ✅ TypeScript compilation clean
   ✅ Linting passed
   ✅ All tests passing
   ✅ Build successful

   **Manual Verification**:
   - All acceptance criteria verified
   - Feature tested in [environment]
   - No regressions found

   **Next Steps**:
   1. Commit changes: [suggest commit message]
   2. Create PR referencing sc-XXXXX
   3. Link implementation plan in PR description
   ```

4. **Update implementation plan file**:
   - Mark all checkboxes as complete
   - Add completion timestamp
   - Note any deviations from original plan

5. **Update Shortcut story** (if applicable):
   ```bash
   short story [story-id] --comment $'✅ Implementation complete\n\nAll phases executed successfully:\n- [Phase 1 summary]\n- [Phase 2 summary]\n- [Phase 3 summary]\n\nAutomated checks: ✅ All passing\nAcceptance criteria: ✅ All verified\n\nReady for PR review.'
   ```

### Step 5: Handle Issues and Blockers

If issues arise during implementation:

1. **Document the issue**:
   - Describe what went wrong
   - Show error messages
   - Note which phase it occurred in

2. **Attempt to resolve**:
   - Research similar issues in codebase
   - Check if plan needs adjustment
   - Fix and retry

3. **If blocked**:
   - Mark current phase as in_progress (not completed)
   - Update Shortcut with blocker details
   - Present options to user:
     ```
     🚫 Blocked on Phase [N]: [Phase Name]

     **Issue**: [Clear description]

     **Options**:
     1. I can research alternative approaches
     2. Skip this phase and continue (not recommended)
     3. Pause here for clarification

     What would you like to do?
     ```

## Important Guidelines

1. **Never skip automated checks**:
   - Always run type checking after code changes
   - Always run linting
   - Always run relevant tests
   - Do not proceed if checks fail

2. **Respect phase boundaries**:
   - Complete one phase fully before starting next
   - Don't mix changes from different phases
   - Each phase should be independently verifiable

3. **Keep plan and todos in sync**:
   - Update todos immediately after completing phase
   - Mark plan checkboxes as you go
   - Update Shortcut regularly

4. **Test alongside implementation**:
   - Write tests in the same phase as the feature
   - Follow test patterns from plan
   - Use factories from `src/tests/factories/`
   - Follow AAA pattern (Arrange, Act, Assert)

5. **Communicate progress**:
   - Keep user informed of current phase
   - Show what's happening during long operations
   - Present clear verification checklists
   - Wait for user approval at phase boundaries

6. **Handle uncertainty**:
   - If plan is ambiguous, ask for clarification
   - If approach isn't working, research alternatives
   - If stuck, present options to user
   - Never guess or make assumptions about requirements

## Recovery and Error Handling

### If implementation fails mid-phase:
1. Note exact point of failure
2. Show error messages
3. Attempt to fix automatically
4. If can't fix, ask for guidance
5. Update todos to reflect current state

### If tests fail:
1. Show failing test output
2. Analyze the failure
3. Fix the issue
4. Re-run tests
5. Don't proceed until green

### If user wants to pause:
1. Mark current phase status clearly
2. Update Shortcut with current state
3. Provide resume instructions:
   ```
   Paused during Phase [N]: [Phase Name]

   To resume: `/implement docs/plans/[plan-file]`

   Current state:
   - [What's been completed]
   - [What's in progress]
   - [What remains]
   ```

## Integration with Other Tools

### With Shortcut:
- Get story context from implementation plan (which references PRD)
- Add progress comments to story using `short story [id] --comment "message"`
- Add external links using `short api /stories/[id]/links -X POST -f url="url"`
- Link plan and PR when done
- **DO NOT fetch stories directly** - context flows from PRD → Plan → Implementation
- **Note**: Short CLI has limited functionality for adding comments and links

### With Git:
- Track current branch
- Suggest commit messages based on phases
- Note files changed
- Prepare for PR creation

### With Testing:
- Run focused tests during development
- Run full suite at end
- Use factories for test data
- Follow testing guidelines

## Success Criteria for Implementation

**Implementation is complete when**:
- ✅ All phases executed successfully
- ✅ All automated checks passing
- ✅ All manual verifications confirmed
- ✅ All acceptance criteria met
- ✅ Plan file updated with completion
- ✅ Shortcut story updated
- ✅ No regressions introduced
- ✅ Code follows established patterns

## Example Interaction Flow

```
User: /implement docs/plans/2025-10-01-sc-12345-add-filtering.md