"""Split shared expenses between friends and work out who pays whom.

A ledger is a plain text file with one expense per line:

    payer | amount | description | participant, participant, ...

Amounts are dollars with up to two decimal places. All money maths is done in
integer cents, so totals always add up exactly. Any line that does not match
the format is rejected with its line number instead of being guessed at.
"""

import argparse
import re
import sys
import unicodedata
from dataclasses import dataclass

AMOUNT_RE = re.compile(r"[0-9]+(\.[0-9]{1,2})?")


class LedgerError(ValueError):
    """Raised when a ledger line cannot be understood."""


@dataclass(frozen=True)
class Expense:
    payer: str
    cents: int
    description: str
    participants: tuple


def person_key(name):
    """Return the identity used to match a person. Case, accent encoding and extra spacing are ignored."""
    return unicodedata.normalize("NFC", " ".join(name.split())).casefold()


def parse_amount(text, line_no):
    """Turn '12', '12.5' or '12.50' into integer cents. Anything else is an error."""
    if not AMOUNT_RE.fullmatch(text):
        raise LedgerError(f"line {line_no}: invalid amount {text!r} (use e.g. 12, 12.5 or 12.50)")
    dollars, _, fraction = text.partition(".")
    cents = int(dollars) * 100 + int(fraction.ljust(2, "0"))
    if cents == 0:
        raise LedgerError(f"line {line_no}: amount must be greater than zero")
    return cents


def parse_participants(text, line_no):
    """Split the comma-separated participant list and reject empty or repeated names."""
    names = []
    seen = set()
    for raw in text.split(","):
        name = " ".join(raw.split())
        if not name:
            raise LedgerError(f"line {line_no}: empty name in participant list {text!r}")
        key = person_key(name)
        if key in seen:
            raise LedgerError(f"line {line_no}: {name!r} listed more than once")
        seen.add(key)
        names.append(name)
    return tuple(names)


def parse_ledger(text):
    """Parse ledger text into a list of Expense objects, skipping blanks and '#' comments."""
    expenses = []
    # A byte-order mark from Notepad or Excel would otherwise stick to the first name.
    text = text.removeprefix(chr(0xFEFF))
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = [field.strip() for field in line.split("|")]
        if len(fields) != 4:
            raise LedgerError(
                f"line {line_no}: expected 4 fields separated by '|', found {len(fields)}"
            )
        payer, amount, description, participants = fields
        if not payer:
            raise LedgerError(f"line {line_no}: payer is missing")
        if not description:
            raise LedgerError(f"line {line_no}: description is missing")
        expenses.append(
            Expense(
                payer=" ".join(payer.split()),
                cents=parse_amount(amount, line_no),
                description=description,
                participants=parse_participants(participants, line_no),
            )
        )
    return expenses


def split_cents(total, count):
    """Divide total cents into count shares. The leftover cents go to the first
    shares in sorted order, so the same ledger always gives the same result."""
    base, remainder = divmod(total, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


def compute_balances(expenses):
    """Return {person_key: (display_name, net_cents)}. Positive means owed money."""
    names = {}
    net = {}

    def add(name, delta):
        key = person_key(name)
        names.setdefault(key, name)
        net[key] = net.get(key, 0) + delta

    for expense in expenses:
        add(expense.payer, expense.cents)
        ordered = sorted(expense.participants, key=person_key)
        for name, share in zip(ordered, split_cents(expense.cents, len(ordered))):
            add(name, -share)

    return {key: (names[key], net[key]) for key in net}


def settle(balances):
    """Return a list of (debtor, creditor, cents) transfers that clear every balance.

    Largest debtors pay largest creditors first, which keeps the number of
    transfers short. This is a greedy plan, not a guaranteed minimum.
    Ties are broken by name so the output is repeatable.
    """
    if sum(cents for _, cents in balances.values()) != 0:
        raise AssertionError("balances do not sum to zero")
    creditors = sorted(
        ([name, cents] for name, cents in balances.values() if cents > 0),
        key=lambda item: (-item[1], person_key(item[0])),
    )
    debtors = sorted(
        ([name, -cents] for name, cents in balances.values() if cents < 0),
        key=lambda item: (-item[1], person_key(item[0])),
    )
    transfers = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        debtor, owes = debtors[i]
        creditor, due = creditors[j]
        amount = min(owes, due)
        transfers.append((debtor, creditor, amount))
        debtors[i][1] -= amount
        creditors[j][1] -= amount
        if debtors[i][1] == 0:
            i += 1
        if creditors[j][1] == 0:
            j += 1
    return transfers


def format_cents(cents):
    """Format cents as dollars, e.g. 1250 -> '12.50', -5 -> '-0.05'."""
    sign = "-" if cents < 0 else ""
    dollars, remainder = divmod(abs(cents), 100)
    return f"{sign}{dollars}.{remainder:02d}"


def format_signed(cents):
    """Like format_cents, but with an explicit '+' for positive amounts."""
    return ("+" if cents > 0 else "") + format_cents(cents)


def format_report(expenses):
    """Build the human-readable balance and settle-up report."""
    if not expenses:
        return "No expenses recorded."
    balances = compute_balances(expenses)
    lines = ["Balances"]
    for name, cents in sorted(balances.values(), key=lambda item: person_key(item[0])):
        lines.append(f"  {name:<16} {format_signed(cents):>10}")
    transfers = settle(balances)
    lines.append("")
    if not transfers:
        lines.append("Everyone is square. Nothing to settle.")
    else:
        lines.append("Settle up")
        for debtor, creditor, cents in transfers:
            lines.append(f"  {debtor} -> {creditor}: {format_cents(cents)}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Split shared expenses and work out a short list of payments to settle up."
    )
    parser.add_argument("ledger", help="path to a ledger text file")
    args = parser.parse_args(argv)
    try:
        with open(args.ledger, encoding="utf-8-sig") as handle:
            text = handle.read()
    except OSError as error:
        print(f"error: cannot read {args.ledger}: {error.strerror}", file=sys.stderr)
        return 2
    try:
        expenses = parse_ledger(text)
    except LedgerError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(format_report(expenses))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
