# Interview: Daniel Tan

## Meta

- **Name:** Daniel Tan
- **Role:** VP Engineering
- **Department:** Engineering / Leadership
- **Email:** daniel.tan@helixpay.io
- **Status:** completed
- **Started:** 2026-04-10 14:02
- **Completed:** 2026-04-10 15:11
- **Language:** en

## Phase 1: Role & Daily Work

### Q: Hey Daniel — give me the one-sentence version of what you own.

**A:** I own the engineering function across both geos which means roughly seventy people split sixty-thirty between Singapore and São Paulo and i report to Arjun the cto. Day to day i'm half in roadmap and capacity conversations and half in technical reviews on stuff i think is at risk and the third half which doesn't exist is hiring.

### Q: What does a typical Tuesday look like?

**A:** stand-up at nine with the lead engineers in singapore. then a one-on-one or two. lunch usually at the desk. afternoon i try to keep one block clear for actual code review or design review depending on what's hot. then in the late afternoon brazil comes online and i do another stand-up cadence with luiz and his leads. that block is always longer than i want it to be because we're in a phase where the brazil team needs more context than a stand-up can carry.

## Phase 2: Knowledge & Expertise

### Q: What's the most important program you're running right now and what's its real status?

**A:** confluence. and i'll give you the real status not the all-hands status. the original commitment was end of june for a unified platform meaning a single backend and shared services for auth payments-core and fraud. we are not making end of june. the merchant id schema migration is the foundation and we've been running dual-write for three weeks and we still have point four percent of records mismatching between the two systems. that's about thirty thousand records out of seven million, the long tail. until we're at zero we can't cut over and after we cut over there's another six to eight weeks of repointing the dependent services and re-testing them. so realistic ga is late august to mid september. i would commit to september thirty if you held me to a number which is what i told priya in the weekly. publicly we are still saying june. that is going to change in the next two weeks.

### Q: What's making the schema migration hard?

**A:** two things. one is that the brazil system was built on a different assumption about merchant identity than the sea system. in sea a merchant is a legal entity and we issue one merchant id per legal entity. in brazil they were issuing one merchant id per location and a multi-location merchant could have ten or twenty ids. for our purposes those are different things and we have to decide which is canonical and reconcile the historical data. we picked legal entity as canonical. that means consolidating ids in the brazil data which means resolving cases where brazil had different banking instructions or different fee schedules per location. that's where most of the mismatches come from. second thing is that the original plan didn't budget any time for this — we discovered it in week two of the implementation. that's on me, we should have caught it in design review.

### Q: Who are the key people on confluence?

**A:** sara wijaya owns the platform side from singapore. vikram patel owns infra and the dual-write tooling. camila souza owns the brazil-side data work and is also the person who actually understands the brazil data better than anyone. luiz ferreira is camila's manager and runs delivery for brazil. on the consuming side ahmad rashid for pos and yong wei for loyalty are the two people who feel the most pain when we slip.

### Q: How much of confluence is blocked on people versus on technical decisions?

**A:** mostly on the merchant id thing. once that lands the rest is parallelizable and we have the people. before that almost nothing else can finish.

## Phase 3: Processes & Tools

### Q: Are the singapore and brazil eng teams operating as one team or two?

**A:** two. that's the honest answer. we have shared rituals — global stand-up wednesdays, joint design reviews on confluence work — but the daily mode is two teams that happen to share an org chart. accents languages timezones tooling, all of it different. the platform unification is supposed to be the forcing function for becoming one team but we're learning that you can't merge teams by merging codebases, you have to do it the other way around.

### Q: What tools does the team use?

**A:** linear for tickets, github for code, datadog for observability, pagerduty, slack for everything else. brazil added a couple of local tools we don't use in sea — they have an internal portal for merchant onboarding that singapore doesn't have because we route it through the standard product. that portal is one of the things we have to retire as part of confluence.

### Q: What does engineering hiring look like right now?

**A:** as of yesterday we paused new sea hires until the confluence re-baseline is signed off. brazil hiring continues, three open reqs. we'll un-pause sea once we have a credible plan.

## Phase 5: Problems & Ideas

### Q: If a magic ai system existed today that could give your team the right context on demand, what would change?

**A:** a couple of specific things. one — onboarding new engineers to the codebase. we have a runbook but the runbook is twelve months out of date and the real knowledge is in five people's heads. if a new joiner could ask "how does fraud check work for cross-border POS transactions" and get a real answer with the relevant code paths and the context of why it works that way, that'd save us a month of ramp per person. two — incident response. we have post-mortems written up but in the moment of an incident the relevant prior post-mortem is hard to find. three — and this is the codos thing — i would love it if non-engineers could answer their own questions about the product without slacking an engineer. half my interrupts are sales people asking is x supported.

### Q: What's the biggest gap between what leadership thinks is happening in eng and what's actually happening?

**A:** the velocity question. there's a perception that eng is slower than it should be. the reality is most of the engineering capacity right now is going into confluence and the merchant id work and that work is invisible. when it lands a bunch of stuff will move quickly. before then the perception gap is going to keep widening.

## Phase 6: Calibration

### Q: How long have you been at HelixPay?

**A:** three years and four months. joined as a senior engineer when we were thirty people, became eng manager after a year, vp eng after the brazil acquisition.
