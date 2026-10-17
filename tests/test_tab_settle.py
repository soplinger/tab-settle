import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import tab_settle  # noqa: E402
from tab_settle import LedgerError, compute_balances, format_report, parse_ledger, settle  # noqa: E402

SAMPLE = os.path.join(ROOT, "examples", "weekend-trip.txt")


def test_parse_reads_fields_and_converts_amounts_to_cents():
    expenses = parse_ledger("Alice | 90.5 | Cabin | Alice, Bob\n")
    assert len(expenses) == 1
    assert expenses[0].payer == "Alice"
    assert expenses[0].cents == 9050
    assert expenses[0].description == "Cabin"
    assert expenses[0].participants == ("Alice", "Bob")


@pytest.mark.parametrize("text, cents", [("12", 1200), ("12.5", 1250), ("12.50", 1250), ("0.01", 1)])
def test_accepted_amount_forms(text, cents):
    expenses = parse_ledger(f"A | {text} | x | A\n")
    assert expenses[0].cents == cents


@pytest.mark.parametrize("amount", ["$12", "12.504", "-5", "0", "0.00", "1,000", ".5", "12.", "abc"])
def test_bad_amounts_are_rejected_with_line_number(amount):
    with pytest.raises(LedgerError, match=r"line 2: .*amount"):
        parse_ledger(f"A | 1 | ok | A\nA | {amount} | x | A\n")


def test_comments_blank_lines_and_extra_spacing_are_ignored():
    text = "\n# trip\n   \n  Alice   |  10  |  Lunch  |  Alice ,  Bob  \n\n"
    expenses = parse_ledger(text)
    assert len(expenses) == 1
    assert expenses[0].payer == "Alice"
    assert expenses[0].participants == ("Alice", "Bob")


def test_wrong_field_count_names_the_line():
    with pytest.raises(LedgerError, match="line 1: expected 4 fields.*found 3"):
        parse_ledger("Alice | 10 | Lunch\n")


def test_empty_participant_entry_is_an_error():
    with pytest.raises(LedgerError, match="line 1: empty name"):
        parse_ledger("Alice | 10 | Lunch | Alice,,Bob\n")


def test_participant_repeated_in_any_case_is_an_error():
    with pytest.raises(LedgerError, match="listed more than once"):
        parse_ledger("Alice | 10 | Lunch | bob, BOB\n")


def test_missing_payer_or_description_is_an_error():
    with pytest.raises(LedgerError, match="payer is missing"):
        parse_ledger(" | 10 | Lunch | Alice\n")
    with pytest.raises(LedgerError, match="description is missing"):
        parse_ledger("Alice | 10 |  | Alice\n")


def test_names_match_case_insensitively_and_ignore_inner_spacing():
    expenses = parse_ledger("Mary  Ann | 10 | a | MARY ANN, bob\nmary ann | 10 | b | Bob, mary ann\n")
    balances = compute_balances(expenses)
    assert len(balances) == 2
    # Each expense: payer +10.00, each of the two participants -5.00.
    assert balances[tab_settle.person_key("mary ann")] == ("Mary Ann", 1000)
    assert balances[tab_settle.person_key("bob")] == ("bob", -1000)


def test_unicode_names_match_case_insensitively():
    expenses = parse_ledger("José | 10 | a | José, Zoë\nZOË | 10 | b | josé, zoë\n")
    balances = compute_balances(expenses)
    assert len(balances) == 2
    assert all(cents == 0 for _, cents in balances.values())


def test_uneven_split_gives_leftover_cents_to_first_names_in_order():
    # 45.50 split three ways is 1517, 1517, 1516 cents for alice, bob, carol.
    expenses = parse_ledger("Bob | 45.50 | Food | Carol, Bob, Alice\n")
    balances = compute_balances(expenses)
    assert balances[tab_settle.person_key("Alice")] == ("Alice", -1517)
    assert balances[tab_settle.person_key("Bob")] == ("Bob", 4550 - 1517)
    assert balances[tab_settle.person_key("Carol")] == ("Carol", -1516)
    assert sum(cents for _, cents in balances.values()) == 0


def test_payer_who_is_not_a_participant_is_still_credited():
    balances = compute_balances(parse_ledger("Dave | 20 | Pizza | Alice, Bob\n"))
    assert balances[tab_settle.person_key("Dave")] == ("Dave", 2000)
    assert balances[tab_settle.person_key("Alice")] == ("Alice", -1000)
    assert balances[tab_settle.person_key("Bob")] == ("Bob", -1000)


def test_single_item_paid_for_only_oneself_needs_no_transfers():
    expenses = parse_ledger("Alice | 7.25 | Coffee | Alice\n")
    assert settle(compute_balances(expenses)) == []


def test_settle_clears_every_balance_with_few_transfers():
    balances = {"a": ("A", -3916), "b": ("B", -567), "c": ("C", 3483), "d": ("D", 1000)}
    transfers = settle(balances)
    assert transfers == [("A", "C", 3483), ("A", "D", 433), ("B", "D", 567)]
    net = {"A": -3916, "B": -567, "C": 3483, "D": 1000}
    for debtor, creditor, cents in transfers:
        net[debtor] += cents
        net[creditor] -= cents
    assert all(value == 0 for value in net.values())


def test_sample_ledger_report_matches_hand_calculation(capsys):
    assert tab_settle.main([SAMPLE]) == 0
    out = capsys.readouterr().out
    assert "Alice" in out and "+34.83" in out
    assert "Bob" in out and "-5.67" in out
    assert "Carol" in out and "-39.16" in out
    assert "Dave" in out and "+10.00" in out
    assert "Carol -> Alice: 34.83" in out
    assert "Carol -> Dave: 4.33" in out
    assert "Bob -> Dave: 5.67" in out


def test_empty_ledger_reports_nothing_recorded():
    assert format_report(parse_ledger("# nothing yet\n")) == "No expenses recorded."


def test_malformed_line_error_names_the_line_and_value():
    with pytest.raises(LedgerError, match="line 2: invalid amount 'ten'"):
        parse_ledger("Alice | 10 | Lunch | Alice\nAlice | ten | Dinner | Alice\n")


def test_main_reports_missing_file(capsys):
    missing = os.path.join(ROOT, "examples", "no-such-ledger.txt")
    assert tab_settle.main([missing]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_byte_order_mark_does_not_create_a_phantom_person():
    expenses = parse_ledger(chr(0xFEFF) + "Alice | 10 | Lunch | Alice, Bob\n")
    assert expenses[0].payer == "Alice"
    assert len(compute_balances(expenses)) == 2


def test_decomposed_and_precomposed_accents_are_the_same_person():
    precomposed = "Jos" + chr(0xE9)  # the single character é
    decomposed = "Jose" + chr(0x301)  # plain e followed by a combining acute accent
    assert precomposed != decomposed
    expenses = parse_ledger(
        f"{precomposed} | 10 | a | {precomposed}, Bob\n"
        f"{decomposed} | 10 | b | {decomposed}, Bob\n"
    )
    balances = compute_balances(expenses)
    assert len(balances) == 2
    # Two expenses paid by José: +10.00 each, minus a 5.00 share each.
    assert balances[tab_settle.person_key(precomposed)] == (precomposed, 1000)
