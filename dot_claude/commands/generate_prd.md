# Generate PRD

You are tasked with transforming a Shortcut story into an agent-optimized Product Requirements Document (PRD) that maximizes Claude Code's success in planning and implementing features.

## Initial Response

When this command is invoked:

1. **Parse parameters from user input**:
   - Look for Shortcut story ID in user's message
   - Story IDs can be: "sc-55337" or "55337"
   - Strip "sc-" prefix and use numeric ID

2. **If story ID provided**, respond with:
```
I'll generate an agent-optimized PRD for Shortcut story sc-[XXXXX].

Analyzing the story and researching relevant codebase areas...
```

3. **If no story ID provided**, respond with:
```
I'll help you create a PRD from a Shortcut story.

Please provide the Shortcut story ID (e.g., sc-XXXXX or XXXXX).

Tip: You can invoke with: `/generate_prd XXXXX`
```

Then wait for story ID.

## Process Steps

### Step 1: Fetch and Analyze Story

1. **Fetch complete story details**:
   ```bash
   short story [story-id]
   ```
   Parse the output to extract story information.

2. **Extract all story information**:
   - Story ID, name, type, team
   - Complete description
   - All acceptance criteria (tasks marked as acceptance criteria)
   - All comments (especially technical clarifications)
   - Story tasks
   - Labels, iteration, epic
   - Owner and requesters

3. **Present story summary**:
   ```
   ## Story Overview: sc-XXXXX

   **Title**: [Story name]
   **Type**: [Feature/Bug/Chore]
   **Team**: [Team name]
   **Status**: [Current state]

   **Description Summary**:
   [First 2-3 sentences]

   **Acceptance Criteria** ([count] total):
   - [First AC]
   - [Second AC]
   ...

   I'll now research the codebase to identify relevant areas for implementation.
   ```

### Step 2: Research Relevant Codebase Areas

**CRITICAL**: Spawn research agents in PARALLEL to gather context efficiently.

1. **Create research todo list** using TodoWrite:
   - "Locate relevant files and directories"
   - "Analyze similar implementations"
   - "Find test patterns to follow"
   - "Identify database schemas involved"

2. **Spawn parallel research tasks**:

   Use Task tool with these agents running SIMULTANEOUSLY:

   **Task 1 - codebase-locator**:
   ```
   Find all files related to [feature/component from story].

   Focus on:
   - Services in src/services/
   - Repositories in src/repositories/
   - API routes in src/apps/pulse-api/
   - Database schemas in src/db/schema/
   - Existing tests

   Return organized list of file paths grouped by purpose.
   ```

   **Task 2 - codebase-pattern-finder**:
   ```
   Find similar implementations to [feature from story].

   Look for:
   - Similar features we can model after
   - Patterns for [specific technical aspect]
   - Test patterns for this type of feature
   - Common utilities or helpers used

   Return concrete code examples with file:line references.
   ```

   **Task 3 - codebase-analyzer**:
   ```
   Analyze how [related feature/system] currently works.

   Understand:
   - Data flow and transformations
   - Integration points
   - Validation and error handling
   - Database operations

   Return detailed explanation with file:line references.
   ```

3. **Wait for ALL research tasks to complete**

4. **Synthesize research findings**:
   ```
   ## Research Findings

   **Relevant Files Identified**:
   - src/services/[service].ts - [purpose]
   - src/repositories/[repo].ts - [purpose]
   - src/db/schema/[schema].ts - [database tables]

   **Similar Implementations**:
   - [Feature X] at src/[path]:123 - [pattern we can follow]
   - [Feature Y] at src/[path]:456 - [test pattern]

   **Current Architecture**:
   - [Key understanding about how system works]
   - [Integration points discovered]
   - [Constraints to work within]
   ```

### Step 3: Generate PRD Using Template

1. **Read PRD template**:
   - Read `docs/prd-template.md` FULLY (no limit/offset)

2. **Fill out PRD sections** based on template structure:

   **Story Context Section**:
   - Copy description verbatim from Shortcut
   - List all acceptance criteria exactly as written
   - Include relevant comments from Shortcut
   - Note any existing story tasks

   **Agent Guidance Section**:
   - List codebase areas from research (step 2)
   - Specify key files to review with explanations
   - Document business logic constraints from story
   - Define expected test coverage based on testing guidelines

   **Success Metrics Section**:
   - Planning phase checklist
   - Implementation complete checklist
   - Reference testing guidelines for test requirements

   **Technical Context Section**:
   - Database changes (if applicable)
   - API changes (if applicable)
   - Dependencies & integrations from research
   - Risk areas identified during research

3. **Ask clarifying questions** if needed:
   ```
   I need clarification on a few points before finalizing the PRD:

   1. [Specific ambiguity in acceptance criteria]
   2. [Technical approach uncertainty]
   3. [Scope clarification needed]

   Please provide guidance on these points.
   ```

### Step 4: Create PRD File

1. **Generate filename**:
   - Format: `docs/prds/YYYY-MM-DD-sc-XXXXX-description.md`
   - Use today's date
   - Use story ID
   - Create brief kebab-case description from story name

2. **Write PRD file** with complete content:
   ```markdown
   # PRD: [Story Name]

   **Story**: [sc-XXXXX](https://app.shortcut.com/wellth/story/XXXXX) | **Type**: [Type] | **Team**: [Team]

   ## Story Context

   ### Description
   [Original Shortcut description - complete and unmodified]

   ### Acceptance Criteria
   - [ ] AC1: [Exact text from Shortcut]
   - [ ] AC2: [Exact text from Shortcut]
   ...

   ### Comments & Context
   [Key comments from Shortcut providing insights]

   ### Story Tasks (from Shortcut)
   - [ ] Task 1: [From Shortcut]
   - [ ] Task 2: [From Shortcut]

   ## Agent Guidance

   ### Codebase Areas to Explore First
   [From research findings]
   - `src/services/[name]/` - [Why relevant]
   - `src/repositories/[name]/` - [What logic here]
   - `src/db/schema/[name]` - [What data models]

   ### Key Files to Review
   [Specific files from research]
   - `path/to/file.ts:123` - [What to understand]
   - `path/to/similar.ts:456` - [Pattern to follow]
   - `path/to/test.test.ts:789` - [Test pattern]

   ### Business Logic Constraints
   [From story description and comments]
   - Constraint 1: [Specific rule]
   - Constraint 2: [Specific rule]

   ### Expected Test Coverage
   [Based on testing-guidelines.md]
   - **Unit Tests**: [Specific functions to test]
   - **Integration Tests**: [API endpoints to test]
   - **Edge Cases**: [Error scenarios to cover]

   ## Success Metrics for Agent

   ### Planning Phase Complete When:
   - [ ] Story requirements fully understood
   - [ ] Relevant existing code explored
   - [ ] Implementation approach defined
   - [ ] Test strategy outlined
   - [ ] Breaking changes identified

   ### Implementation Complete When:
   - [ ] All acceptance criteria met
   - [ ] Comprehensive tests passing
   - [ ] TypeScript compilation clean
   - [ ] Linting passes
   - [ ] No regressions
   - [ ] Follows established patterns

   ## Technical Context

   ### Database Changes Required
   [From research or story]
   - Schema changes: [Details]
   - Migrations needed: [Details]

   ### API Changes
   [From story or research]
   - New endpoints: [Details]
   - Modified responses: [Details]
   - Breaking changes: [None/Details]

   ### Dependencies & Integrations
   [From research]
   - External services: [List]
   - Internal services: [List]
   - Shared components: [List]

   ### Risk Areas
   [From research findings]
   - [Specific area to be careful with]
   - [Potential breaking changes]
   ```

3. **Save PRD file** using Write tool

### Step 5: Link PRD to Shortcut

1. **Add external link to Shortcut story**:
   ```bash
   short api /stories/[story-id]/links -X POST -f url="https://github.com/wellth/pulse/blob/development/docs/prds/[filename].md"
   ```

2. **Add comment to Shortcut story**:
   ```bash
   short story [story-id] --comment $'📋 PRD generated: [link to PRD]\n\nReady for implementation planning with `/create_plan`'
   ```

### Step 6: Present PRD to User

```
✅ PRD Generated: [Story Name]

**Location**: `docs/prds/YYYY-MM-DD-sc-XXXXX-description.md`

**PRD includes**:
- Complete story context with all acceptance criteria
- [X] relevant codebase areas identified
- [Y] similar implementations documented
- Technical context and constraints
- Comprehensive test strategy
- Success metrics for planning and implementation

**Shortcut Story Updated**:
- ✅ PRD linked to story
- ✅ Comment added with PRD location

**Next Steps**:
1. Review the PRD for accuracy and completeness
2. Use `/create_plan sc-XXXXX` to create implementation plan
3. Or provide feedback for PRD adjustments

Would you like me to create the implementation plan now?
```

## Important Guidelines

1. **Be thorough with story analysis**:
   - Read complete story including all comments
   - Extract acceptance criteria carefully
   - Note any ambiguities or questions

2. **Research efficiently**:
   - Use parallel agents for research
   - Wait for all research to complete
   - Synthesize findings before writing PRD

3. **Follow PRD template exactly**:
   - Read template fully before generating
   - Include all sections
   - Use exact markdown formatting
   - Provide concrete, actionable guidance

4. **Make PRD agent-ready**:
   - Specific file paths, not general directions
   - Concrete examples from research
   - Clear constraints and requirements
   - Measurable success criteria

5. **Keep Shortcut in sync**:
   - Link PRD to story
   - Add helpful comments
   - Make it easy to find PRD from story

## PRD Quality Checklist

Before presenting PRD to user, verify:
- [ ] All story acceptance criteria included verbatim
- [ ] Specific file paths from research included
- [ ] Similar implementations documented with examples
- [ ] Test strategy references testing-guidelines.md
- [ ] Business constraints clearly stated
- [ ] Technical context complete
- [ ] Success metrics are measurable
- [ ] PRD filename follows convention
- [ ] Linked to Shortcut story
- [ ] All sections from template filled out

## Integration with Workflow

**PRD fits into workflow as**:
1. ← Story created in Shortcut
2. → `/generate_prd` creates structured PRD
3. → `/create_plan` uses PRD for detailed planning
4. → `/implement` executes the plan
5. → PR references PRD and plan

## Handling Edge Cases

### If story has no acceptance criteria:
- Note this in PRD
- Extract implied criteria from description
- Ask user to confirm criteria

### If story is too vague:
- Document ambiguities in PRD
- Ask clarifying questions
- Don't proceed until clarified

### If research finds no similar implementations:
- Note that this is new pattern
- Research external best practices
- Document need for new pattern

### If story spans multiple components:
- Break down by component in PRD
- Note integration points clearly
- Suggest phased implementation

## Example Interaction Flow

```
User: /generate_prd 55337