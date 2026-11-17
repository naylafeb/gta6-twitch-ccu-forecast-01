# GTA VI Twitch CCU forecast — make.fun entry

Forecast how many people watch Grand Theft Auto VI live on Twitch in each
hour of its release day (2026-11-19 UTC), from the first hour's print.

## Entry

`main.py` (Python 3.13, standard library only). It reads one case
`/input/<id>.in` and writes `/output/<id>.out` with five quantiles
(5/25/50/75/95%) of the concurrent-viewer count for each of hours 2..24.

## Model

Launch-day Twitch audiences share one shape: hour 1 only catches the
time zones that already unlocked, the count climbs as the US unlocks
(05:00 and 08:00 UTC), peaks in the late afternoon/evening UTC, then
decays. But the scale of that climb depends on how big hour 1 already is:
a launch whose first hour drew 800k viewers has little room left to grow,
while one that drew 20k can grow tenfold.

Per hour, the log ratio of that hour's count to the hour-1 print is fitted
by least squares on log10 of the hour-1 print, over the past launches in
the case's `comparables`:

    log(y_h / p1) = a_h + b_h * log10(p1) + noise

with b_h strongly negative at peak hours (about -2). Then:

- the slope is shrunk 25% toward zero (the raw slope overfits small
  launches and extrapolates badly to a launch bigger than every
  comparable);
- the median ratio is floored at 1.0 from hour 9 on (once the US has
  unlocked, a rolling-midnight launch does not fall back below its first
  hour);
- the spread comes from the regression residuals, scaled by 0.4 and
  floored at 0.15 log units.

Quantiles are log-normal around the fitted median.

## Practice result

Scored locally against the four practice launches' recorded hourly counts
(Marvel's Wolverine, Red Dead Redemption 2, God of War Ragnarök,
Marvel's Spider-Man 2; answers from SullyGnome's public hourly averages,
the same source the kit's cases use):

| case | pinball loss | typical miss | 90% coverage |
| ---- | -----------: | -----------: | -----------: |
| p00 Wolverine | 0.136 | 21.8% | 0.87 |
| p01 RDR2 | 0.136 | 23.2% | 0.91 |
| p02 God of War Ragnarök | 0.140 | 28.4% | 1.00 |
| p03 Spider-Man 2 | 0.210 | 41.2% | 0.74 |
| **mean** | **0.155** | | |

House persistence baseline on the same cases: **0.387** (typical miss
82.8%). The entry beats it on every practice case.

## Run

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=<kit>/input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Deterministic (identical output on re-runs), ~0.1 s per case, no network.
