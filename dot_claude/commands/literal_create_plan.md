# Create Implementation Plan

You are tasked with creating detailed implementation plans through an interactive, iterative process. You should be thorough, use existing agents for research, and work collaboratively with the user to produce high-quality technical specifications that align with Pulse's architecture and testing practices.

## Initial Response

When this command is invoked:

1. **Parse parameters from user input**:
   - Look at the ACTUAL text provided by the user after the command
   - Extract story ID(s) from the user's message (NOT from examples in this document)
   - Story IDs can be formatted as:
     - "sc-55337" (with prefix)
     - "55337" (just the number)
   - Strip any "sc-" prefix and use just the numeric ID

2. **Check for existing PRD first**:
   - Search for PRD in `docs/prds/` matching pattern `*sc-[story-id]-*.md`
   - If PRD exists, read it FULLY and proceed with planning
   - If no PRD exists, prompt user to create one first

3. **If no parameters provided**, respond with:
```
I'll help you create a detailed implementation plan. Let me start by understanding what we're building.

Please provide the Shortcut story ID (e.g., sc-XXXXX or XXXXX).

Note: This command expects a PRD to exist first. If you haven't created one yet, run:
`/generate_prd XXXXX`

Tip: You can invoke with: `/create_plan XXXXX`
```

Then wait for the user's input.

4. **If story ID provided but no PRD exists**, respond with:
```
I couldn't find a PRD for story sc-XXXXX in docs/prds/.

Please create a PRD first using:
`/generate_prd XXXXX`

The PRD provides essential context and research needed for effective planning.
```

Then stop and wait.

## Process Steps

### Step 1: Load PRD and Extract Context

1. **Read the PRD file FULLY**:
   - PRD should exist in `docs/prds/` with pattern `*sc-[story-id]-*.md`
   - Read entire PRD without limit/offset parameters
   - Extract all story context already gathered:
     - Story description and acceptance criteria
     - Research findings and relevant codebase areas
     - Similar implementations and patterns
     - Technical context and constraints
     - Expected test coverage

2. **Read any additional referenced files FULLY**:
   - Related implementation plans in docs/plans/
   - Research documents referenced in PRD
   - **IMPORTANT**: Use Read tool WITHOUT limit/offset parameters to read entire files

3. **Verify PRD completeness and spawn additional research if needed**:
   - Check if PRD has all necessary context from `/generate_prd`
   - If additional research needed beyond PRD, spawn focused tasks:
     - Use **codebase-analyzer** to deepen understanding of specific areas
     - Use **codebase-pattern-finder** to find additional implementation examples
   - Read any new files identified by additional research FULLY

4. **Analyze and verify understanding**:
   - Cross-reference PRD story requirements with actual code
   - Identify any discrepancies or ambiguities
   - Note assumptions that need verification
   - Determine true scope based on codebase reality and PRD guidance

5. **Present informed understanding and focused questions**:
   ```
   Based on the PRD and my analysis, I understand we need to [accurate summary].

   **From PRD:**
   - Story: sc-12345
   - Type: Feature/Bug/Chore
   - Team: [Team name]
   - Key codebase areas: [from PRD research]
   - Similar implementations: [from PRD]

   **Additional findings:**
   - [Any new discovery with file:line reference]
   - [Relevant pattern or constraint]

   **Questions requiring clarification:**
   - [Specific technical question requiring human judgment]
   - [Business logic clarification]
   - [Design preference that affects implementation]
   ```

   Only ask questions that genuinely cannot be answered through PRD or code investigation.

### Step 2: Design & Options Development

After getting initial clarifications:

1. **If the user corrects any misunderstanding**:
   - DO NOT just accept the correction
   - Verify against PRD or spawn research tasks
   - Read the specific files/directories they mention
   - Only proceed once you've verified the facts yourself

2. **Create a planning todo list** using TodoWrite to track planning tasks

3. **Leverage PRD research findings**:
   - Use codebase areas already identified in PRD
   - Reference similar implementations documented in PRD
   - Build on technical context from PRD
   - Only spawn new research tasks if PRD gaps exist

4. **If additional research needed**:
   - Create focused Task agents for specific gaps:
     - **codebase-analyzer** - Understand specific implementation details
     - **codebase-pattern-finder** - Find additional examples if needed
   - Wait for ALL sub-tasks to complete before proceeding

5. **Present findings and design options**:
   ```
   Based on the PRD and my analysis, here's what I found:

   **From PRD Research:**
   - [Key codebase areas documented in PRD]
   - [Pattern or convention identified in PRD]
   - [Database schema/tables involved]

   **Similar Features (from PRD):**
   - [Feature X] at [file:line] - [pattern to follow]
   - [Feature Y] at [file:line] - [similar approach]

   **Design Options:**
   1. [Option A] - Follow pattern from [existing feature documented in PRD]
      - Pros: [benefits]
      - Cons: [tradeoffs]
   2. [Option B] - Alternative approach
      - Pros: [benefits]
      - Cons: [tradeoffs]

   **Open Questions:**
   - [Technical uncertainty requiring decision]
   - [Design choice needed]

   Which approach aligns best with your vision?
   ```

### Step 3: Plan Structure Development

Once aligned on approach:

1. **Create initial plan outline**:
   ```
   Here's my proposed plan structure:

   ## Overview
   [1-2 sentence summary aligned with Shortcut story]

   ## Implementation Phases:
   1. [Phase name] - [what it accomplishes]
   2. [Phase name] - [what it accomplishes]
   3. [Phase name] - [what it accomplishes]

   Each phase will include:
   - Specific code changes with file paths
   - Automated verification steps (yarn test, yarn tsc, etc.)
   - Manual testing steps from acceptance criteria

   Does this phasing make sense? Should I adjust the order or granularity?
   ```

2. **Get feedback on structure** before writing details

### Step 4: Detailed Plan Writing

After structure approval:

1. **Write the plan** to `docs/plans/YYYY-MM-DD-sc-XXXX-description.md`
   - Format: `YYYY-MM-DD-sc-XXXX-description.md` where:
     - YYYY-MM-DD is today's date
     - sc-XXXX is the Shortcut story ID (omit if no story)
     - description is a brief kebab-case description
   - Examples:
     - With story: `2025-10-01-sc-12345-parent-child-tracking.md`
     - Without story: `2025-10-01-improve-error-handling.md`

2. **Use this template structure**:

````markdown
# [Feature/Task Name] Implementation Plan

**Story**: [sc-XXXX](https://app.shortcut.com/wellth/story/XXXX) | **Type**: [Feature/Bug/Chore] | **Team**: [Team Name]

## Overview

[Brief description from Shortcut story of what we're implementing and why]

## Story Context

### Description
[Original Shortcut story description - complete and unmodified]

### Acceptance Criteria
[Exact acceptance criteria from Shortcut - these are the success targets]
- [ ] AC1: [Exact text from Shortcut]
- [ ] AC2: [Exact text from Shortcut]
- [ ] AC3: [Exact text from Shortcut]

### Story Tasks (from Shortcut)
[Any existing tasks defined in the Shortcut story]
- [ ] Task 1: [From Shortcut]
- [ ] Task 2: [From Shortcut]

## Current State Analysis

### What Exists Now
[What exists, what's missing, key constraints discovered]

### Key Files to Review First
- `path/to/file.ts:123` - [What to understand here]
- `path/to/another.ts:45` - [Related logic]

### Similar Features
- [Feature X] at `path/to/example.ts:89` - [Pattern to follow]
- [Feature Y] at `path/to/another-example.ts:234` - [Test pattern]

### Key Discoveries
- [Important finding with file:line reference]
- [Pattern to follow]
- [Constraint to work within]

## Desired End State

[Specification of desired state after plan is complete, and how to verify it]

## What We're NOT Doing

[Explicitly list out-of-scope items to prevent scope creep]

## Implementation Approach

[High-level strategy and reasoning, referencing similar patterns found in codebase]

## Phase 1: [Descriptive Name]

### Overview
[What this phase accomplishes]

### Changes Required

#### 1. [Component/File Group]
**File**: `path/to/file.ts`
**Changes**: [Summary of changes]
**Pattern Reference**: Based on `similar/file.ts:123`

```typescript
// Specific code to add/modify
// Reference existing pattern from [file:line]
```

#### 2. [Database Changes]
**Migration**: `migrations/XXXX_description.sql`
**Schema**: `src/db/schema/table_name.ts`

```sql
-- Migration SQL
```

### Testing Strategy for Phase 1

#### Unit Tests
**File**: `src/tests/[component]/[name].test.ts`
**Pattern**: Follow pattern from `src/tests/[similar]/example.test.ts`

```typescript
// Test structure following existing patterns
describe('ComponentName', () => {
  // Use factories from src/tests/factories/
  // Follow AAA pattern (Arrange, Act, Assert)
});
```

#### Integration Tests
**File**: `src/tests/apps/pulse-api/handlers/[name].test.ts`

```typescript
// API integration test using supertest
// Follow pattern from existing handler tests
```

### Success Criteria

#### Automated Verification
- [ ] Migration applies cleanly: `yarn db migrate`
- [ ] TypeScript compiles: `yarn tsc --noEmit`
- [ ] Unit tests pass: `yarn test src/tests/[specific path]`
- [ ] Integration tests pass: `yarn test src/tests/apps/[specific path]`
- [ ] Linting passes: `yarn lint`

#### Manual Verification
- [ ] [Acceptance criterion 1 verification steps]
- [ ] [Acceptance criterion 2 verification steps]
- [ ] Feature works as expected in UI/API
- [ ] No regressions in related features

---

## Phase 2: [Descriptive Name]

[Similar structure with automated and manual success criteria]

---

## Testing Strategy Summary

### Test Files to Create/Update
- `src/tests/repositories/[name]_repository.test.ts` - Repository tests
- `src/tests/services/[name]_service.test.ts` - Service tests
- `src/tests/apps/pulse-api/handlers/[name].test.ts` - API tests

### Factories Needed
- `src/tests/factories/[name]_factory.ts` - Test data factory using Fishery

### Test Coverage Requirements
- Unit tests for all new services and repositories
- Integration tests for API endpoints
- Edge cases: [List specific edge cases to test]
- Error scenarios: [List error cases to test]

### Testing Commands
```bash
# Run all related tests
yarn test src/tests/[component]

# Run specific test file
yarn test src/tests/[specific-file].test.ts

# Watch mode during development
yarn test --watch src/tests/[component]
```

## Performance Considerations

[Any performance implications or optimizations needed]

## Database Migration Notes

[How to handle existing data, rollback strategy, data transformations]

## Deployment Considerations

- Environment variables needed: [List any new env vars]
- Feature flags: [Any feature flags to use]
- Rollback plan: [How to rollback if needed]

## References

- **Shortcut Story**: [sc-XXXX](https://app.shortcut.com/wellth/story/XXXX)
- **Related Stories**: [Links to related Shortcut stories]
- **Similar Implementation**: `[file:line]` - [Description]
- **Test Pattern**: `[test-file:line]` - [Test to follow]
- **Documentation**: [Links to relevant docs]
````

### Step 5: Review and Iterate

1. **Present the draft plan location**:
   ```
   I've created the implementation plan at:
   `docs/plans/YYYY-MM-DD-sc-XXXX-description.md`

   The plan includes:
   - All acceptance criteria from the Shortcut story
   - Specific file paths and line numbers for reference
   - Automated verification steps using yarn commands
   - Manual testing steps aligned with acceptance criteria
   - Test strategy following our testing guidelines

   Please review and let me know:
   - Are the phases properly scoped?
   - Are the success criteria specific enough?
   - Any technical details that need adjustment?
   - Missing edge cases or considerations?
   ```

2. **Iterate based on feedback** - be ready to:
   - Add missing phases
   - Adjust technical approach
   - Clarify success criteria (both automated and manual)
   - Add/remove scope items
   - Include more test cases

3. **Continue refining** until the user is satisfied

4. **Update Shortcut story** (if appropriate):
   ```
   Would you like me to add a link to this implementation plan to the Shortcut story using `short api`?
   ```

## Important Guidelines

1. **Be Thorough**:
   - Read Shortcut stories COMPLETELY before planning
   - Research actual code patterns using parallel sub-tasks
   - Include specific file paths and line numbers
   - Write measurable success criteria with automated vs manual distinction
   - Reference similar features found in the codebase

2. **Be Interactive**:
   - Don't write the full plan in one shot
   - Get buy-in at each major step
   - Allow course corrections
   - Work collaboratively

3. **Be Practical**:
   - Focus on incremental, testable changes
   - Follow existing patterns found in the codebase
   - Consider migration and rollback
   - Think about edge cases
   - Include comprehensive test strategy

4. **Track Progress**:
   - Use TodoWrite to track planning tasks
   - Update todos as you complete research
   - Mark planning tasks complete when done

5. **No Open Questions in Final Plan**:
   - If you encounter open questions during planning, STOP
   - Research or ask for clarification immediately
   - Do NOT write the plan with unresolved questions
   - Every decision must be made before finalizing the plan

6. **Follow Testing Guidelines**:
   - Reference `docs/testing-guidelines.md` for test patterns
   - Use factories from `src/tests/factories/`
   - Follow AAA pattern (Arrange, Act, Assert)
   - Include both unit and integration tests
   - Test edge cases and error scenarios

## Success Criteria Guidelines

**Always separate success criteria into two categories:**

1. **Automated Verification** (can be run during development):
   - Commands using `yarn`: `yarn test`, `yarn lint`, `yarn tsc --noEmit`
   - Specific test files that should pass
   - Database migrations that should run
   - Build commands that should succeed

2. **Manual Verification** (requires human testing):
   - UI/UX functionality from acceptance criteria
   - Performance under real conditions
   - Edge cases from acceptance criteria
   - User acceptance criteria from Shortcut

**Format example:**
```markdown
### Success Criteria

#### Automated Verification
- [ ] TypeScript compiles: `yarn tsc --noEmit`
- [ ] Unit tests pass: `yarn test src/tests/services/candidate-service.test.ts`
- [ ] Integration tests pass: `yarn test src/tests/apps/pulse-api/handlers/`
- [ ] Linting passes: `yarn lint`
- [ ] Database migration runs: `yarn db migrate`

#### Manual Verification
- [ ] [Exact acceptance criterion 1 from Shortcut]
- [ ] [Exact acceptance criterion 2 from Shortcut]
- [ ] Feature works correctly via UI
- [ ] No regressions in [specific related feature]
```

## Pulse-Specific Patterns

### For Database Changes
1. Create migration in `migrations/`
2. Update schema in `src/db/schema/`
3. Add/update repository in `src/repositories/`
4. Update service in `src/services/`
5. Expose via API in `src/apps/pulse-api/`
6. Add tests at each layer

### For New Features
1. Research existing patterns first using agents
2. Start with data model (database schema)
3. Build repository layer (data access)
4. Implement service layer (business logic)
5. Add API endpoints (routes + handlers)
6. Implement frontend (if applicable)
7. Comprehensive tests at each layer

### For Bug Fixes
1. Document current behavior with file:line references
2. Identify root cause through research
3. Find similar fixes in codebase
4. Plan fix with test to prevent regression
5. Verify no unintended side effects

## Sub-task Spawning Best Practices

When spawning research sub-tasks:

1. **Spawn multiple tasks in parallel** for efficiency
2. **Each task should be focused** on a specific area
3. **Provide detailed instructions** including:
   - Exactly what to search for
   - Which directories to focus on (src/services/, src/repositories/, etc.)
   - What information to extract
   - Expected output format with file:line references
4. **Specify tools to use**: Read, Grep, Glob, Bash
5. **Request specific file:line references** in responses
6. **Wait for all tasks to complete** before synthesizing
7. **Verify sub-task results**:
   - If unexpected results, spawn follow-up tasks
   - Cross-check findings against actual codebase
   - Don't accept results that seem incorrect

## Shortcut Integration

### Story Information Source
**DO NOT fetch stories directly** - all story context should come from the PRD created by `/generate_prd`.

The PRD contains:
- Complete story description and acceptance criteria
- All story comments and context
- Research findings about relevant codebase areas
- Similar implementations to follow

### Linking Plans to Stories
```bash
# Add plan link to story
short api /stories/12345/links -X POST -f url="https://github.com/wellth/pulse/blob/main/docs/plans/2025-10-01-sc-12345-feature.md"
```

## Example Interaction Flow

```
User: /create_plan 12345