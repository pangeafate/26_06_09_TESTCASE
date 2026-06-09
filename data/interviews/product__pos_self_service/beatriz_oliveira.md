# Interview: Beatriz Oliveira

## Meta

- **Name:** Beatriz Oliveira
- **Role:** Product Lead, Brasil
- **Department:** Product
- **Email:** beatriz.oliveira@helixpay.io
- **Status:** completed
- **Started:** 2026-04-10 11:00
- **Completed:** 2026-04-10 12:04
- **Language:** en (with PT phrases)

## Phase 1: Role & Daily Work

### Q: Bea, what do you own?

**A:** i own product priorities for the brasil portfolio. that means tap which we launched in q4, the brazil side of loyalty, the brazil-specific bits of core, and a chunk of pos. i don't own the kiosk product, that's vinod. i report to hannah park into the global product org but day to day i'm embedded with the brazil team — luiz on eng, rafael on the md side, fernanda on marketing, maria santos on cs. so the singapore reporting line is real but my operating context is here in são paulo.

### Q: How does your week run?

**A:** mornings i'm with the brazil team — stand-ups, design reviews, customer calls. afternoons singapore comes online and i jump into the global product review on mondays and the eng-product sync with daniel's team midweek. it's a long day, tipo, by the time singapore is done it's eight pm here. i try to protect fridays for actual roadmap thinking but it doesn't always survive.

### Q: What's eating your week right now?

**A:** the tap-loyalty reconciliation bug. honestly. it's been eating my week since q4.

## Phase 2: Knowledge & Expertise

### Q: Tell me about that bug. The full version.

**A:** so. when a merchant in brasil has both tap and loyalty turned on, the reconciliation report — the daily report they pull to check what they got paid — shows wrong totals. the loyalty discount line and the tap settlement line don't reconcile properly. the merchant looks at the report and the bottom number doesn't match the deposit they got from the bank. they call their csm and they say "why is this wrong". and we have to manually walk them through it. a gente vê isso toda semana. about two hundred eighty merchants are affected — that's the ones with both products active. it's been a known issue since q4 2025. i've been escalating it since then. muito frustrante isso aqui.

### Q: Why hasn't it been fixed?

**A:** because the engineer who would fix it is camila souza and camila is on the confluence brazil-side data work. her capacity for everything else is basically zero until that lands. yong wei has scoped the fix on the loyalty service side but it can't ship in isolation, it needs the brazil data piece too. so it's queued behind confluence. hannah and i have talked about it many times. she agrees it should be higher priority. but every quarter we go through prioritization and confluence wins. eu entendo, mas é frustrante.

### Q: What's the workaround?

**A:** maria santos and her csms run a manual monthly reconciliation for every affected merchant. they pull the raw transactions, recalculate the totals, send the merchant a corrected statement by email. camila built a small script that helps with the calculation but the actual sending and the customer comms is manual. it takes maria's team probably forty hours a month across all the affected merchants. it's not sustainable but it's what we're doing.

### Q: How are merchants reacting?

**A:** depends on the merchant. some are patient because their csm has built the relationship and they trust that we'll get it right. others are openly annoyed and i think a few are already shopping around. we haven't lost a merchant explicitly over this yet that i know of but it's contributing to the brasil smb nps being thirty-one. when your reports are wrong you don't trust the platform.

### Q: What other product priorities are on your list for brasil?

**A:** tap continued rollout — we launched in q4 and the adoption is decent but the integration story is what'll make it stick. multi-property reporting matters for some of our larger brazil merchants too although the cosmos loss was a sea hotel chain. and there's a chunk of localization work for the dashboard that's been pending forever — date formats, currency symbols, some of the labels still come through in english. small but visible.

### Q: Tell me about the tap launch in brasil.

**A:** we launched in q4 2025. the tap-on-phone product. it's done well in terms of merchant interest — fernanda's team has generated a lot of leads. the conversion to paid is weaker than we hoped, fernanda can talk about the marketing side. on the product side the launch was clean except for the loyalty integration bug, which surfaced about three weeks after launch when we had enough merchants with both products to notice.

## Phase 3: Processes & Tools

### Q: What tools are you using?

**A:** productboard for the roadmap, linear shared with luiz's team for tickets, looker for product analytics, notion for docs, slack. nothing brazil-specific on the product side.

### Q: How does the global-local product split work in practice?

**A:** in theory we have one global roadmap and i own the brazil cut of it. in practice the global roadmap is mostly singapore-driven and i have to fight for brazil items to get attention. ahmad rashid has been good about making space for the brazil pos work. yong wei the same on loyalty. but it's a fight i have to keep having.

## Phase 5: Problems & Ideas

### Q: If a knowledge system existed that gave your team perfect context what would it do?

**A:** for me specifically — i'd want it to track every escalation across cs and product so i can show with numbers when a bug is actually big. when i bring the reconciliation bug to prioritization conversations i'm armed with maria's anecdotes and a count of two hundred eighty merchants. if i could show "here are the verbatims, here's the support ticket volume, here's the nps correlation, here's the at-risk arr", the conversation would go differently. right now i'm bringing a story and other people are bringing numbers.

### Q: Anything else?

**A:** the language gap. sometimes our brazil docs are in portuguese and the singapore team can't read them. sometimes the singapore docs are in english and a junior engineer here struggles. an agent that just translates and summarizes the relevant context across languages would change daily life for the brazil team.

### Q: Gap between leadership story and reality?

**A:** brazil is harder than the all-hands suggests. the bugs are real, the cs gap is real, the sales pipeline is softer than the headline number, and the team is stretched. i don't think wei or priya are pretending — but the public narrative leans optimistic and the reality on the ground is more work-in-progress.

## Phase 6: Calibration

### Q: How long have you been at HelixPay?

**A:** since the brasil acquisition closed, about a year and seven months. before that i was at the company we acquired for two years.
