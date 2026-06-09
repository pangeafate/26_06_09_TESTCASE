From: Maria Santos <maria.santos@helixpay.io>
To: Marco Bianchi <marco.b@helixpay.io>
Cc: Beatriz Oliveira <beatriz@helixpay.io>; Ahmad Rashid <ahmad.rashid@helixpay.io>; Camila Souza <camila.souza@helixpay.io>
Date: Mon, 14 Apr 2026 19:40 -03:00
Subject: FW: [URGENT] reconciliation report errors — Açaí Express SP — at risk

Marco — see below. Forwarding for visibility. The customer is patient but they're escalating
internally to their CFO, who I expect will write back to me directly. Workaround is in place
(monthly manual recon by my team) but they want a hard fix date and we don't have one.

This is the 11th time I've forwarded an Açaí-Express-style ticket since November.
Beatriz, Ahmad, Camila — we've talked about this. Same pattern. ETA on HX-LOY-487?

— Maria

---------- Forwarded message ----------

From: Lucas Andrade <lucas@acaiexpress.com.br>
To: Maria Santos <maria.santos@helixpay.io>
Date: Mon, 14 Apr 2026 18:12 -03:00
Subject: [URGENT] reconciliation report errors — Açaí Express SP

Olá Maria,

Estou com problema sério no relatório de conciliação dos meses de fevereiro e março.
Os totais que aparecem no portal HelixPay não batem com o que o banco depositou.
A diferença de março é R$ 2.140,00 — exatamente o valor de redenções de Loyalty,
que aparenta ser contado duas vezes na coluna Net.

Vocês me mandaram um ajuste manual em janeiro e disseram que o fix do app sairia
"em poucas semanas". Já são quatro meses. Meu contador está perdendo tempo a cada
fechamento e a gente já discutiu de migrar para outro provedor por causa disso.

Preciso de uma data de correção firme até quarta-feira. Caso contrário vou levar
ao CFO da empresa que vai entrar em contato direto com o time comercial de vocês.

Anexei o relatório de conciliação de março com os números marcados.

Lucas Andrade
Head of Finance, Açaí Express SP

[Attachment: reconciliacao-marco-2026.pdf — 2 pages]

---------- End forwarded message ----------

---

From: Marco Bianchi <marco.b@helixpay.io>
To: Maria Santos <maria.santos@helixpay.io>
Cc: Beatriz Oliveira <beatriz@helixpay.io>; Ahmad Rashid <ahmad.rashid@helixpay.io>;
    Camila Souza <camila.souza@helixpay.io>; Hannah Park <hannah@helixpay.io>;
    Daniel Tan <daniel.tan@helixpay.io>
Date: Tue, 15 Apr 2026 08:14 +08:00
Subject: Re: FW: [URGENT] reconciliation report errors — Açaí Express SP — at risk

Looping in Hannah and Daniel.

This is the issue we've been talking about for months. HX-LOY-487. Customer-visible defect
in the Tap + Loyalty integration that systematically overstates Net by the value of Loyalty
redemptions for any merchant using both products. ~280 affected merchants. Manual workaround
in place (monthly recon emails from CSM team) but it doesn't scale and customers are losing
patience.

Maria — please reassure Lucas that we have an active workaround and the fix is on the
roadmap. Don't commit to a date.

Hannah, Daniel — I want a real date. Where does this sit relative to Confluence?

— Marco

---

From: Hannah Park <hannah@helixpay.io>
To: Marco Bianchi <marco.b@helixpay.io>
Cc: [thread]
Date: Tue, 15 Apr 2026 09:48 +08:00
Subject: Re: FW: [URGENT] reconciliation report errors — Açaí Express SP — at risk

Marco — the honest answer is the fix sits behind the merchant_id schema migration
because the root cause is in how Loyalty references merchants in the legacy Brasil
schema vs the unified one we're moving to. Until we cut over we're patching around
the symptom. Camila and Ahmad's teams have a hotfix design but they're not staffed
to run it in parallel with the Confluence work.

If we want it sooner we need to make a tradeoff. Daniel?

— Hannah

---

From: Daniel Tan <daniel.tan@helixpay.io>
To: Hannah Park <hannah@helixpay.io>
Cc: [thread]
Date: Tue, 15 Apr 2026 11:02 +08:00
Subject: Re: FW: [URGENT] reconciliation report errors — Açaí Express SP — at risk

I can free Camila for 2 weeks to run the hotfix design through to merge. That pushes
the schema migration completion by ~3 weeks. Net of net, the unified merchant ID work
takes longer but ~280 merchants stop seeing wrong numbers in their reports. I think
that's the right tradeoff but it's a leadership call — the schedule slip cascades into
Confluence GA.

If we hold the line, the fix lands roughly when Confluence GA lands (late August / mid
September). 4-5 months of monthly manual recon between now and then.

Let me know.

— Daniel

---

From: Marco Bianchi <marco.b@helixpay.io>
To: Daniel Tan <daniel.tan@helixpay.io>
Cc: [thread]; Priya Raman <priya@helixpay.io>; Sofia Almeida <sofia.almeida@helixpay.io>
Date: Wed, 16 Apr 2026 09:30 +08:00
Subject: Re: FW: [URGENT] reconciliation report errors — Açaí Express SP — at risk

Looping Priya and Sofia. This needs an exec call.

The R$1.1M Brasil tier-2 ARR at risk that we discussed in last week's WBR — a meaningful
chunk of it is this issue. If we hold the line, I think we lose 2-3 of the 14 at-risk
accounts before Confluence ships.

Maria has held them so far. She's a magician but it's not sustainable.

— Marco

---

From: Priya Raman <priya@helixpay.io>
To: Marco Bianchi <marco.b@helixpay.io>
Cc: [thread]
Date: Wed, 16 Apr 2026 14:20 +08:00
Subject: Re: FW: [URGENT] reconciliation report errors — Açaí Express SP — at risk

Tabling for the WBR on April 21. Everyone bring numbers. Daniel — bring the exact
schedule impact of the hotfix in/out. Marco — bring an updated at-risk impact. Hannah —
recommendation.

— Priya
