# Results

48 actions per configuration on two tenants. Costs are measured from API usage.

| Configuration | Accuracy | Queries | Writebacks | Should-not-act | Postable bad entries | Cost / 1k actions | Without caching | Median latency | Retries |
|---|---|---|---|---|---|---|---|---|---|
| Opus 5.5, cached | **100%** | 100% | 100% | 100% | 0 | $4.47 | $13.04 | 2.1s | 0 |
| Sonnet 5.5, cached | **100%** | 100% | 100% | 100% | 0 | $2.31 | $6.60 | 1.6s | 0 |
| Haiku 5.5, cached | **98%** | 97% | 100% | 100% | 0 | $0.20 | $0.42 | 1.9s | 2 |
| Haiku 5.5, cached (rerun) | **98%** | 97% | 100% | 100% | 0 | $0.19 | $0.41 | 1.7s | 0 |
| Haiku 5.5, pruned, no cache | **96%** | 93% | 100% | 100% | 0 | $0.37 | $0.37 | 1.7s | 0 |
| Haiku 5.5 + Sonnet on retry | **100%** | 100% | 100% | 100% | 0 | $0.33 | $0.73 | 1.9s | 2 |

## What a naive grader would have reported (Haiku, query actions)

- SQL text matches the gold SQL: **0/29**
- Result correct on tenant A only: 28/29
- Result correct on both tenants (what we report): 28/29

## Run-to-run variance (Haiku, same requests, two runs)

- Cases whose chosen action or grade changed: 2/48 (w05, h16)

## Where Opus spend goes

| Component | Share |
|---|---|
| input | 4% |
| cache write | 6% |
| cache read | 21% |
| output | 69% |

- The most expensive 10% of actions are 17% of Opus spend: q01 ($0.0139), q20 ($0.0084), h04 ($0.0076), h01 ($0.0069)
- Cost per 1k actions by action kind: query $4.89, should-not-act $3.83, writeback $3.84
