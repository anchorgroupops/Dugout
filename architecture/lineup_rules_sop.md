# Lineup Rules SOP

## Purpose

Generate PCLL-compliant batting orders that maximize run production while respecting mandatory play requirements.

## PCLL Mandatory Play Constraints

1. **Every rostered player** must receive at least **1 at-bat** per game.
2. **Every rostered player** must play at least **6 consecutive defensive outs** (~2 innings).
3. **Continuous batting order** is used — all players bat.

## Batting Order Slot Logic

| Slot | Role | Selection Criteria |
|:---|:---|:---|
| 1st | Leadoff | Highest OBP + speed composite |
| 2nd | Contact | Best BA × (1 - K%) composite |
| 3rd | Best Hitter | Highest overall batting score |
| 4th | Cleanup | Second-highest batting score (power-weighted) |
| 5th | Run Producer | Third-highest batting score |
| 6-N | Depth | Remaining players in descending score order |

## Scoring Formulas

### Balanced Strategy
`score = (OBP × 40) + (SLG × 25) + ((1 - K%) × 20) + (SB_rate × 15)`

### Aggressive Strategy
`score = (SLG × 35) + (OBP × 25) + (RBI_rate × 25) + ((1 - K%) × 15)`

### Development Strategy
`score = (OBP × 30) + (BA × 30) + ((1 - K%) × 25) + (SB_rate × 15)`
Then flatten: `final = score × 0.7 + 0.3 × 10`

## Validation

Every generated lineup MUST pass:
- All roster players are included in batting order
- No duplicate entries
- Slot numbers are sequential
