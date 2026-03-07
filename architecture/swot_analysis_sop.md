# SWOT Analysis SOP

## Purpose

Deterministic, formula-driven SWOT classification for individual players and the team as a whole. No LLM guessing — every classification maps to a statistical threshold.

## Statistical Thresholds (Youth Softball / LL Majors)

### Hitting

| Stat | Strong (≥) | Weak (≤) | Direction |
|:---|:---|:---|:---|
| BA | .350 | .200 | Higher = better |
| OBP | .420 | .280 | Higher = better |
| SLG | .450 | .250 | Higher = better |
| OPS | .850 | .530 | Higher = better |
| K% | .20 | .40 | Lower = better |
| BB% | .12 | .05 | Higher = better |

### Pitching (minimum 1.0 IP to qualify)

| Stat | Strong (≤) | Weak (≥) | Direction |
|:---|:---|:---|:---|
| ERA | 3.00 | 6.00 | Lower = better |
| WHIP | 1.20 | 1.80 | Lower = better |
| K/IP | 1.0 | 0.5 | Higher = better |
| BB/IP | 0.40 | 0.80 | Lower = better |

### Fielding

| Stat | Strong (≥) | Weak (≤) |
|:---|:---|:---|
| Fielding % | .950 | .880 |

### Baserunning

| Stat | Strong (≥) | Weak (≤) |
|:---|:---|:---|
| SB Success % | .75 | .50 |

## SWOT Classification

- **Strengths**: Stats meeting or exceeding "Strong" threshold
- **Weaknesses**: Stats at or below "Weak" threshold
- **Opportunities**: Identified from opponent weaknesses that match our strengths
- **Threats**: Opponent strengths that target our weaknesses

## Calibration

These thresholds are initial estimates for youth softball. As season data accumulates, recalibrate by computing actual league-wide percentiles (75th = strong, 25th = weak).
