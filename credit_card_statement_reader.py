import csv
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from transaction_pipeline import assign_transaction_identifiers

CARD_TRANSACTION_HEADER = [
    "Date",
    "Sr.No.",
    "Transaction Details",
    "Reward Point Header",
    "Intl.Amount",
    "Amount(in Rs)",
    "BillingAmountSign",
]
MASKED_CARD_NUMBER_PATTERN = re.compile(r"^\d{4}X{4,}\d{4}$")
CARD_DATE_FORMAT = "%d/%m/%Y"
CREDIT_BILLING_SIGN = "CR"
DEBIT_BILLING_SIGNS = {"", "DR"}
UPI_REFERENCE_PREFIX_PATTERN = re.compile(r"^UPI-\d{6,}-")
EMI_INSTALLMENT_COUNTER_PATTERN = re.compile(r"<\d+/\d+>")
TRAILING_COUNTRY_MARKER_PATTERN = re.compile(r"\s+(?:[A-Z]{2}\*|IN)$")


def find_card_transaction_header_index(statement_rows):
    normalized_header = [cell.strip().upper() for cell in CARD_TRANSACTION_HEADER]
    for row_index, row in enumerate(statement_rows):
        normalized_cells = [cell.strip().upper() for cell in row]
        if normalized_cells[: len(normalized_header)] == normalized_header:
            return row_index
    raise ValueError("Card transaction header row not found in statement")


def is_masked_card_number_row(row):
    populated_cells = [cell.strip() for cell in row if cell.strip()]
    if len(populated_cells) != 1:
        return False
    return bool(MASKED_CARD_NUMBER_PATTERN.match(populated_cells[0]))


def read_card_transaction_block(statement_file_path):
    statement_path = Path(statement_file_path)
    with statement_path.open(newline="", encoding="utf-8-sig") as statement_handle:
        statement_rows = list(csv.reader(statement_handle))

    header_index = find_card_transaction_header_index(statement_rows)
    header_cells = [cell.strip() for cell in statement_rows[header_index]]

    transaction_rows = []
    masked_card_numbers = []
    current_masked_card_number = None

    for row in statement_rows[header_index + 1 :]:
        if not any(cell.strip() for cell in row):
            break
        if is_masked_card_number_row(row):
            current_masked_card_number = [cell.strip() for cell in row if cell.strip()][0]
            continue
        if len(row) != len(header_cells):
            raise ValueError(f"Unexpected column count in card transaction block: {len(row)}")
        transaction_rows.append([cell.strip() for cell in row])
        masked_card_numbers.append(current_masked_card_number)

    transaction_block = pd.DataFrame(transaction_rows, columns=header_cells, dtype=str)
    transaction_block["STATEMENT_FILE"] = statement_path.name
    transaction_block["MASKED_CARD_NUMBER"] = masked_card_numbers
    return transaction_block


def parse_card_statement_decimal(raw_value):
    stripped_value = raw_value.strip().replace(",", "")
    if not stripped_value:
        raise ValueError("Empty numeric field")
    try:
        return Decimal(stripped_value)
    except InvalidOperation:
        raise ValueError(f"Unparseable numeric field: {raw_value!r}")


def parse_card_statement_date(raw_date):
    stripped_date = raw_date.strip()
    if not stripped_date:
        raise ValueError("Empty date field")
    try:
        return datetime.strptime(stripped_date, CARD_DATE_FORMAT).date()
    except ValueError:
        raise ValueError(f"Date does not match {CARD_DATE_FORMAT}: {raw_date!r}")


def resolve_card_amount_and_direction(raw_amount, raw_billing_amount_sign):
    billing_amount_sign = raw_billing_amount_sign.strip().upper()
    if billing_amount_sign != CREDIT_BILLING_SIGN and billing_amount_sign not in DEBIT_BILLING_SIGNS:
        raise ValueError(f"Unrecognized billing amount sign: {raw_billing_amount_sign!r}")

    amount = parse_card_statement_decimal(raw_amount)
    if amount < 0:
        raise ValueError(f"Negative amount in source: {raw_amount!r}")
    if amount == 0:
        raise ValueError("Zero amount on a card transaction row")

    direction = "credit" if billing_amount_sign == CREDIT_BILLING_SIGN else "debit"
    return amount, direction


def clean_card_narration(narration_raw):
    uppercased_narration = re.sub(r"\s+", " ", narration_raw.strip().upper())
    uppercased_narration = UPI_REFERENCE_PREFIX_PATTERN.sub("", uppercased_narration)
    uppercased_narration = EMI_INSTALLMENT_COUNTER_PATTERN.sub("", uppercased_narration)
    uppercased_narration = TRAILING_COUNTRY_MARKER_PATTERN.sub("", uppercased_narration)
    return re.sub(r"\s+", " ", uppercased_narration).strip()


def resolve_card_payment_mode(narration_raw):
    if UPI_REFERENCE_PREFIX_PATTERN.match(narration_raw.strip().upper()):
        return "UPI"
    return "CARD"


def assemble_card_transaction(raw_row, source_account):
    review_reasons = []

    try:
        transaction_date = parse_card_statement_date(raw_row["Date"])
    except ValueError as error:
        transaction_date = None
        review_reasons.append(str(error))

    try:
        amount, direction = resolve_card_amount_and_direction(
            raw_row["Amount(in Rs)"], raw_row["BillingAmountSign"]
        )
    except ValueError as error:
        amount = None
        direction = None
        review_reasons.append(str(error))

    narration_raw = raw_row["Transaction Details"].strip()
    if not narration_raw:
        review_reasons.append("Empty narration")

    narration_clean = clean_card_narration(narration_raw)
    payment_mode = resolve_card_payment_mode(narration_raw)
    merchant_name = narration_clean if narration_clean else None

    masked_card_number = raw_row.get("MASKED_CARD_NUMBER")
    source_card_last_four = masked_card_number[-4:] if masked_card_number else None

    return {
        "source_account": source_account,
        "statement_file": raw_row["STATEMENT_FILE"],
        "source_card_last_four": source_card_last_four,
        "transaction_date": transaction_date,
        "value_date": None,
        "narration_raw": narration_raw,
        "narration_clean": narration_clean,
        "merchant_name": merchant_name,
        "payment_mode": payment_mode,
        "counterparty_handle": None,
        "amount": amount,
        "direction": direction,
        "currency": "INR",
        "balance_after": None,
        "category": "Uncategorized",
        "subcategory": "Needs Review",
        "category_source": None,
        "is_transfer": False,
        "transfer_match_id": None,
        "is_duplicate": False,
        "needs_review": bool(review_reasons),
        "review_reason": "; ".join(review_reasons) if review_reasons else None,
    }


def load_card_statement(statement_file_path, source_account):
    transaction_block = read_card_transaction_block(statement_file_path)
    assembled_transactions = [
        assemble_card_transaction(row, source_account) for _, row in transaction_block.iterrows()
    ]
    return assign_transaction_identifiers(assembled_transactions)