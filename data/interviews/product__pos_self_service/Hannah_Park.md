# Interview: Hannah Park

## Meta

- **Name:** Hannah Park
- **Role:** VP Product
- **Department:** Product / Leadership
- **Email:** hannah.park@helixpay.io
- **Status:** completed
- **Started:** 2026-04-09 10:05
- **Completed:** 2026-04-09 11:08
- **Language:** en

## Phase 1: Role & Daily Work

### Q: Hannah, give me your function in one sentence.

**A:** i own product across all five products — core, pos, pos self-service, loyalty, and tap — across both geos. about fourteen people on my team split roughly nine in singapore and five in brazil. i report to priya raman.

### Q: How do you spend your week in practice?

**A:** monday is usually the global product review where vinod yong wei jia qi and beatriz come in and we go through what's shipping what's slipping what's on fire. tuesday wednesday i try to keep blocks for actual roadmap work but those almost always get eaten by escalations or sales asks. thursday is the eng-product sync with daniel and his leads which is mostly about confluence sequencing right now. friday is half ones-on-ones half whatever i couldn't finish during the week. honestly the calendar is too full and i know that's not unique to me.

### Q: What's the split between strategic and tactical right now?

**A:** maybe thirty seventy and the seventy is tactical. that's worse than i'd like. a lot of my tactical time goes into negotiating with eng on what we can squeeze in around confluence which is a conversation that keeps repeating because the answer is always less than what we asked for.

## Phase 2: Knowledge & Expertise

### Q: What's the single biggest enterprise product gap right now?

**A:** multi-property reporting. it's not even close. we lost cosmos hotels in q1 over it — they're a hotel chain, they need consolidated reporting across their properties with the ability to drill down per property, and we can't do that in a clean way. they went to a competitor. the painful part is that this gap has been on the roadmap for three quarters. every quarter we plan it in, every quarter it gets bumped because confluence work or a critical bug or an enterprise sales ask takes priority. so it's been on the list since roughly q3 2025 and it's still not built. if i'm being honest about why — it's that multi-property requires changes to the merchant data model and we've been told to not touch the data model until the merchant id schema migration is done. which means it's blocked behind confluence too.

### Q: Anything else on the enterprise gap list?

**A:** sso for larger merchants, role-based access on the dashboard at the level enterprise wants it, and audit logs that are exportable in a format the bigger merchants' compliance teams accept. all real, all smaller than multi-property in terms of deal impact.

### Q: There's a tap-loyalty bug that came up in marco's interview. Tell me about it.

**A:** yes. when a brazilian merchant has both tap and loyalty enabled the reconciliation report shows wrong totals — the loyalty discount line and the tap settlement line don't reconcile correctly so the daily total the merchant sees doesn't match what they actually got paid. it's been a known issue since q4 2025. beatriz has been escalating it for months. it didn't make q1 prioritization and that's frustrating to me because it's the kind of bug that erodes trust with the merchant base every day it's open. we're carrying it with a manual workaround that maria santos's csms run monthly. it affects roughly two hundred eighty merchants in brazil. yong wei has the fix scoped but it sits in the queue behind confluence-blocking work for the loyalty service.

### Q: Why didn't it get fixed in Q1?

**A:** because the engineer who'd fix it is camila souza and camila has been pulled onto the brazil-side data work for confluence. that's the real answer. when we looked at q1 prioritization we had a choice between unblocking the schema migration and fixing this bug and we picked the schema migration. i think we made the right call given the constraint but i don't love that we keep being in this kind of choice.

### Q: What's the pos self-service status?

**A:** vinod owns it day to day so he can give you the full version. headline — we launched in 2025, current installed base is around three hundred forty active kiosks across sea, our target was six hundred by end of q1. so we're behind. two main reasons — kiosk hardware lead time is three months which limits how fast we can deploy, and there's market confusion between "pos" and "pos self-service". even our own sales reps mix them up. vinod wants to merge the marketing pages to clean it up but that's a conversation between him me and rajesh and we haven't aligned yet.

## Phase 3: Processes & Tools

### Q: What does the prioritization process look like?

**A:** we run a quarterly planning cycle. inputs are the strategy doc from priya and wei, customer asks aggregated by marco's team, sales gap list from sofia's team, and engineering capacity from daniel. we score things on a rough framework — revenue impact, churn risk, strategic alignment, eng cost — and then we sort. the part that's broken is that almost everything we want to do has eng cost that's blocked behind confluence so the sort doesn't do as much work as it should. when most of the list has the same blocker the framework stops being useful.

### Q: What tools does product use?

**A:** linear for tickets shared with eng, productboard for the roadmap, figma for design, notion for docs, looker for product analytics. nothing exotic.

## Phase 5: Problems & Ideas

### Q: If a system gave your team perfect context on demand what changes?

**A:** two things i'd buy tomorrow. one is exec briefings — every monday i spend an hour pulling together the state of product for the priya wei one-on-one. revenue numbers from finance, churn signal from cs, sales pipeline from sofia, the top three things shipping or slipping. if that briefing wrote itself i'd take that hour back instantly. two is sales prep. our enterprise ae's ask my team for the same context over and over before big merchant calls — what's the latest on multi-property, what's our tap roadmap in sea, when does feature x land. if a sales prep agent could answer those with the real story not the all-hands version i'd save my pms maybe four hours a week each. the multiplier across fourteen people is real.

### Q: What's the gap between what leadership thinks product is doing and what's actually happening?

**A:** the velocity perception. it looks slow from the outside. inside it's that almost every meaningful thing is gated on confluence and we've been holding the line on not doing data model work until the migration finishes. so the things that look like they should be easy aren't. once confluence lands a lot of the backlog will move at once and the perception will flip. before then we're going to keep getting the "why is product slow" question and the answer is going to keep being unsatisfying.

### Q: Anything on the team side?

**A:** beatriz needs more support in brazil. she's effectively running product for the entire brazil portfolio and the scope is bigger than one person. i've been trying to get a hire approved for q2.

## Phase 6: Calibration

### Q: How long have you been at HelixPay?

**A:** two years and two months. came in as senior pm for core, took over the vp role after the brazil acquisition closed.
