# Financial Quality Reference

For the financial quality section (MECE section 3) of Atlas findings.
This is the most scrutinized section in any acquisition DD.

---

## Revenue quality tests

Run these in order. Each produces a finding or an open question.

**1. Recurring vs one-time split**
- Recurring: subscription, maintenance, contracted retainer.
- One-time: implementation fees, professional services sold per project,
  hardware, milestone payments.
- Target: recurring >= 70% for a SaaS/recurring-revenue business.
  Below 60% warrants an H risk on revenue predictability.
- Citation: contract schedule or revenue recognition footnote.

**2. Cohort retention**
- Net Revenue Retention (NRR): (start ARR + expansion - contraction -
  churn) / start ARR. Best-in-class >= 120%. Below 90% is H risk.
- Logo retention: % of customers who remained. Below 85% is H risk for
  SMB; below 95% for enterprise.
- If neither metric is in the data room, write "Cohort retention
  unavailable — request from management as closing condition."

**3. Revenue concentration**
- Compute top-1, top-3, top-10 as % of total revenue.
- Any single customer > 20% is H risk.
- Top-10 > 70% is M risk even if each individual is < 20%.

**4. Contract terms and renewal visibility**
- What % of ARR is under multi-year contracts?
- What % auto-renews vs requires active renewal?
- What is the average contract length?
- Upcoming renewals in 12 months: list each one > 5% of ARR.

**5. Revenue recognition policy**
- Is revenue recognized on delivery, over contract term, on milestone?
- Are there any unusual policies that inflate near-term revenue
  (e.g. front-loaded recognition, channel stuffing)?

---

## EBITDA bridge

Standard bridge from reported EBITDA to adjusted EBITDA. Partners
expect this; its absence is a flag.

```
Reported Net Income
+ Income tax expense
+ Depreciation and amortization
+ Interest expense
= Reported EBITDA

Adjustments (each must be documented and one-time in nature):
+ Owner compensation above market rate (document replacement cost)
+ Non-recurring legal/settlement costs
+ One-time transaction costs (but exclude recurring integration)
+ Non-cash stock compensation (if addback is standard in the sector)
- Non-recurring revenue (one-time deals that will not repeat)

= Adjusted EBITDA
```

Red flags in EBITDA addbacks:
- "Synergies" included as addbacks before deal close.
- Recurring items labeled non-recurring (e.g. annual recruiting fees).
- Rent below market rate (related-party lease).

---

## Working capital analysis

Working capital = Current Assets - Current Liabilities.

**Target working capital peg:**
- Typical acquisition includes a working capital peg at close.
  Understand the normal (trailing 12-month average) level.
- If actual WC at close is below peg, buyer gets a dollar-for-dollar
  price adjustment.

**Traps to check:**
- Deferred revenue: is it excluded from WC (standard) or included?
  Inclusion inflates WC artificially.
- Accounts receivable aging: >60 days outstanding is a quality risk.
- Inventory obsolescence (for product businesses): is reserve adequate?
- Accrued vacation / PTO liability: often omitted from target WC.

---

## Capex intensity

- Maintenance capex: required to sustain current revenue.
- Growth capex: required to grow.
- Rule of thumb: capex > 15% of revenue warrants explanation.
- For SaaS/services: capex should be near zero; high capex suggests
  the business is more infrastructure-heavy than represented.

---

## Margin bridge

```
Gross margin % (benchmark vs sector median)
- S&M as % revenue (benchmark vs rule-of-40 peers)
- R&D as % revenue
- G&A as % revenue
= EBITDA margin %
```

Flag any line item more than 5 percentage points above sector median
as a potential quality risk or cost that will normalize post-close.

---

## Common financial DD open questions (template)

If the data room does not answer these, list them as open questions:

1. Audited financial statements (last 3 fiscal years) — if only
   management accounts are available.
2. Revenue recognition policy documentation.
3. Customer-level revenue breakdown (last 2 years).
4. Cohort churn and NRR by cohort vintage.
5. Cap table with full dilution schedule.
6. Outstanding debt, leases, and off-balance-sheet obligations.
7. Working capital target calculation methodology.
