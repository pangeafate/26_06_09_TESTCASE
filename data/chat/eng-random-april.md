# #eng-random — Slack export

*Channel: #eng-random (open, ~70 members, mostly engineering across SG and BR). Export window: 2026-04-08 to 2026-04-21. This is a sample — the real channel has ~5,000 messages in this window. Selected for representative noise.*

---

**Tue Apr 08 09:14 — sara.w**
who broke the build 👀

**Tue Apr 08 09:14 — vikram.p**
not me i swear

**Tue Apr 08 09:15 — ahmad.r**
😅

**Tue Apr 08 09:18 — sara.w**
oh nvm it's the dual-write smoke test — env var rotated

**Tue Apr 08 09:18 — vikram.p**
🫠

**Tue Apr 08 11:02 — kelvin.lim**
anyone have a good ramen rec near tanjong pagar

**Tue Apr 08 11:04 — ahmad.r**
takagi is solid

**Tue Apr 08 11:06 — sara.w**
+1 takagi. but the line.

**Tue Apr 08 13:30 — luiz.f**
oi galera, qualquer um da equipe SG no escritório hoje? need a quick pair on the cutover script

**Tue Apr 08 13:33 — sara.w**
i'm in. dm me

**Tue Apr 08 14:55 — pedro.a**
tan wei ming and i pushed a fix for the merchant_id index bug, branch is `fix/merchant-id-idx-tail-cases`. PR coming in 30 min.

**Tue Apr 08 14:55 — camila.s**
🚀

**Tue Apr 08 17:11 — random_meme.gif**
*[image attachment: meme of an engineer staring at a 99.6% completion bar]*

**Tue Apr 08 17:12 — vikram.p**
😂😂😂 too real

**Wed Apr 09 08:42 — lin.x**
PSA: figma plugin for eng diagrams now installed org-wide. try it before re-drawing things in mermaid for the 12th time

**Wed Apr 09 08:50 — sara.w**
🙏 thanks lin

**Wed Apr 09 10:18 — ahmad.r**
who's on call this weekend? pagerduty showing me as primary but my calendar disagrees 🥲

**Wed Apr 09 10:20 — vikram.p**
swap with rishi if you need to. rotation has been weird since the override last month.

**Wed Apr 09 10:21 — ahmad.r**
yeah doing that now

**Wed Apr 09 14:33 — kelvin.lim**
lol someone actually sent me a fax 📠

**Wed Apr 09 14:34 — sara.w**
wait we have a fax?

**Wed Apr 09 14:34 — kelvin.lim**
the singapore office has one apparently

**Wed Apr 09 14:35 — vikram.p**
why

**Wed Apr 09 14:35 — kelvin.lim**
the bank requires it

**Wed Apr 09 14:35 — vikram.p**
2026.

**Thu Apr 10 09:00 — daniel.tan**
heads up — i'll be at all-hands next wednesday giving the confluence update. if anyone has questions you want me to address, drop them as a thread reply here.

**Thu Apr 10 09:02 — yong.w**
when can i actually start integrating loyalty against the unified merchant id

**Thu Apr 10 09:03 — daniel.tan**
working on that. honest answer — depends on the schema migration. i'll have a real date by 30 april.

**Thu Apr 10 09:04 — yong.w**
copy

**Thu Apr 10 09:05 — ahmad.r**
+1 for tap

**Thu Apr 10 11:22 — random.gif**
*[image attachment: gif of a cat slow-blinking]*

**Thu Apr 10 12:00 — sara.w**
🍔 lunch at the rooftop?

**Thu Apr 10 12:01 — kelvin.lim**
yes

**Thu Apr 10 16:41 — camila.s**
@sara.w found 4 more edge cases in the brazil legacy data — three of them are the per-location fee schedules thing, one is a really weird one where the merchant has TWO legal entities under one tax id. writing it up.

**Thu Apr 10 16:42 — sara.w**
oh no the two legal entities thing. that's a new one.

**Thu Apr 10 16:43 — vikram.p**
🫠

**Thu Apr 10 16:43 — camila.s**
brazilian tax law things

**Fri Apr 11 09:15 — lin.x**
who else is doing the marathon next month 🏃

**Fri Apr 11 09:18 — ahmad.r**
me — half. you?

**Fri Apr 11 09:18 — lin.x**
half. trying for 1:55

**Fri Apr 11 09:19 — sara.w**
running away from confluence ⏳

**Fri Apr 11 09:19 — lin.x**
😅

**Fri Apr 11 13:48 — vikram.p**
recon report: 0.42% mismatch (down from 0.51% wednesday). long tail is steeper than i hoped.

**Fri Apr 11 13:50 — camila.s**
that's 28k merchants out of ~7m. mostly per-location stuff i flagged thursday. i think we get to maybe 0.15% in 2-3 weeks but the last bit is going to be manual.

**Fri Apr 11 13:51 — vikram.p**
manual reconciliation flow is on the design doc. need someone to own.

**Fri Apr 11 13:52 — sara.w**
i'll own.

**Mon Apr 14 09:01 — daniel.tan**
all-hands wednesday at 11. if you're in brasil that's 10pm-ish so no shame in catching the recording.

**Mon Apr 14 09:30 — wendy.c**
👋 wandered in to ask — does anyone know if the new POS Self-Service kiosks support arabic locales? customer marketing for MY/ID asked me

**Mon Apr 14 09:31 — vinod.k**
not yet. on the q3 list. ahmad?

**Mon Apr 14 09:32 — ahmad.r**
correct, q3.

**Mon Apr 14 09:33 — wendy.c**
thanks 🙏

**Tue Apr 15 14:48 — sara.w**
all-hands recap: confluence "on track for end of june" 🙃 we'll see what daniel announces in 2 weeks.

**Tue Apr 15 14:49 — vikram.p**
🍿

**Tue Apr 15 14:50 — camila.s**
😅 setembro é mais realista

**Tue Apr 15 14:51 — sara.w**
agreed

**Wed Apr 16 11:22 — kelvin.lim**
btw is the WiFi extra slow today or is it just me

**Wed Apr 16 11:23 — lin.x**
just you i think

**Wed Apr 16 11:23 — kelvin.lim**
😭

**Wed Apr 16 14:00 — daniel.tan**
small announcement: tan wei ming will be back in singapore for two weeks starting may 12 to do a knowledge transfer with sara's team on the brazil legacy data. say hi if you see him.

**Wed Apr 16 14:01 — sara.w**
🇧🇷🇸🇬

**Thu Apr 17 09:11 — yong.w**
ticket HX-LOY-487 (the tap-loyalty reconciliation thing) just got escalated again by CS, customer is açaí express. anyone have updated context on the fix?

**Thu Apr 17 09:13 — ahmad.r**
fix is queued behind the merchant id work. so post-confluence. CS is sending a manual monthly reconciliation report as a workaround. beatriz has the workaround template if you need it.

**Thu Apr 17 09:14 — yong.w**
ok thanks. cs is going to push for sooner. i don't have capacity to pull it in.

**Thu Apr 17 09:14 — daniel.tan**
let me know if you need air cover, yong.

**Fri Apr 18 12:30 — random.gif**
*[image attachment: meme — engineer crying while typing on keyboard, captioned "fixing tomorrow's bug today"]*

**Fri Apr 18 12:31 — vikram.p**
🥲

**Fri Apr 18 16:42 — kelvin.lim**
is it just me or has the merchant onboarding doc been "in draft" for like 8 months

**Fri Apr 18 16:43 — sara.w**
9 months

**Fri Apr 18 16:43 — kelvin.lim**
we should fix it

**Fri Apr 18 16:44 — sara.w**
add it to the eng wiki backlog

**Mon Apr 21 09:00 — daniel.tan**
all — heads up. the WBR is today and i expect the confluence schedule reset to come out of it. official internal comms in 2 weeks. don't pre-announce.

**Mon Apr 21 09:02 — sara.w**
👍

**Mon Apr 21 09:02 — vikram.p**
👍

**Mon Apr 21 09:03 — camila.s**
👍

**Mon Apr 21 11:38 — sara.w**
WBR done. fyi — internal-only — confluence target moves to end of Q3. announcement to whole company is sequenced behind the may board meeting (may 12). until then we say "re-baseline in progress."

**Mon Apr 21 11:39 — vikram.p**
copy.

**Mon Apr 21 11:39 — camila.s**
copy

**Mon Apr 21 13:14 — kelvin.lim**
unrelated — the office aircon is broken on the south side again 🫠

**Mon Apr 21 13:15 — lin.x**
working from the cafe today, can confirm

---

*End export.*
