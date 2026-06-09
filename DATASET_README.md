# Codos take-home

Codos turns a company's scattered context — docs, transcripts, dashboards, conversations — into something AI agents can reason over reliably. This take-home asks you to build a small version of that.

## The task

You're given `data/` — a snapshot from a fictional B2B payments company called **HelixPay**. 

Build a system that ingests it and exposes a programmatic interface for answering deep questions about the company. The consumer is an AI agent. Turn this raw data into a clean ontology about the organization.

Several requirements:

- **Agent-friendly.** The interface is built for an AI agent to call, not a human at a search box. CLI, HTTP, MCP, library — your call.
- **Deep questions, good answers, reasonable time.** The interesting queries don't have single-passage answers. They cut across the dataset; they involve staleness, aliases, hierarchy, contradictions; they need source attribution. Returning good answers to questions like these in reasonable time is the bar. How you divide the work between ingestion-time and query-time is yours to decide.
- **Built for a moving target.** The dataset will keep changing in real life — new files arrive, old ones get updated, things get re-imported. You don't need to implement live ingestion, but the architecture should make adding it later a small change, not a rewrite.
- - **Should be live in production** - not local.

## What's in `data/`

```
overview.md                     COO orientation note
org-chart.md                    Org chart, mid-April 2026
all-hands-2026-04-15.md         Company meeting transcript
weekly-review-2026-04-21.md     Weekly business review
board-update-2026-04-22.md      Board email
q1-2026-results.pdf             Q1 financials
board-deck-q1-2026.pdf          Board deck
interviews/                     24 employee Q&A interviews
dashboards/                     HTML dashboard exports
images/                         Charts and screenshots (JPEG)
chat/                           Slack channel exports
email/                          Customer and exec email threads
code/                           GitHub contributor analysis
```

It's deliberately what you'd actually receive on day one: multiple formats, inconsistent naming, mixed languages, stale alongside fresh, noise alongside signal, internal contradictions. The CEO does not have a structured interview in this sample; CEO context appears in the all-hands transcript, board update, exec chat, and email threads.

## Build quality

We expect that most of the code will be LLM-written — that's fine, that's how we work too. We won't dock you for a missing edge case or a function that could be cleaner. What we're looking for is the part where LLM is not (yet) reliable: a thought-through architecture, a project setup that runs, and the conventions you put around the model so it produces production-grade code instead of slop. That's what we'll be reading for.

## Constraints

- **Time budget: about 4-6 hours of focused work.** That's the size of the task we have in mind, including the writeup. 
- **Stack is your call.** We use Python and TypeScript day-to-day and we work with Claude. Pick whatever lets you ship.
- **LLMs are part of the system.** Use them. We'll be interested in *how* — when, where, with what context.
- **No starter code on purpose.** How you set up a project is signal.

## Submission

Pack your solution into a zip and send it to **gleb@codos.ai** and **dima@codos.ai**. Include a file `SOLUTION.md` that:

1. Documents how to run what you built — ideally one command from a fresh clone.
2. Describes the tradeoffs you faced and the calls you made.
3. Justifies the architectural choices that mattered.
4. Calls out what you didn't tackle. The dataset has plenty of quirks and edge cases and you won't (and shouldn't) handle all of them in 4-6 hours. Name the ones you left as future work and, for each, say why it's less important for the real product and less interesting as part of this exercise.

A 2–5 minute video walkthrough is welcome but optional.
