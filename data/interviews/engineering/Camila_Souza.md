# Interview: Camila Souza

## Meta

- **Name:** Camila Souza
- **Role:** Senior Backend Engineer, Payments
- **Department:** Engineering / Brasil
- **Email:** camila.souza@helixpay.io
- **Status:** completed
- **Started:** 2026-04-11 09:15
- **Completed:** 2026-04-11 10:28
- **Language:** en (mixed PT)

## Phase 1: Role & Daily Work

### Q: Camila — tell me what you own.

**A:** i am senior backend on payments module here in são paulo, i report to luiz. i've been with this team three years but the company before helixpay acquired us i was there five years so really i know this codebase like, tipo assim, more than anyone except maybe pedro. on confluence i am the person who knows the brazil merchant data, the history of it, why things are the way they are. so a lot of my time now is explaining brazil to singapore and explaining singapore to brazil.

### Q: A typical day.

**A:** stand-up nine am são paulo. then usually i am in the migration work — reviewing reconciliation cases that the script flagged that need a human, writing rules for the ones we can automate. afternoon i overlap with sara and vikram in singapore, sometimes daniel joins. that overlap is short, maybe two hours, and we try to make it count. evenings i mostly stop but sometimes there is a thing.

### Q: Who do you work with most.

**A:** sara and vikram on the singapore side, luiz here, pedro on the payments code. and tan wei ming who came over from singapore in february to help us — he is good, helps a lot with bridging singapore conventions, but the language barrier is real. he speaks no portuguese and most of the team here we speak english at work but the deeper conversations the historical stuff happens in portuguese naturally. so things get lost.

### Q: Quick clarification — pedro is pedro almeida right? same surname as sofia?

**A:** yes pedro almeida. não é parente da sofia, mesmo sobrenome só. very common name here. people confuse them all the time, even internally. pedro is engineering, sofia is the cro, completely different.

## Phase 2: Knowledge & Expertise

### Q: Tell me about the brazil merchant_id history. The real story.

**A:** olha só, this is going to take a minute. so the company that became helixpay brasil, before helixpay acquired us in twenty twenty four, we had ourselves acquired two other smaller companies. one was a payment processor focused on retail chains, the other was more focused on hospitality. each of them had their own database their own way of thinking about what a merchant is. the retail one used per-location identifiers because that is how retail works in brazil — you have a chain with twenty stores, each store has its own cnpj sometimes, its own bank account, its own pos terminal. so for them merchant equals location. the hospitality one was more per-legal-entity, like singapore, because hotels usually have one legal entity per property group. and then we built our own thing on top that was kind of a mix.

### Q: Three models in one database.

**A:** três modelos sim. the per-location one, the per-cnpj one which is sort of legal entity but not exactly because cnpj has its own complications in brazil, and the hybrid we built. most of the production traffic now goes through the per-location model because that is what most brazilian merchants expect. but the data is all there from all three. when sara's team designed the unified schema with one merchant_id per legal entity that is the singapore convention and it makes sense for sea, mas a gente sabe que for brazil you are throwing away a lot of context. like a chain with thirty stores has thirty different banking setups in some cases and we have to pick one. or build rules that pick the right one per transaction which is what we are doing for some merchants.

### Q: That sounds like it took a while to figure out.

**A:** week two of implementation. we should have caught it in design but we didn't. it is partly that the design review happened in singapore and the brazil context was not in the room enough. tipo, i was in the meeting but a one hour meeting is not enough to communicate eight years of history in two acquired companies plus our own.

### Q: Where does the historical knowledge of all this live.

**A:** in my head mostly. some in pedro. luiz knows the high level. there are some old documents in portuguese from before the helixpay acquisition that nobody on the singapore side has read because they are in portuguese and not translated. we should translate them. we have not. that is one of my frustrations honestly — none of this is being captured anywhere systematic. when i leave this company someday all of this leaves with me and pedro.

## Phase 3: Processes & Tools

### Q: How is communication with singapore working.

**A:** it is better than it was. six months ago it was bad. now we have a daily sync sara runs, thirty minutes, agenda. but the time zones are brutal. by the time i see something sara wrote in slack it is already her next morning so a question and an answer takes a full day round trip. mas a gente faz funcionar.

### Q: Tools.

**A:** the same as singapore. linear, github, datadog. we also have an internal portal we built before helixpay acquired us for merchant onboarding here in brazil — that is going away as part of confluence which honestly i am sad about because it works well for the brazilian context but i understand why we need to retire it.

### Q: How is luiz to work for.

**A:** good. he protects the team from a lot of the noise. he is also the person who has to translate brazil reality up to daniel which is hard.

## Phase 5: Problems & Ideas

### Q: If you had a magic system that knew everything about how the brazil codebase works what would you do with it.

**A:** the first thing — i would point sara and vikram at it and say go ask it instead of asking me. half my week is answering questions that have answers if you know where to look. the second thing is the historical stuff. those old portuguese documents the migration scripts from when we acquired the other two companies, the slack threads from twenty twenty two when we made certain schema decisions — if all of that was searchable and a new engineer could ask "why does this table have this weird column" and get the actual answer with the actual context, that would be huge. right now the only way to get that answer is ask me.

### Q: Anything else.

**A:** the language thing. if a system could let tan wei ming and the rest of the singapore team read our portuguese docs and our portuguese slack threads with translation that is faithful — not just google translate, faithful — that would help a lot. and the other way too, our junior engineers reading the singapore design docs.

### Q: What's the biggest frustration day to day.

**A:** being the bottleneck. i don't want to be the only person who knows the brazil history. it is not good for me and not good for the company.

## Phase 6: Calibration

### Q: How long with the company total counting pre-acquisition.

**A:** eight years. three under helixpay, five before.

### Q: Anything you want leadership to know.

**A:** that the brazil eng team is not slow. we are working on a harder problem than singapore is and the harder problem is the legacy data not the code. the code we can write fast. the data we have to be careful with because it is real merchants with real money. and that pedro and tan wei ming and the others here are very good engineers.
