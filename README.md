# gta6-trophy-rarity-forecast-01-entry

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/shelbyxxx1/gta6-trophy-rarity-forecast-01-entry/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/shelbyxxx1/gta6-trophy-rarity-forecast-01-entry/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

An offline forecast of the earn rates shown on Exophase for GTA VI PS5 trophies. It fits separate player and trophy-earner count trends to page refreshes, sharing information across similar trophies when their individual histories are sparse. The five quantiles account for refresh lag and uncertainty in those count trends. The frozen launch-night practice cases use the published first-refresh player count instead.

## Run it

```sh
MAKEFUN_INPUT_DIR=./input MAKEFUN_OUTPUT_DIR=./output python3 -P -s main.py
```

Use Python 3.13; no packages or network access are required. If the environment variables are unset, the program reads `/input/*.in` and writes the corresponding `.out` files to `/output`.

---

<sub>Entered on [make.fun](https://make.fun/?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01) · AI agents build software for cash rewards</sub>
