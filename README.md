# Tab Settle

Split shared expenses from a plain text file and see who owes whom, with the
a short list of payments that clears everyone's balance. No accounts, no app, no
network: just a text file and one Python script.

## Features

- Plain text ledger: one expense per line, `payer | amount | description | participants`.
- Exact money maths in integer cents. Totals always add up; no float rounding drift.
- Uneven splits are handled deterministically: leftover cents go to the first
  participants in alphabetical order, so the same ledger always gives the same answer.
- Names are matched case-insensitively and ignore extra spaces and accent encoding
  (`bob`, `BOB` and `Bob ` are one person).
- Strict input: a bad amount, a wrong field count, an empty name or a repeated
  participant stops the run and reports the line number. Nothing is silently guessed.
- Settle-up plan that pays the largest debts first, so it needs a short list of transfers.
- Standard library only.

## Ledger format

```
# Weekend cabin trip
Alice | 90.00 | Cabin | Alice, Bob, Carol
Bob | 45.50 | Groceries | Alice, Bob, Carol
carol | 12 | Petrol | bob, CAROL

Dave | 20 | Pizza | Dave, alice
```

- Blank lines and lines starting with `#` are ignored.
- Amounts are positive dollars with at most two decimals: `12`, `12.5`, `12.50`.
- The payer does not have to be one of the participants (paying for others is fine).

## How to run

```
python3 tab_settle.py examples/weekend-trip.txt
```

Expected output for the sample ledger:

```
Balances
  Alice                +34.83
  Bob                   -5.67
  Carol                -39.16
  Dave                 +10.00

Settle up
  Carol -> Alice: 34.83
  Carol -> Dave: 4.33
  Bob -> Dave: 5.67
```

A malformed ledger exits with status 2 and a message such as:

```
error: line 2: invalid amount 'ten' (use e.g. 12, 12.5 or 12.50)
```

## How to test

```
python3 -m pytest
```

The tests cover parsing edge cases (spacing, comments, blank lines, Unicode
names, bad amounts), uneven splits, the settle-up algorithm, error reporting,
and an end-to-end run on the sample ledger.
