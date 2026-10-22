# Accounting cutover readiness for a multifamily operator

```
python3 run.py      # stdlib only, under a second
```

A synthetic operator moving property accounting to a new platform: 60 properties, 15,707 units,
14,827 resident records, 91,498 ledger lines at one cutover date. Each property has resident
ledgers for the cutover month, security and pet deposits held, the legacy charge-code table, a
legacy GL trial balance and bank balances. Fixed seed, no real operator, resident or bank. Failures
are injected with ground truth, so every check is scored against what is actually wrong.

The question: which properties can cut over today, and what does a migration sign-off miss if it
only looks at the numbers people usually look at?

## The checks people sign off on all pass

| check | result |
|---|---|
| trial balance debits = credits | 60 of 60 properties |
| portfolio AR, GL vs resident ledgers | -0.29% |
| portfolio deposits, GL vs resident ledgers | -1.61% |

Under those numbers, **11 of 60 properties** are clean enough to cut over. The other 49 have at
least one exception, and 16 have two or three.

## What sits underneath

**Pet deposits booked as income.** At 9 properties a local charge-code override posts PETDEP to a
revenue account instead of the deposit liability. $230,300 is owed back to residents at move-out
and the GL does not know it. Comparing deposits held on resident ledgers to GL 2210 by property
finds all 9. The portfolio deposit total is only 1.6% off, because the other 51 properties are fine.

**Deposit cash in the operating account.** At 4 properties the liability is right but the cash
backing it is in operating cash, not the deposit trust account: $1,028,148 short. The trial balance
is perfect at all four. Only a liability-to-trust-cash check per property sees it.

**Control-account entries with no resident behind them.** 7 properties have write-offs or
reversals posted straight to AR control. Gross $114,630, but they net to -$17,145 across the
portfolio, which is why total AR is within 0.3%. A per-property tie-out of AR control to the sum of
resident balances finds all 7.

**Transfers that duplicated a deposit.** 64 residents moved units and were re-keyed as a new
record with the deposit re-entered instead of moved. Resident ledgers carry $83,632 of deposits the
GL never had. Exact name matching finds 40 of the 64; 24 were re-typed with different case or
spacing. Normalizing the name finds all 64.

**Charge codes missing from the mapping file.** Three codes created locally at 11 properties
(AMENX, STOR2, UTILADJ) are not in the mapping the migration team was handed: 647 lines, $55,781.
Nothing errors. They just don't arrive.

**Net AR migrated as AR.** The legacy control account is net of resident credits. Gross AR is
$6.73M and prepaid rent is $0.84M. Loading the $5.89M net as receivables drops $842,796 of
prepaid-rent liability and turns paid-ahead residents into zero balances.

## What I got wrong first

My first run had net AR **negative**: I had 5% of residents paying a full extra month, which no
real book looks like, and every AR number downstream was meaningless. And my first duplicate check
matched exact names, so it scored 64 of 64 only because the generator had copied names exactly.
Once some transfers were re-typed the way people actually key them, exact matching fell to 40.

## Files

| file | what it does |
|---|---|
| `world.py` | builds the operator, resident ledgers, deposits, charge codes and legacy trial balance, and records which failures were injected where |
| `run.py` | runs the eight checks, scores each against ground truth, prints which properties are ready |
