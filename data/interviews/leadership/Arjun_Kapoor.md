# Interview: Arjun Kapoor

## Meta

- **Name:** Arjun Kapoor
- **Role:** CTO
- **Department:** Engineering / Leadership
- **Email:** arjun.kapoor@helixpay.io
- **Status:** completed
- **Started:** 2026-04-09 10:30
- **Completed:** 2026-04-09 11:18
- **Language:** en

## Phase 1: Role & Daily Work

### Q: Arjun, give me the short version — what do you actually own day to day?

**A:** i own the technology strategy and i report to wei. day to day i'm not in the eng org running stand-ups anymore — daniel runs eng. i step back from that on purpose. my job is the two-year picture, the architecture posture, and the conversations with the board and with wei about where we should be putting our bets. i still sit in on the confluence design reviews because that is the bet right now and i don't want to be a stranger to it.

### Q: How much of your week is internal vs external?

**A:** sixty internal forty external roughly. external is investors, a couple of large enterprise prospects who want to meet a technical exec, and partner conversations on the rails side. internal is mostly daniel, sara, vikram, and increasingly the codos folks.

## Phase 2: Knowledge & Expertise

### Q: Confluence — your read on the timeline.

**A:** i'll be direct. i committed to wei in december that june was achievable. i was wrong. in retrospect june was not realistic. i was the one in the design review who looked at the merchant id work and said it would take six weeks and it's going to take more like four months once you count the dual-write and the repointing and the reconciliation of the brazil consolidation. so when daniel says late august to mid september that is the right number and the june commitment was mine to make and mine to walk back.

### Q: Why did you miss it in design review?

**A:** because i didn't push hard enough on the brazil data model. we knew the brazil system used per-location merchant ids and we knew sea used per legal entity. what i didn't internalize was how much historical reconciliation work that creates. camila has been telling us for months that the brazil data is messier than we modeled and we didn't budget for it. that's on me.

### Q: What does the architecture look like the day after confluence ships?

**A:** shared services, single code deploy across both geos, one auth one payments-core one fraud. the brazil-specific logic lives behind feature flags inside the same codebase rather than as a parallel codebase. that's the load-bearing piece. on top of that i want ai agent infrastructure as a first-class concern not a side project — meaning the ontology layer the codos team is building, an agent runtime, evals, and the right hooks into our data so internal agents can answer questions without an engineer in the loop.

### Q: Anything you'd do differently if you were rewinding twelve months?

**A:** yes. we should have built data infrastructure first and code-unification second. we did it the other way around. if we had a clean unified data layer first, the merchant id problem would have surfaced earlier and we would have solved it as a data problem not a migration-blocking-everything-else problem. that's the lesson i'm carrying into the codos work — get the data shape right first.

## Phase 3: Processes & Tools

### Q: How are you working with daniel on confluence?

**A:** weekly one-on-one, plus i'm in the friday review. he runs it. i don't second-guess his sequencing. when i have a concern i raise it in the one-on-one not in the review. that's working.

### Q: Sara and vikram — how do you see their roles?

**A:** sara owns platform and is the technical center of gravity for the unification. vikram owns the dual-write and the infra layer underneath it. they're the two i lose the most sleep over because if either of them got hit by a bus we'd add three months to the program. that's a knowledge concentration problem we have to fix after confluence.

## Phase 5: Problems & Ideas

### Q: How do you feel about the codos engagement now versus when it started.

**A:** more bought in than i was. i'll say that plainly. when priya first pitched it i was skeptical — we had confluence on the burner and i didn't want a second platform program competing for attention. what changed my mind was two things. one, the codos team is not asking my engineers to build the ontology, they're building it on top of our data, that's the right shape. two, when i actually mapped out what an internal agent layer looks like a year from now i couldn't see how we'd build it organically — eng would always deprioritize it. so having an external forcing function is useful. i still want to see the q3 deliverable before i declare it a win but i'm not skeptical the way i was in january.

### Q: What's the biggest risk on your radar that isn't confluence.

**A:** brazil tier-2 churn. i'm a technical exec so i shouldn't be the one flagging it but the platform gap there is real and we're losing merchants because of things we know how to fix and haven't prioritized. multi-property reporting is one. that's the cosmos hotels lesson and it's not absorbed yet.

## Phase 6: Calibration

### Q: How long have you been at HelixPay?

**A:** two and a half years. i joined post series a as vp engineering, took the cto role after the brazil acquisition when daniel stepped up to vp eng.
