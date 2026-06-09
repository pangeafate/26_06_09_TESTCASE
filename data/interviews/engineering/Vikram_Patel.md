# Interview: Vikram Patel

## Meta

- **Name:** Vikram Patel
- **Role:** Platform / Infrastructure Lead
- **Department:** Engineering
- **Email:** vikram.patel@helixpay.io
- **Status:** completed
- **Started:** 2026-04-08 15:30
- **Completed:** 2026-04-08 16:42
- **Language:** en

## Phase 1: Role & Daily Work

### Q: Vik — give me the one-line version of what you own.

**A:** platform and infra for the engineering org across both geos. that means the cloud footprint, the deployment pipelines, observability stack, and right now most importantly the dual-write tooling for the merchant_id migration. i report to daniel. small team — one sre and three engineers. we punch above our weight which means we're permanently a little stretched.

### Q: What does a typical day look like.

**A:** sg stand-up at nine. then i'm usually in the reconciliation dashboard for the first hour seeing what mismatches showed up overnight. afternoon is split between code review on the dual-write changes and whatever pagerduty noise i'm chasing down. brazil overlap in the late afternoon i jump on the sync sara runs with camila. evenings i try to switch off but pagerduty doesn't always agree.

### Q: How is on-call.

**A:** noisy. four to seven pages a week just from the dual-write system. a chunk of those are real, a chunk are the recon script flagging something that turns out to be benign. we're tuning thresholds but every time we tune them down something real slips and we tune back up.

## Phase 2: Knowledge & Expertise

### Q: Tell me about the dual-write system.

**A:** in production. has been since mid march. the legacy sea system and the legacy brazil system both write to their old tables and the new unified system writes alongside. every write goes to two places. then the reconciliation script runs hourly, picks up mismatches, classifies them, and pushes them to a queue. mismatch rate when we started was about two point one percent. as of this morning it's zero point four. that drop is mostly us closing systematic issues — wrong field mappings, timezone problems, encoding stuff with portuguese characters in merchant names. the long tail that's left is the genuinely hard cases.

### Q: What's the long tail.

**A:** it's the brazil per-location merchant_id thing. brazil was issuing one merchant_id per physical location and a single legal entity could have many. we collapse those down to one canonical id and we have to pick which banking instructions and fee schedules carry forward. some of those we can do with rules. some need a human. that's the bulk of what's left.

### Q: How long to zero.

**A:** four to six weeks if nothing new shows up. then cutover. then six to eight weeks repointing the dependent services pos loyalty reporting onboarding. so call it three to four months from today on the optimistic side. daniel's number of september for ga is consistent with that.

### Q: You said something earlier about the brazil database having more than two merchant models.

**A:** yeah this is fun. when we got under the hood we realized brazil had three different conceptual models for "merchant" living in different tables. it's a historical artifact — the brazil entity we acquired had itself acquired two smaller companies before helixpay picked them up, and each of those came with its own merchant abstraction. one was a per-location model which is what we mostly talk about. one was a per-cnpj model which is closer to legal entity but not quite. and one was a hybrid that mixed both depending on the merchant tier. the production code mostly uses the per-location one but parts of reporting still hit the others. our reconciliation script has to know about all three.

### Q: That's not in any doc presumably.

**A:** correct. it's in camila's head and now mine. one of the reasons i want better knowledge tooling.

## Phase 3: Processes & Tools

### Q: Tools.

**A:** github, linear, datadog, pagerduty, terraform, aws. nothing weird. the reconciliation dashboard is custom but it's just datadog widgets pointing at a postgres we keep the mismatch queue in.

### Q: How does the team coordinate with brazil infra.

**A:** brazil doesn't have a dedicated infra person. luiz's team has senior engineers who own pieces of their stack but no equivalent of me. that means anything infra-shaped on the brazil side comes through me which is also why my team is permanently behind.

### Q: Are you hiring.

**A:** sea hires were paused last week pending the confluence re-baseline. i had a req open for another sre that's now frozen. brazil reqs are still open but i don't run those.

## Phase 5: Problems & Ideas

### Q: You're part of the codos kickoff. What do you want out of an ai system.

**A:** i want a system that knows our infra. specifically — right now if i'm not on call but i get pinged because someone needs context, i have no fast way to get that context. i have to log into datadog click through dashboards check pagerduty history check the recent deploys in github read the slack thread. fifteen twenty minutes minimum to get oriented. if i could ask "what's the state of the dual-write system in the last hour and what changed in the last day" and get a real answer i'd save hours a week. multiply that by every senior engineer.

### Q: Anything else.

**A:** runbooks. we have them but they are out of date the second you write them. a system that could keep a live picture of how things actually work — what's calling what, what the latest deploy did, where the recent incidents clustered — would be more valuable than any static doc.

### Q: One thing you'd change about how engineering operates today.

**A:** the twelve-hour gap between sg and brazil is the killer. not because the people aren't good — they are — but because anything that needs back-and-forth takes a calendar day per round trip. the tooling has to fill that gap because the meetings can't.

## Phase 6: Calibration

### Q: How long at HelixPay.

**A:** two and a half years. came in as a senior infra engineer, took the lead role about a year in.

### Q: How confident are you in the september number.

**A:** seventy percent. the thing that would push it later is finding a fourth merchant model we don't know about, which i'd put at maybe twenty percent likely.
