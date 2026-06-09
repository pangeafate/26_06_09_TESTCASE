# Output Template Enforcement

_How to build and enforce output templates for self-developing agent projects_

**Version**: 1.0
**Status**: Active Development Guidelines

---

## The Problem

LLM agents freestyle output when not constrained. A status report becomes a wall of text, a triage summary invents its own format, a notification ignores the established style. Templates and examples solve this -- but only if the agent is forced to read them before producing output.

Without enforcement, an agent will:
- Invent new formats each session (inconsistent user experience)
- Include irrelevant information and omit critical details
- Ignore icon conventions, grouping rules, and section ordering
- Produce output that looks different depending on context window contents

## Architecture: Three Enforcement Layers

Output template enforcement requires rules at three levels, each catching different invocation paths:

```
Layer 1: Global Rules          "Read TEMPLATES.md before generating any output"
(workspace instructions)        Loaded every session, catches ad-hoc output
        |
        v
Layer 2: Capability References  Task-specific templates with full examples
(spec files, reference docs)    Read on-demand when the capability is invoked
        |
        v
Layer 3: Invocation Instructions "Read the template file. Do not freestyle."
(cron messages, trigger prompts) Per-invocation enforcement, catches scheduled runs
```

### Why Three Layers

No single layer is sufficient:

| Layer | Catches | Misses |
|---|---|---|
| Global rules only | Ad-hoc requests | Scheduled runs, long sessions where rules drift |
| Capability references only | Explicit capability invocations | Ad-hoc formatting, human requests for "a quick summary" |
| Invocation instructions only | Specific triggers | Everything else |

All three together create defense-in-depth.

## Where Templates Live

### Short, Reusable Formats

Templates used across multiple capabilities go in a central file:

```
workspace/TEMPLATES.md
```

Examples: status cards, approval requests, notification formats, error reports.

These are loaded via the global rule (Layer 1) and are available to all capabilities.

### Long, Capability-Specific Templates

Templates with detailed formatting rules, icon legends, and complete examples go in capability-specific reference files:

```
src/capabilities/[name]/references/[template-name].md
```

Examples: daily briefings, detailed reports, slide generation guidelines.

These are loaded on-demand when the capability is invoked (Layer 2).

### Decision Criteria

| Criterion | Use TEMPLATES.md | Use references/*.md |
|---|---|---|
| Length | < 50 lines per template | > 50 lines |
| Reuse | Used by 2+ capabilities | Used by 1 capability |
| Complexity | Simple card format | Section structure, icon legends, grouping rules |
| Example needed | Brief inline example sufficient | Full realistic example required |

## How to Enforce Template Usage

### Layer 1: Global Rule (Session-Level)

In the agent's workspace instructions (e.g., AGENTS.md), add:

```markdown
**IMPORTANT:** Before generating any user-facing output, read `TEMPLATES.md`
for the exact format. Do not freestyle.
```

This is loaded at session start and catches any ad-hoc output.

### Layer 2: Capability Reference (On-Demand)

In the capability's spec file (e.g., SPEC.md or SKILL.md):

```markdown
## Output Format
Read `references/report-template.md` for the formatting template, icons,
and a complete example.

ALWAYS read the template file before formatting output. Do not freestyle.
```

This is read when the capability is invoked.

### Layer 3: Invocation Instruction (Per-Trigger)

In scheduled job messages or trigger prompts:

```
Step 2: Read the formatting template.
Read src/capabilities/reporting/references/report-template.md for the exact
format, icons, and a complete example.

Do NOT relay raw script output directly. Format according to the template.
```

This is embedded directly in the trigger payload, catching scheduled runs that may not load workspace instructions.

## Anatomy of a Good Template File

A template file should contain these sections, in order:

### 1. What the Input Looks Like

Describe the raw data the agent will receive (script output, API response, structured text). The agent needs to understand the input format to map it to the output format.

```markdown
## Input Format

The script outputs plain text with sections separated by `---`.
Each item is one line: `[ID] STATUS | TITLE | DEADLINE | PRIORITY`

Example input:
```
[42] active | Review proposal | 2026-04-15 | high
[43] waiting | Send contract | 2026-04-10 | critical
```
```

### 2. Icon/Symbol Legend

Exact icons to use. Do not leave this to the agent's judgment -- it will pick different icons each time.

```markdown
## Icons

### Priority Icons
- Critical: (!!)
- High: (!)
- Normal: (-)
- Low: (.)

### Status Icons
- Active: [>>]
- Waiting: [..]
- Complete: [OK]
- Blocked: [XX]

### Deadline Icons
- Overdue: (LATE)
- Today: (TODAY)
- This week: (SOON)
```

### 3. Item Format

The pattern for each line item. Use placeholders for variable content.

```markdown
## Item Format

```
{status_icon} **[{id}] {priority_icon}** {title} -- {deadline_text}
```

Examples:
```
[>>] **[42] (!)** Review proposal -- due Apr 15
[..] **[43] (!!)** Send contract -- due Apr 10 (LATE)
```
```

### 4. Section Structure

The order and hierarchy of sections in the output.

```markdown
## Section Structure

1. **Header**: Date, greeting, summary sentence
2. **Critical Items**: Items with priority=critical or overdue deadlines
3. **Active Work**: Items with status=active, grouped by area
4. **Waiting**: Items with status=waiting
5. **Footer**: End-of-day check question, next actions
```

### 5. Formatting Rules

Grouping logic, what to omit, message splitting, length limits.

```markdown
## Formatting Rules

- Group items by area within each section
- Omit completed items unless completed today
- If output exceeds 3000 characters, split into multiple messages
- Always include the footer, even if there are no items
- Empty sections: omit the section header entirely (do not show "No items")
```

### 6. Complete Example (MOST IMPORTANT)

A real, filled-in instance of the template. This is the single most important section.

**Why**: Agents copy examples more reliably than they follow abstract rules. An abstract rule like "group by area" is ambiguous -- an example showing exactly how grouped items look is unambiguous.

```markdown
## Complete Example

**Input:**
```
[42] active | Review proposal | 2026-04-15 | high | product
[43] waiting | Send contract | 2026-04-10 | critical | legal
[44] active | Update dashboard | 2026-04-20 | normal | engineering
[45] active | Fix login bug | 2026-04-12 | high | engineering
```

**Output:**
```
Good morning! Here is your status for April 11, 2026.
3 active items, 1 waiting. 1 critical item needs attention.

--- CRITICAL ---

[..] **[43] (!!)** Send contract -- due Apr 10 (LATE)
   Waiting on legal review. Overdue by 1 day.

--- ACTIVE WORK ---

Engineering:
[>>] **[45] (!)** Fix login bug -- due Apr 12 (SOON)
[>>] **[44] (-)** Update dashboard -- due Apr 20

Product:
[>>] **[42] (!)** Review proposal -- due Apr 15

--- END OF DAY CHECK ---

Before wrapping up today, verify:
- Did the contract get sent? (1 day overdue)
- Is the login bug fix on track for tomorrow?
```
```

## Pattern: Data Script + LLM Formatting

For complex outputs, separate deterministic data gathering from creative formatting:

```
Data Script (deterministic)          LLM Agent (creative)
query_database()                     Read template
  -> filter and sort                 Categorize items
  -> compute derived fields          Group into sections
  -> return structured data          Choose contextual language
  -> stdout (plain text/JSON)        Compose summaries and questions
```

The script produces **structured data** -- no formatting decisions. The agent applies the template using its intelligence to categorize, group, and compose contextual elements that code cannot do well.

### Why This Split Works

- **Pure code formatting**: Cannot make judgment calls ("Pay utility bill" is financial; "Review proposal" is product work)
- **Pure LLM querying**: Hallucinates data, misses items, produces inconsistent structure
- **Combined**: Deterministic data + intelligent formatting = reliable and contextual output

### Implementation Pattern

```python
# Script: compile_report.py (deterministic)
def main():
    items = query_items()           # Database query, no formatting
    computed = compute_metrics(items)  # Derived fields, aggregations
    output = format_as_plain_data(items, computed)  # Structured text
    print(output)                   # To stdout for agent consumption

# Agent instruction (in SPEC.md or trigger):
# 1. Run compile_report.py to get the raw data
# 2. Read references/report-template.md for the formatting template
# 3. Format the data according to the template
# 4. Do NOT relay the raw script output directly
```

## Checklist: Adding a New Template

When adding a new output format to the project:

### 1. Create the Template File

- Short card format: add to `workspace/TEMPLATES.md`
- Capability-specific with examples: create `src/capabilities/{name}/references/{name}.md`

### 2. Include a Complete, Realistic Example

- Use real-looking data (not "Lorem ipsum" or "Example 1, Example 2")
- Cover the common case AND at least one edge case (empty section, overdue item, etc.)
- Make the example long enough to demonstrate grouping, ordering, and section structure

### 3. Add Read Instructions at Every Invocation Point

| Invocation Path | Where to Add | Instruction |
|---|---|---|
| Ad-hoc user request | `workspace/AGENTS.md` or `TEMPLATES.md` | "Read TEMPLATES.md before generating output" |
| Capability invocation | `SPEC.md` or `SKILL.md` | "Read references/{name}.md before formatting" |
| Scheduled job | Cron/trigger message payload | "Read {path} for the exact format" |
| Sub-agent delegation | Task description for sub-agent | "Format output according to {path}" |

### 4. Add "Do Not Freestyle"

At every instruction point, include the explicit directive: **"Do not freestyle."**

This sounds redundant, but without it, agents treat templates as suggestions rather than requirements.

### 5. Ensure Data Scripts Produce Clean Structured Output

If the template depends on script output:
- The script produces structured data (JSON, key-value lines, delimited text)
- The script does NOT make formatting decisions (no icons, no grouping, no headers)
- The agent transforms the data into the template format

### 6. Test the Template

- Have the agent produce output using the template
- Compare against the complete example
- Verify: correct icons, correct section order, correct grouping, correct omissions
- If the agent deviates, refine the template (usually the example needs to be more explicit)

## Template Maintenance

### When to Update Templates

- When the output format changes (new sections, different icons, changed ordering)
- When a data script's output structure changes (new fields, renamed fields)
- When users report formatting issues (the template was ambiguous)

### Versioning

Templates are version-controlled alongside code. Changes to templates should be:
- Committed with the code changes that motivated them
- Noted in the sprint plan if significant
- Tested by producing sample output after the change

### Deprecation

When replacing a template:
1. Keep the old template file until all invocation points are updated
2. Add a deprecation notice at the top of the old file: `**DEPRECATED**: Use {new-file} instead`
3. Remove the old file only after confirming no references remain

---

_This framework ensures that self-developing agents produce consistent, well-formatted output. The complete example is the most powerful enforcement tool -- agents copy examples more reliably than they follow abstract rules._
