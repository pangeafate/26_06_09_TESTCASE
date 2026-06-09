# Interview: Sara Wijaya

## Meta

- **Name:** Sara Wijaya
- **Role:** Backend Lead, Core
- **Department:** Engineering
- **Email:** sara.wijaya@helixpay.io
- **Status:** completed
- **Started:** 2026-04-09 10:05
- **Completed:** 2026-04-09 11:14
- **Language:** en

## Phase 1: Role & Daily Work

### Q: Give me the short version of what you own.

**A:** i lead the backend team for core which is the merchant payments processing platform from the singapore side. i report to daniel. day to day i'm running the team about eight engineers in sg and i'm also the platform owner for confluence on the sea side which means the unified merchant_id schema sits with me. so half of my week is people stuff one on ones reviews unblocking and the other half is design work and code review on the migration.

### Q: Walk me through a typical day.

**A:** stand-up at nine sg time. usually a design review or two before lunch. afternoons i try to keep heads-down for actual schema work or pr review. then around five or six brazil comes online and i either join the brazil-side sync or have a one-on-one with vikram or with camila. some days the whole afternoon goes to the brazil sync and i get nothing of my own done which is fine that's the phase we're in.

### Q: Who do you work with most closely?

**A:** vikram on infra he owns the dual-write tooling so we are joined at the hip right now. camila on the brazil data side she knows the historical brazil schema better than anyone. ahmad on mobile because pos consumes the merchant_id apis and luiz on delivery for brazil. and daniel of course.

## Phase 2: Knowledge & Expertise

### Q: Tell me about the schema migration. What's the actual state.

**A:** ok so the unified schema lives in helixpay/core/merchants/schema_v3.py and the design is one merchant_id per legal entity which is the sea convention. we're running dual-write so the legacy sea system and the legacy brazil system both still write to their old tables and the new unified system writes alongside. vikram's reconciliation script runs hourly and surfaces mismatches. we are at zero point four percent mismatch right now down from two-ish in march. the headline number sounds great but the long tail is nasty.

### Q: What's in the long tail?

**A:** almost all of it is brazil. roughly twenty-eight thousand merchants where the brazil side had multiple banking instructions per "merchant_id" because their merchant_id was actually a per-location identifier. so a single legal entity could have ten locations each with its own banking setup fee schedule sometimes even different acquirer routing. when we collapse those to one canonical merchant_id by legal entity which is what sea expects we have to decide which banking instruction wins. some of those we can resolve with rules — most recent wins, or the location flagged primary wins — but a meaningful chunk of them need a human to look. either someone on camila's team or sometimes the merchant directly. that's why the last zero point four percent is going to take longer than the first one point seven did.

### Q: What's your honest read on the timeline.

**A:** september. if no new edge cases. daniel said sept thirty in the weekly and i agree with him. i would not commit to august. the public position is june and we're all aware that's not happening but the re-baseline isn't done yet so officially i'm still saying june. between you and me september.

### Q: What about after cutover.

**A:** then it's six to eight weeks of repointing dependent services. pos consumes merchant_id, loyalty consumes it, the reporting stack, the onboarding flow. each of those needs to swap to the new api and we test each one. parallelizable mostly but not zero work. so end of september cutover means dependent services done by mid november. that's the real ga.

### Q: Anything you discovered late that you wish you'd caught earlier.

**A:** the per-location vs per-legal-entity thing should have been in design review. it wasn't. we found it week two of implementation. i own that. the second one is that the brazil database has more than just two merchant models in it — there's a third one buried in some of the older tables that vikram noticed. that's not breaking the migration but it makes the reconciliation logic more annoying than it should be.

## Phase 3: Processes & Tools

### Q: How does the team coordinate across singapore and brazil.

**A:** we've gotten better but the honest answer is it's a daily thirty-minute sync not a stand-up. like a real meeting with an agenda where we walk through the reconciliation queue and the open prs. that takes thirty minutes minimum and we still miss things. the structural problem is the singapore stand-up is at nine am sg and the brazil stand-up is around nine am sao paulo which is twelve hours apart. so anything that comes up in the sg stand-up doesn't reach brazil until basically the next sg morning. info propagates with a day's lag which sounds fine until you're in a week where every day matters.

### Q: Have you tried changing the cadence.

**A:** we've talked about a single global stand-up at a time that's bad for both sides. nobody loves it. we do have a wednesday global engineering thing daniel runs but that's once a week.

### Q: What tools.

**A:** linear, github, datadog, pagerduty, slack. nothing exotic. the reconciliation dashboard vikram built sits in datadog.

### Q: How are you onboarding new engineers right now.

**A:** badly. five to six weeks to ramp. we have a runbook but it's stale and the real knowledge of how core actually works is in maybe four people's heads me vikram daniel and one of camila's seniors. i wish we had a system where a new joiner could ask questions of the codebase and get real answers with the right code paths. that would cut weeks off ramp.

## Phase 5: Problems & Ideas

### Q: If a magic ai system existed today that knew your codebase what would change.

**A:** onboarding is the obvious one. five to six weeks down to two would be life-changing for capacity. the second one is incident triage — half the time when something pages we spend the first fifteen minutes just figuring out which service touches the broken thing. a system that could answer "what calls this endpoint and what depends on it" instantly would be huge. third is the design review thing, the per-location issue we missed — if i could ask "is there anything in the brazil schema that contradicts assumption x" before i write the design doc that would catch some of these.

### Q: What's the single biggest pain point on confluence right now.

**A:** the lag between sg and brazil. not the technical work the communication. the technical work we know how to do.

### Q: If you could change one thing about how the brazil and sg eng teams work together what would it be.

## Phase 6: Calibration

### Q: How long have you been at HelixPay.

**A:** four years in june. joined as a backend engineer when core was three people, became lead about eighteen months ago.

### Q: One thing you'd want leadership to understand about the engineering side that you don't think they currently do.

**A:** the zero point four percent number sounds tiny. it isn't. each of those records is a real merchant with real money flowing and a wrong reconciliation means someone gets paid wrong. we are not going to cut over until that number is zero and i don't want anyone outside eng deciding that's a number we can ship at.
