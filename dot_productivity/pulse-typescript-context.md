# Pulse Project TypeScript Context

Use this context when working on the Pulse project to ensure Claude Code generates appropriate TypeScript.

## Project Stack
- Backend: Node.js + Fastify + Drizzle ORM + Zod validation
- Frontend: Next.js
- Database: PostgreSQL
- Purpose: Internal tool for (1) data API and (2) prospect/candidate selection

## TypeScript Style Guidelines

### Preferred Patterns
- **Simple, explicit types** over complex unions/intersections
- **Declarative single types** rather than workarounds
- **Specific types** rather than `any` or `unknown`
- **Type guards** over type assertions (`as` statements)
- **Interface definitions** for data structures
- **Zod schemas** for validation with proper TypeScript inference

### Anti-Patterns to Avoid
- Chains of `as` type assertions
- Complex union types with intersection workarounds
- Using `any` or `unknown` as escape hatches
- Nested conditional types when simple alternatives exist
- Type gymnastics to work around linting errors

## Common Patterns in Pulse
- **Request validation**: Separate Zod validators for request parameters vs request body
- **Database types**: Use Drizzle's inferred types from schema definitions
- **API responses**: Strongly typed response objects, not generic Record types
- **Error handling**: Explicit error types rather than union catch-alls

## Prompt Template
```
PULSE PROJECT CONTEXT:
- Node/Fastify/Drizzle + Next.js stack with PostgreSQL
- Strict TypeScript linting rules enabled
- Prefer explicit, simple types over complex unions/intersections
- Avoid 'any' and 'unknown' - use specific types from Drizzle schema
- Use Zod for validation with proper TypeScript inference
- Follow declarative patterns, not complex type workarounds
```

Copy this into Claude Code sessions when working on Pulse to get cleaner, project-appropriate TypeScript suggestions.