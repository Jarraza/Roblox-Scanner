# Roblox-Scanner

A price scanner for Roblox limiteds. For every limited listed on
Rolimons, it reads the current lowest resale price from Roblox's public catalog
endpoint and reports it next to the Rolimons value, highlighting items listed
below their reference price.
## Requirements

- Python 3.10+
- No dependencies (standard library only)

## Usage

```bash
python scanner.py                      # scan the whole catalogue once
python scanner.py --limit 50           # first 50 items only
python scanner.py --min-discount 20    # only show items >=20% under reference
python scanner.py --csv out.csv        # also write results to CSV
python scanner.py --valued-only        # skip items Rolimons hasn't valued
python scanner.py --loop               # re scan continuously until Ctrl+C
```

`--limit N` - all - scan only the first N items

`--delay S` - `0.3` - seconds between catalog calls 

`--timeout S` - `15.0` - per-request timeout 

`--min-discount P` - `0.0` - only show rows at least P% under reference 

`--valued-only` - off - skip items with no Rolimons value 

`--csv PATH` - — - also write full results to CSV 

`--loop` - off - re-scan continuously instead of exiting once 

`--interval S` - `60.0` - seconds between loop cycles 

`--rolimons-refresh S` - `300.0` - seconds between Rolimons refreshes while looping 



