# Interview: Ahmad Rashid

## Meta

- **Name:** Ahmad Rashid
- **Role:** Mobile Lead, POS
- **Department:** Engineering
- **Email:** ahmad.rashid@helixpay.io
- **Status:** completed
- **Started:** 2026-04-12 13:45
- **Completed:** 2026-04-12 14:18
- **Language:** en

## Phase 1: Role & Daily Work

### Q: Ahmad — quick version of what you own.

**A:** mobile for pos. that means the pos app that runs on the card-reader hardware and also the pos self-service kiosk app which is the kiosk product that launched last year. four engineers reporting to me, all in singapore. i report to daniel. the two apps are technically different products but they share about sixty percent of the codebase — the payment flow the receipt rendering the offline queue the sync logic. the kiosk app has its own ui layer and a chunk of self-service flow logic on top.

### Q: A typical day.

**A:** stand-up nine. usually a code review block in the morning. afternoon depends — if there's a release going out i'm in release prep, otherwise it's roadmap work and one on ones. brazil overlap is light for us mostly, the brazil mobile work goes through luiz's team and we coordinate at a higher level.

### Q: Who do you work with most.

**A:** my four engineers. vinod for the kiosk pm side, jia qi on tap because the tap integration touches our payment flow, sara on backend because pos consumes a lot of core apis, and daniel.

## Phase 2: Knowledge & Expertise

### Q: Tell me about the tap-loyalty integration bug.

**A:** known issue. surfaces in brazil mostly because tap launched there in q4. when a merchant runs a tap-on-phone transaction with loyalty applied the reconciliation report sometimes shows the loyalty discount in the wrong column — it gets booked as a fee adjustment instead of a discount. doesn't lose money for anyone, the totals tie out, but it makes the merchant's report look weird and it generates support tickets. we know where the bug is. fix is queued. it's been queued for a while because the schema migration work eats most of our backend time and the mobile side of the fix needs a backend change first. it's hurting tap attach in brazil — merchants try it, see the weird report, lose confidence. i feel bad about it.

### Q: Why isn't it prioritized higher.

**A:** because confluence is eating everything. once the merchant_id migration lands the tap codebase actually gets simpler — we currently have two paths in the code for the brazil per-location merchant case and the sea per-legal-entity case, and after migration we collapse to one. so the tap-loyalty fix slots in cleaner after migration than before. that's the rationalization. the truth is also that we just don't have the cycles right now.

### Q: How does the schema migration affect your team.

**A:** medium. we don't own the migration but we consume merchant_id in the pos apis so we'll be one of the dependent services that has to repoint after cutover. sara's team is good at giving us advance notice. i don't think about confluence day to day, it's not our main work, but it sets the calendar for some of our cleanup work.

## Phase 3: Processes & Tools

### Q: Tools your team uses.

**A:** github, linear, datadog for the backend bits we own, firebase crashlytics for mobile, slack. nothing exotic.

### Q: Biggest operational pain.

**A:** ticket bouncing. every time a merchant complains about something showing up wrong in the app — reconciliation off, transaction missing, receipt weird — the ticket comes in to cs, cs sends it to mobile because the merchant saw it on a phone, mobile looks and says it's a backend issue and sends it to payments, payments looks and says it's actually a cs configuration issue and sends it back. that loop takes days. by the time the merchant gets an answer they're already annoyed. it's not anyone's fault structurally but it's a real cost.

### Q: How would you fix it.

**A:** i'd want a system that can look at a ticket and tell me which app behavior actually caused it. right now we triage by reading the ticket and guessing. if we had something that could correlate the ticket text with our crash data and our backend error logs and tell us "this looks like the recon discrepancy bug from two weeks ago" we could route correctly the first time.

## Phase 5: Problems & Ideas

### Q: If a magic ai system existed for your team what would it do.

**A:** the ticket triage thing i just said. that's the big one for me. the secondary one is i want to understand which app behaviors are actually generating tickets. i suspect a small number of behaviors are generating most of the support load and if i knew which ones i could prioritize the fixes properly. right now i'm guessing.

### Q: What about codebase knowledge.

