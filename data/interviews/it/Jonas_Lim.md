# Interview: Jonas Lim

## Meta

- **Name:** Jonas Lim
- **Role:** IT Manager
- **Department:** IT
- **Email:** jonas.lim@helixpay.io
- **Started:** 2026-04-12 11:00
- **Completed:** 2026-04-12 11:34
- **Status:** completed
- **Language:** en

## Phase 1: Role & Daily Work

### Q: Jonas, give me the short version — what do you own.

**A:** endpoint management, sso, internal tooling, and vendor procurement across both geos. i report to priya raman. one direct report — carlos mendes in brasil, he runs local it for sao paulo and the rio office. so two of us total, one in each geo, covering two hundred seventy five people. lean.

### Q: What does your week look like.

**A:** mondays i do a sync with carlos, half an hour. rest of the week is a mix of tickets, the okta migration project, and whatever procurement conversation is on. tuesdays i tend to have the heaviest vendor calls.

## Phase 2: Knowledge & Expertise

### Q: Biggest pain point.

**A:** saas sprawl. helixpay has forty seven saas tools right now that i know about — there are probably a few i don't know about because someone in marketing expensed them. there's a lot of overlap. we have two project tools, three different note-taking apps in active use, two different scheduling tools. and i can't see total saas spend in one place. finance has a piece of it, i have a piece of it from the procurement side, no one has the whole picture. that's the thing i'd most like to fix this year.

### Q: How are you tackling it.

**A:** slowly. i'm building a vendor inventory in a notion database and tagging each tool by category, owner, and renewal date. once that's complete i can have the consolidation conversation with finance and with the department heads. probably two months out from having the full picture.

### Q: Tell me about the sso migration.

**A:** we started moving everything to okta in q4 last year. about halfway done. the easy stuff is done — google workspace, slack, github, lever, lattice, the standard saas. the harder stuff is the long tail of smaller tools where the saml setup is fiddly or where the vendor charges extra for sso. and there's a specific complication with the two crms.

### Q: Tell me about that.

**A:** so sea uses hubspot and brasil uses pipedrive. both are sso'd through okta but differently. hubspot was set up after the okta rollout so it uses our standard sso pattern with okta as the idp and group-based provisioning. pipedrive in brasil was set up before okta — back when sao paulo was using google sso directly — and we layered okta on top later, which means the sso flow goes through an extra hop and the user provisioning is still partly manual. it works but it's not clean. we'll fix it when brasil migrates to hubspot, which is supposed to start may first. probably easier to just do the okta integration cleanly on the new instance than to fix the pipedrive one for two months of remaining life.

## Phase 3: Processes & Tools

### Q: How does the sg-brasil split work day to day.

**A:** carlos handles all local stuff in brasil — laptop provisioning, office network, anything that needs hands on the ground in sao paulo. i handle the global tools and the strategic stuff. we sync once a week, async slack the rest of the time. it works but it's thin. if either of us is on leave the other one is covering everything.

### Q: What's your ticket volume.

**A:** maybe forty to sixty tickets a week between the two of us. spike on monday mornings and after any company-wide change. nothing crazy.

## Phase 5: Problems & Ideas

### Q: If you had a magic budget for one thing what would you do.

**A:** a saas management platform — torii or zylo or one of those — that connects to our spend and our identity provider and gives me automatic discovery plus utilization data. right now i'm building that picture by hand and it's going to be stale the day i finish it.

### Q: What about the codos work — does any of it touch you.

**A:** indirectly. priya raman has mentioned it. mostly it sits at the application layer not the infra layer so it's not on my plate but i'd expect to be involved when it comes to identity and access — agents acting on behalf of users is a permissions question and that's my territory. i'd want to be in those conversations early.

### Q: How worried are you about shadow it given the tool sprawl.

## Phase 6: Calibration

### Q: How long have you been at HelixPay?

**A:** four years. one of the longer-tenured people here. i joined when we were forty people and i was the first dedicated it hire.
