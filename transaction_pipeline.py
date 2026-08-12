import hashlib
import re
from collections import defaultdict

TRANSACTION_IDENTIFIER_LENGTH = 16

def build_transaction_grouping_key(transaction):
    return (
        str(transaction["source_account"]),
        str(transaction["transaction_date"]),
        str(transaction["amount"]),
        str(transaction["direction"]),
        str(transaction["narration_clean"]),
    )

def build_transaction_identifier(transaction, sequence_number):
    grouping_key = build_transaction_grouping_key(transaction)
    identifier_input = "|".join(list(grouping_key) + [str(sequence_number)])
    return hashlib.sha256(identifier_input.encode("utf-8")).hexdigest()[:TRANSACTION_IDENTIFIER_LENGTH]

def assign_transaction_identifiers(assembled_transactions):
    sequence_counter = defaultdict(int)
    identified_transactions = []

    for transaction in assembled_transactions:
        grouping_key = build_transaction_grouping_key(transaction)
        sequence_number = sequence_counter[grouping_key]
        sequence_counter[grouping_key] += 1

        identified_transaction = dict(transaction)
        identified_transaction["transaction_id"] = build_transaction_identifier(transaction, sequence_number)
        identified_transactions.append(identified_transaction)

    return identified_transactions

def mark_duplicate_transactions(identified_transactions, previously_written_identifiers):
    seen_identifiers = set(previously_written_identifiers)
    marked_transactions = []

    for transaction in identified_transactions:
        marked_transaction = dict(transaction)
        transaction_identifier = transaction["transaction_id"]
        marked_transaction["is_duplicate"] = transaction_identifier in seen_identifiers
        seen_identifiers.add(transaction_identifier)
        marked_transactions.append(marked_transaction)

    return marked_transactions


SAVINGS_SOURCE_ACCOUNT = "icici_savings"
CARD_SOURCE_ACCOUNT_PREFIX = "icici_credit_card"
CARD_PAYMENT_LAST_FOUR_PATTERN = re.compile(r"BILLPAY-(\d{4})")
CARD_PAYMENT_NARRATION_MARKER = "PAYMENT RECEIVED"
MAXIMUM_TRANSFER_DATE_DIFFERENCE_DAYS = 3


def extract_card_payment_last_four(narration_clean):
    match = CARD_PAYMENT_LAST_FOUR_PATTERN.search(narration_clean)
    return match.group(1) if match else None


def build_transfer_match_identifier(bank_transaction, card_transaction):
    identifier_input = "|".join(sorted([bank_transaction["transaction_id"], card_transaction["transaction_id"]]))
    return hashlib.sha256(identifier_input.encode("utf-8")).hexdigest()[:TRANSACTION_IDENTIFIER_LENGTH]


def reconcile_card_payments(transactions):
    reconciled_transactions = [dict(transaction) for transaction in transactions]

    bank_payment_legs = [
        transaction
        for transaction in reconciled_transactions
        if transaction["source_account"] == SAVINGS_SOURCE_ACCOUNT
        and transaction["direction"] == "debit"
        and extract_card_payment_last_four(transaction["narration_clean"])
    ]
    card_payment_legs = [
        transaction
        for transaction in reconciled_transactions
        if transaction["source_account"].startswith(CARD_SOURCE_ACCOUNT_PREFIX)
        and transaction["direction"] == "credit"
        and CARD_PAYMENT_NARRATION_MARKER in transaction["narration_clean"]
    ]

    matched_card_identifiers = set()

    for bank_transaction in bank_payment_legs:
        bank_last_four = extract_card_payment_last_four(bank_transaction["narration_clean"])
        for card_transaction in card_payment_legs:
            if card_transaction["transaction_id"] in matched_card_identifiers:
                continue
            if card_transaction["source_card_last_four"] != bank_last_four:
                continue
            if card_transaction["amount"] != bank_transaction["amount"]:
                continue
            date_difference = abs((card_transaction["transaction_date"] - bank_transaction["transaction_date"]).days)
            if date_difference > MAXIMUM_TRANSFER_DATE_DIFFERENCE_DAYS:
                continue

            transfer_match_identifier = build_transfer_match_identifier(bank_transaction, card_transaction)
            for leg in (bank_transaction, card_transaction):
                leg["is_transfer"] = True
                leg["transfer_match_id"] = transfer_match_identifier
            matched_card_identifiers.add(card_transaction["transaction_id"])
            break

    unmatched_payment_legs = [
        transaction
        for transaction in bank_payment_legs + card_payment_legs
        if not transaction["is_transfer"]
    ]
    return reconciled_transactions, unmatched_payment_legs


def is_date_within_any_period(transaction_date, statement_periods):
    if transaction_date is None:
        return False
    return any(start <= transaction_date <= end for start, end in statement_periods)


def classify_unmatched_payment_legs(unmatched_payment_legs, statement_periods):
    anomalous_legs = []
    pending_legs = []

    for leg in unmatched_payment_legs:
        transaction_date = leg["transaction_date"]
        if transaction_date is None or is_date_within_any_period(transaction_date, statement_periods):
            anomalous_legs.append(leg)
        else:
            pending_legs.append(leg)

    return anomalous_legs, pending_legs