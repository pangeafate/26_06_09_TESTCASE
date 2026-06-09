# Skill Design - System-Level Skills, Agent-Bound Use

## Purpose

Skills, tools, and capabilities should be shared contracts. Agents consume
them through grants and policy, not through per-agent copies of the same code.

## Philosophy

The load-bearing distinction is substrate versus domain reasoning.

Substrate is reusable machinery: validated data reads/writes, message sending,
event querying, scheduling, idempotency, correlation ids, and authorization
checks.

Domain reasoning is the part that belongs to a specific business domain:
scoring formulas, triage taxonomies, prompt fragments, or workflow-specific
decisions.

Generalize substrate. Do not force domain reasoning into a generic tool before
the shared shape is real.

## Principles

### 1. Skills are system-owned; agents are consumers

Skill code lives in one place. Agents declare which skills they may invoke.
Skill handlers must not branch on string-literal caller identity.

Bad:

```ts
if (ctx.agent_id === "support_agent") {
  // special behavior
}
```

Better:

```ts
const policy = await loadPolicy(ctx.agent_id, operation);
enforce(policy, input);
```

### 2. Configure over fork

Two skills that differ only by table, namespace, threshold, schedule, or
retention window should become one parameterized skill. Two skills that differ
in validation rules, idempotency, or side effects may stay separate.

### 3. Tool granularity follows authority granularity

Make tools only as fine-grained as the authorization model needs. If policy can
express "may write records in namespace X," a generic validated write tool is
enough. If policy must distinguish "may create but not approve," expose
separate verbs.

### 4. Domain invariants live with the operation

Enforce invariants in the tool handler, middleware, database constraint, or
service boundary that owns the operation. Do not rely on prompt text or caller
identity.

### 5. Repeated workflows become deterministic skills

When a workflow repeats, package the query plan, validation, filtering,
permission checks, side effects, and output envelope into one deterministic
skill. Let the model choose the skill and explain the result; do not make it
rebuild the same procedure from raw tools each time.

### 6. Compose, do not inherit

Agents get capabilities by grants and composition. Avoid inheritance-based
agent hierarchies that hide shared behavior in base classes.

### 7. Wait for the third use before extracting

Two similar uses may still be coincidence. Three independent uses usually
reveal the real axis of variation.

### 8. Skills are contracts

Every skill should declare:

- Input schema.
- Output schema.
- Side-effect class.
- Idempotency requirement.
- Authorization policy surface.

Two skills with the same contract should be one skill unless a meaningful
difference is named explicitly.

### 9. Skills are not the security boundary

Security should be enforced by grants, policy, ring-fence checks, and runtime
authorization hooks. Code organization can clarify policy, but it must not be
the only place policy exists.

### 10. Agent-specific skills require justification

Specialization carries the burden of proof. Use an agent-specific skill only
when:

- The reasoning cannot be parameterized.
- The state lifecycle is genuinely private to that agent/domain.
- The authorization boundary cannot be expressed in the shared policy model.

### 11. Schema-generic tools separate validity from authorization

A data-substrate tool should validate against live schema or a shared schema
registry. Validity answers "is this operation well-formed?" Authorization
answers "may this caller perform it?" Keep those axes separate.

## Review Questions

Before adding a skill or tool:

1. Is this substrate or domain reasoning?
2. Does an existing skill already cover the operation with parameters?
3. What does authority need to permit or deny?
4. Which invariants belong to the operation?
5. Is this a repeated workflow that deserves a deterministic skill?
6. What is the exact contract?
7. If specialized, which explicit justification applies?

## Refactoring A Fork

1. Extract shared substrate into a system-level tool.
2. Parameterize the variable axis.
3. Keep domain reasoning in the domain skill.
4. Migrate one consumer at a time.
5. Delete forked skills only after all consumers use the shared substrate.
