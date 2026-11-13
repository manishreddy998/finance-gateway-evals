# Recommendation: which model should run the gateway?

*Written for finance and product leadership. Numbers come from `results/summary.md`.*

## The decision

Today every gateway action runs on the largest model. On our 48-case regression suite, a smaller model
answering first, with a mid-size model taking over only when the small model's query fails, was **just as
accurate (100%)** and cost **$0.33 per 1,000 actions instead of $4.47**, about 13 times less.

## What I recommend

1. **Ship it for read queries, behind a shadow period.** For two weeks, run the routed policy alongside the
   current model on real traffic, compare answers, and switch when they agree on at least 98% of queries.
2. **Do not move writebacks yet.** The small model got all 7 entries it had to post right, and declined all 12 requests
   it should not have acted on, but that is far too few to trust for entries that land in a customer's ledger. Keep writebacks on the mid-size model until the suite
   has at least 200 writeback cases, including real (anonymized) customer requests.
3. **Turn on prompt caching everywhere now.** It cuts cost by about two thirds on every model, changes no
   answers, and needs no evaluation to ship.
4. **Do not shorten prompts to save money.** Trimming the prompt per question made it more expensive (it
   breaks caching) and less accurate (96%).

## What this means for pricing

At 100,000 actions a month, the current setup costs about **$447**; the routed policy about **$33**. The
saving per action is large enough to change what a credit should cost, so the per-action cost should be
re-measured monthly and fed into plan allowances.

## What could make this wrong

- **The suite is small and synthetic.** 48 cases on a test ledger. Real questions are messier. The shadow
  period exists to catch this.
- **I chose the routing rule after seeing these results.** It needs to be confirmed on cases it was not
  tuned on before it is trusted.
- **Models change.** Every model or prompt change should re-run the suite and produce a new version of
  this page before shipping.

## Safety

No configuration produced a journal entry that the gateway would have posted wrongly. Separately from the
model, the gateway itself rejects entries that don't balance, use inactive or missing accounts, or touch
closed periods, so a model mistake there is caught before it reaches the ledger.
