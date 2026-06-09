# Weekly Business Review — April 21, 2026

*Owner: Priya Raman. Attendees: Wei, Boon Hock, Sofia, Arjun, Daniel, Marco, Hannah, Rajesh, Sarah. Format: 60-min Tuesday sync. Notes by Priya, lightly edited.*

## TL;DR

- April month-to-date revenue: SGD 4.1M. Tracking to ~12.6M for the quarter against a 17M Q2 target. **We are 26% behind pace.**
- Brasil April pipeline coverage is 1.4x. SEA is 2.6x. Brasil is the problem.
- Confluence: **slipping. Working assumption is now end of Q3 (September), not end of Q2 (June).** Daniel and Arjun acknowledged in the meeting. Communication plan to the company TBD — we agreed not to surface this in next all-hands until we have a re-baselined plan.
- NPS: aggregate (all segments, all geos) is **47**. SEA enterprise is 62 (the number we used at all-hands). Brazil SMB is 31. Marco's team is concerned about Brazil tier-2 churn risk.
- Three enterprise churns confirmed in March (Lazada SG midmarket, Cosmos Hotels, Banco Verde — source sheet not included in this data drop). Combined ARR loss SGD 340K.
- Codos engagement begins this week. Priya owning.

## Revenue

- Apr MTD 4.1M (rev recognized).
- Forecast for April: 4.6M to 4.9M. Last-week pull-in unlikely to move it materially.
- May commit: Sofia 5.0M. Stretch 5.6M.
- June commit: pending — Sofia waiting on Brasil pipeline cleanup before committing.
- **Question for Wei**: do we revise Q2 target down or hold and miss?

## Brasil deep-dive

- Q1 revenue R$22M against R$28M target. April pacing R$6.8M against R$9.5M target.
- Maria Silva flagging 4 reps under-performing on activity (calls/week below 60% of target). Performance plans started for two.
- CRM migration not yet started in Brasil. Pipedrive remains the system of record. Sofia commit: HubSpot migration for Brasil starts May 1, completes end of June. (Note: this means Sofia's all-hands statement of "78% of pipeline in HubSpot" is SEA-weighted — a HQ-only number. Worth flagging in the next exec write-up.)
- Tap product attach rate 11% in Brasil, target was 25%. Beatriz investigating. Hypothesis: SMB merchants don't use the upsell flow.

## Confluence — schedule reset

Daniel walked us through the merchant_id schema migration status. Current state: the schema design landed in March, the migration script is written but the dual-write phase has been running for three weeks and there are reconciliation gaps (~0.4% of records mismatch between the two systems). Until that's at zero we can't cut over. Estimate to zero: 4–6 weeks. After cutover, the dependent services (POS, Loyalty, fraud) need to be re-pointed and re-tested — another 6–8 weeks.

So **realistic Confluence GA: late August to mid September**. Daniel's words: "I'd commit to September 30 if you held me to a number."

We agreed:
1. Daniel re-baselines the plan formally by April 30.
2. Wei communicates to the board at the May meeting (May 12).
3. Internal communication held until re-baseline is signed off.
4. Codos work that depended on post-Confluence platform should plan for Q4, not Q3.

Wei was not happy. Reasonable.

## NPS

Marco shared Q1 NPS breakdown:

| Segment              | NPS | n  | vs Q4 |
|----------------------|-----|-----|------|
| SEA enterprise       | 62  | 47 | +9   |
| SEA SMB              | 41  | 312 | +2  |
| Brasil enterprise    | 53  | 19 | -3   |
| Brasil SMB           | 31  | 408 | -8  |
| **Aggregate**        | **47** | **786** | **+1** |

The all-hands number (62) was the SEA-enterprise figure. Marco wants us to lead with the aggregate number going forward; Sofia wants to keep the segmented view because the enterprise number is the fundraising number. Tabled — Wei to decide.

Brasil SMB drop of 8 points is real and concerning. Marco's working theory: support response time degraded after the Q1 case-volume spike when we lost two CSMs to attrition.

## Churn and at-risk

- 3 enterprise churns in Q1 (Lazada SG midmarket — pricing, Cosmos Hotels — moved to competitor, Banco Verde — internal bank decision unrelated to product). ARR impact SGD 340K.
- Tier-2 SMB at-risk in Brasil: Maria Santos's team flagging 14 accounts with deteriorating engagement. Combined ARR ~R$1.1M. Save plan in motion.

## Hiring

- Sarah Ng: Q2 hiring plan pre-Confluence-slip was 18 net adds (12 eng, 4 sales, 2 CS). Reviewing.
- Decision: pause new eng hires for SEA until Confluence re-baseline is signed (April 30). Brasil eng hiring continues as planned (3 open reqs).
- 2 Brasil CSMs to be filled by end of May.

## Action items

| Item                                                         | Owner   | Due     |
|--------------------------------------------------------------|---------|---------|
| Re-baseline Confluence plan with milestones and dependencies | Daniel  | Apr 30  |
| Brasil pipeline cleanup; commit June number                  | Sofia   | May 5   |
| Aggregate vs segment NPS framing — write up for Wei          | Marco   | Apr 28  |
| Codos kickoff and scope alignment                            | Priya   | Apr 25  |
| Tap-attach hypothesis testing                                | Beatriz | May 15  |
| Q2 target revision proposal                                  | Boon    | Apr 30  |

---
*Recorded in `weekly-review/` in Drive. Next sync April 28.*
