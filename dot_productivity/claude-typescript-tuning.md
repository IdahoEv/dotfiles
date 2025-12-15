# Claude Code TypeScript Optimization Guide

**Target:** Generate strict, simple TypeScript that passes Pulse linting rules without manual fixes

## Your TypeScript Style Profile

Based on your Ruby/Rails background and clean code preferences:

- **Prefer:** Simple, declarative single types
- **Avoid:** Complex unions, intersections, chains of "as" statements
- **Avoid:** Loose typing (`any`, `unknown`) except where genuinely needed
- **Context:** Learning TS syntax while strong on architectural patterns

## Project-Specific Prompting Strategies

### 1. Pulse Project Context Template

Add this to your Claude prompts when working on Pulse:

```
TYPESCRIPT CONTEXT FOR PULSE PROJECT:
- Node/Fastify/Drizzle + Next.js stack
- Strict TypeScript linting rules enabled
- Prefer simple, explicit types over complex unions/intersections
- Avoid 'any' and 'unknown' - use specific types
- Follow patterns consistent with existing codebase
- Clean, readable code preferred over clever type gymnastics
```

### 2. Pre-Prompt TypeScript Rules

Use this as a system message or at the start of TS conversations:

```
TYPESCRIPT CODING STYLE:
1. Use explicit, single types rather than unions when possible
2. Prefer interface definitions over inline types
3. Avoid type assertions ('as') unless absolutely necessary
4. No 'any' types - be specific about what you expect
5. Create clear type definitions rather than complex nested types
6. Follow existing project patterns for consistency
7. Prioritize readability over type complexity
```

## Common Anti-Patterns to Call Out

Tell Claude to specifically avoid these patterns you've been seeing:

### ❌ Avoid These Patterns
```typescript
// Complex unions with 'as' chains
type ComplexType = (string | number | undefined) as SomeOtherType;

// Excessive unknowns
function process(data: unknown): unknown { ... }

// Deep nested intersections
type Complex = A & B & C & { nested: D & E };
```

### ✅ Request These Instead
```typescript
// Clear interfaces
interface UserData {
  id: string;
  name: string;
  email: string;
}

// Explicit return types
function getUser(id: string): Promise<UserData> { ... }

// Simple, readable types
type Status = 'pending' | 'completed' | 'failed';
```

## Project Setup Commands

### For Pulse-Specific Prompting
```
I'm working on the Pulse project (Node/Fastify/Drizzle + Next.js).
Use strict TypeScript with simple, explicit types.
Follow existing codebase patterns and avoid complex type gymnastics.
Generate code that passes our strict linting rules without manual fixes.
```

### For Learning-Focused Sessions
```
I'm learning TypeScript syntax while building [feature].
Explain type choices and provide clean, simple examples.
Prefer explicit over clever - I want to understand every type decision.
Point out common TypeScript patterns I should learn.
```

## Quick Wins While Learning

### 1. Type-First Development Prompts
```
"Define types first, then implement the function"
"Show me the interface before writing the implementation"
"What TypeScript types would you recommend for this data structure?"
```

### 2. Error Interpretation Help
```
"Explain this TypeScript error in simple terms: [paste error]"
"How would you fix this without using 'any' or type assertions?"
"What does this error tell me about my type design?"
```

### 3. Code Review Prompts
```
"Review this TypeScript for strict linting compliance"
"Suggest type improvements that align with clean code principles"
"Are there any type assertions I can eliminate?"
```

## VSCode + Claude Integration

Based on your current productivity plan items #32 (Error Lens) and #41 (ESLint keybinding):

### Error Workflow with Claude
1. Use Error Lens to see inline TypeScript errors
2. Copy error message to Claude with: "How do I fix this TS error cleanly?"
3. Use your ESLint auto-fix keybinding (when you set it up)
4. Ask Claude: "Why did this fix work? What pattern should I learn?"

### Learning Acceleration
```
# When you see a TS pattern you don't understand:
"Explain this TypeScript pattern from my Ruby/Rails perspective"
"How would this pattern look in Ruby? What's the TypeScript equivalent?"
"What's the clean, simple way to handle this type requirement?"
```

## Project-Specific .claude/instructions

Consider creating a `.claude/instructions.md` in your Pulse project root:

```markdown
# Pulse Project TypeScript Guidelines

This project uses strict TypeScript with these preferences:

## Type Style
- Explicit, simple types over complex unions/intersections
- No 'any' or 'unknown' unless genuinely required
- Clear interface definitions over inline types
- Minimal type assertions

## Stack Context
- Node/Fastify backend with Drizzle ORM
- Next.js frontend
- PostgreSQL database
- Strict ESLint rules enabled

## Code Generation Preferences
- Generate types that pass linting without manual fixes
- Follow existing codebase patterns
- Prioritize readability over cleverness
- Explain type choices for learning
```

## Weekly Learning Integration

Since you're studying the TypeScript handbook, add this to your daily practice:

### Morning Check (with productivity plan)
1. Pick a TS concept from your handbook reading
2. Ask Claude: "Show me 3 clean examples of [concept] that follow Pulse coding style"
3. Practice the pattern during the day

### Evening Review
1. Share any TS errors you couldn't fix quickly
2. Ask: "What pattern would prevent this error in the future?"
3. Update your understanding of the concept

## Next Actions

1. **Immediate:** Add the TypeScript context template to your next Claude session
2. **This week:** Create Pulse-specific .claude/instructions.md
3. **Ongoing:** Use error interpretation prompts when stuck
4. **Learning:** Connect each handbook concept to clean coding examples

This should significantly reduce the 5-10 minute cycles you're experiencing with TypeScript/ESLint errors while accelerating your learning.