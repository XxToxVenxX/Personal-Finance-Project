import csv
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from transaction_pipeline import assign_transaction_identifiers

SAVINGS_TRANSACTION_HEADER = ["DATE", "MODE", "PARTICULARS", "DEPOSITS", "WITHDRAWALS", "BALANCE"]
OPENING_BALANCE_MARKER = "B/F"
SAVINGS_DATE_FORMAT = "%d-%m-%Y"
STATEMENT_PERIOD_PATTERN = re.compile(r"for the period\s*-\s*(.+)", re.IGNORECASE)
STATEMENT_PERIOD_DATE_FORMAT = "%B %d %Y"
MODE_PREFIX_TOKENS = {"MMT", "UPI", "NEFT", "IMPS", "BIL", "VIN", "CAM", "ACH", "INF", "ONL", "VPS", "IPS", "NFS"}
NUMERIC_REFERENCE_PATTERN = re.compile(r"^\d{7,}$")
ALPHANUMERIC_REFERENCE_PATTERN = re.compile(r"^\d{4,}[A-Z]{2,4}$|^[A-Z]{2,6}\d{6,}$")
BANK_BRANCH_CODE_PATTERN = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
CHARGE_FRAGMENT_PATTERN = re.compile(r"^CHGRS[\d.]+GSTRS[\d.]+$")
DATE_FRAGMENT_PATTERN = re.compile(r"^\d{2}-\d{2}-\d{2,4}$")
HYPHEN_MODE_PREFIX_PATTERN = re.compile(r"^(NEFT|IMPS|UPI|ACH|INF)-")
LONG_REFERENCE_SUBSTRING_PATTERN = re.compile(r"(?<![@.\w])(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*\d)[A-Z0-9]{20,}(?![@.\w])")
BANK_REFERENCE_SUBSTRING_PATTERN = re.compile(r"(?<![@.\w])[A-Z]{2,6}\d{8,}(?![@.\w])")
NARRATION_PREFIX_TO_PAYMENT_MODE = {
    "UPI": "UPI",
    "NEFT": "NEFT",
    "IMPS": "IMPS",
    "MMT": "IMPS",
    "CAM": "ATM",
    "ACH": "AUTO_DEBIT",
    "VIN": "POS",
    "VPS": "POS",
    "IPS": "POS",
    "NFS": "ATM",
    "ONL": "AUTO_DEBIT",
    "BIL": "AUTO_DEBIT",
}
SOURCE_MODE_TO_PAYMENT_MODE = {
    "CASH DEPOSIT": "ATM",
    "ATM": "ATM",
    "ATM/CASH WITHDRAWAL": "ATM",
    "DEBIT CARD": "POS",
    "POS": "POS",
    "CHEQUE": "CHEQUE",
    "CLEARING": "CHEQUE",
    "AUTO DEBIT": "AUTO_DEBIT",
    "ECS": "AUTO_DEBIT",
}
UPI_HANDLE_PATTERN = re.compile(r"^[A-Za-z0-9._-]{2,}@[A-Za-z]{2,}$")
NARRATION_MODE_PREFIXES = ["MMT/IMPS/", "MMT/", "UPI/", "NEFT-", "NEFT/", "IMPS-", "IMPS/", "BIL/", "VIN/", "ACH/", "TOP/"]
REFERENCE_NUMBER_PATTERN = re.compile(r"^\d{7,}$")
IFSC_CODE_PATTERN = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$", re.IGNORECASE)
DATE_FRAGMENT_PATTERN = re.compile(r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$")
BANK_CHARGE_PATTERN = re.compile(r"^chg\s*Rs[\d.]+\s*GST\s*Rs[\d.]+$", re.IGNORECASE)


def find_transaction_header_index(statement_rows):
    for row_index, row in enumerate(statement_rows):
        normalized_cells = [cell.strip().upper() for cell in row]
        if normalized_cells[: len(SAVINGS_TRANSACTION_HEADER)] == SAVINGS_TRANSACTION_HEADER:
            return row_index
    raise ValueError("Transaction header row not found in statement")


def read_savings_transaction_block(statement_file_path):
    statement_path = Path(statement_file_path)
    with statement_path.open(newline="", encoding="utf-8-sig") as statement_handle:
        statement_rows = list(csv.reader(statement_handle))

    header_index = find_transaction_header_index(statement_rows)
    header_cells = [cell.strip() for cell in statement_rows[header_index]]

    transaction_rows = []
    for row in statement_rows[header_index + 1 :]:
        if not any(cell.strip() for cell in row):
            break
        if len(row) != len(header_cells):
            raise ValueError(f"Unexpected column count in transaction block: {len(row)}")
        transaction_rows.append([cell.strip() for cell in row])

    transaction_block = pd.DataFrame(transaction_rows, columns=header_cells, dtype=str)
    transaction_block["STATEMENT_FILE"] = statement_path.name
    return transaction_block


def parse_statement_decimal(raw_value):
    stripped_value = raw_value.strip().replace(",", "")
    if not stripped_value:
        raise ValueError("Empty numeric field")
    try:
        return Decimal(stripped_value)
    except InvalidOperation:
        raise ValueError(f"Unparseable numeric field: {raw_value!r}")


def split_opening_balance_row(transaction_block):
    is_opening_balance_row = (
        transaction_block["PARTICULARS"].str.strip().str.upper() == OPENING_BALANCE_MARKER
    )
    opening_balance_rows = transaction_block[is_opening_balance_row]

    if len(opening_balance_rows) > 1:
        raise ValueError(f"Expected at most one {OPENING_BALANCE_MARKER} row, found {len(opening_balance_rows)}")

    if opening_balance_rows.empty:
        opening_balance = None
    else:
        opening_balance_row = opening_balance_rows.iloc[0]
        deposits_amount = parse_statement_decimal(opening_balance_row["DEPOSITS"])
        withdrawals_amount = parse_statement_decimal(opening_balance_row["WITHDRAWALS"])
        if deposits_amount != 0 or withdrawals_amount != 0:
            raise ValueError(f"{OPENING_BALANCE_MARKER} row carries a non-zero amount")
        opening_balance = parse_statement_decimal(opening_balance_row["BALANCE"])

    transaction_rows = transaction_block[~is_opening_balance_row].reset_index(drop=True)
    return opening_balance, transaction_rows


def parse_statement_date(raw_date):
    stripped_date = raw_date.strip()
    if not stripped_date:
        raise ValueError("Empty date field")
    try:
        return datetime.strptime(stripped_date, SAVINGS_DATE_FORMAT).date()
    except ValueError:
        raise ValueError(f"Date does not match {SAVINGS_DATE_FORMAT}: {raw_date!r}")


def resolve_amount_and_direction(raw_deposits, raw_withdrawals):
    deposits_amount = parse_statement_decimal(raw_deposits)
    withdrawals_amount = parse_statement_decimal(raw_withdrawals)

    if deposits_amount < 0 or withdrawals_amount < 0:
        raise ValueError(f"Negative amount in source: deposits={raw_deposits!r} withdrawals={raw_withdrawals!r}")

    if deposits_amount != 0 and withdrawals_amount != 0:
        raise ValueError(f"Both deposit and withdrawal populated: {raw_deposits!r} / {raw_withdrawals!r}")

    if deposits_amount == 0 and withdrawals_amount == 0:
        raise ValueError("Neither deposit nor withdrawal populated")

    if deposits_amount != 0:
        return deposits_amount, "credit"
    return withdrawals_amount, "debit"


def assemble_savings_transaction(raw_row):
    review_reasons = []

    try:
        transaction_date = parse_statement_date(raw_row["DATE"])
    except ValueError as error:
        transaction_date = None
        review_reasons.append(str(error))

    try:
        amount, direction = resolve_amount_and_direction(raw_row["DEPOSITS"], raw_row["WITHDRAWALS"])
    except ValueError as error:
        amount = None
        direction = None
        review_reasons.append(str(error))

    try:
        balance_after = parse_statement_decimal(raw_row["BALANCE"])
    except ValueError as error:
        balance_after = None
        review_reasons.append(str(error))

    narration_raw = raw_row["PARTICULARS"].strip()
    if not narration_raw:
        review_reasons.append("Empty narration")

    source_mode = raw_row["MODE"].strip()
    narration_clean = clean_narration(narration_raw)
    payment_mode = resolve_payment_mode(narration_raw, source_mode)
    counterparty_handle = extract_counterparty_handle(narration_raw)
    merchant_name = extract_merchant_name(narration_clean, payment_mode, counterparty_handle)

    return {
        "source_account": "icici_savings",
        "statement_file": raw_row["STATEMENT_FILE"],
        "transaction_date": transaction_date,
        "value_date": None,
        "narration_raw": narration_raw,
        "narration_clean": narration_clean,
        "merchant_name": merchant_name,
        "payment_mode": payment_mode,
        "counterparty_handle": counterparty_handle,
        "source_mode": source_mode,
        "amount": amount,
        "direction": direction,
        "currency": "INR",
        "balance_after": balance_after,
        "category": "Uncategorized",
        "subcategory": "Needs Review",
        "category_source": None,
        "is_transfer": False,
        "transfer_match_id": None,
        "is_duplicate": False,
        "needs_review": bool(review_reasons),
        "review_reason": "; ".join(review_reasons) if review_reasons else None,
    }


def is_discardable_narration_token(token):
    if "@" in token:
        return False
    return bool(
        REFERENCE_NUMBER_PATTERN.match(token)
        or IFSC_CODE_PATTERN.match(token)
        or DATE_FRAGMENT_PATTERN.match(token)
        or BANK_CHARGE_PATTERN.match(token)
    )


def clean_narration(narration_raw):
    remaining_narration = narration_raw.strip()
    for mode_prefix in NARRATION_MODE_PREFIXES:
        if remaining_narration.upper().startswith(mode_prefix.upper()):
            remaining_narration = remaining_narration[len(mode_prefix) :]
            break

    retained_tokens = []
    for token in remaining_narration.split("/"):
        collapsed_token = re.sub(r"\s+", " ", token).strip()
        if not collapsed_token:
            continue
        if is_discardable_narration_token(collapsed_token):
            continue
        retained_tokens.append(collapsed_token.upper())

    return "/".join(retained_tokens)


def is_noise_token(token):
    if not token:
        return True
    if token in MODE_PREFIX_TOKENS:
        return True
    if NUMERIC_REFERENCE_PATTERN.match(token):
        return True
    if ALPHANUMERIC_REFERENCE_PATTERN.match(token):
        return True
    if BANK_BRANCH_CODE_PATTERN.match(token):
        return True
    if CHARGE_FRAGMENT_PATTERN.match(token):
        return True
    if DATE_FRAGMENT_PATTERN.match(token):
        return True
    return False


def clean_narration(narration_raw):
    uppercased_narration = re.sub(r"\s+", " ", narration_raw.strip().upper())
    uppercased_narration = HYPHEN_MODE_PREFIX_PATTERN.sub("", uppercased_narration)
    uppercased_narration = LONG_REFERENCE_SUBSTRING_PATTERN.sub("", uppercased_narration)
    uppercased_narration = BANK_REFERENCE_SUBSTRING_PATTERN.sub("", uppercased_narration)
    candidate_tokens = re.split(r"[/\-]", uppercased_narration) if "/" not in uppercased_narration else uppercased_narration.split("/")
    meaningful_tokens = [token.strip(" -") for token in candidate_tokens if not is_noise_token(token.strip(" -"))]
    return "/".join(token for token in meaningful_tokens if token)


def resolve_payment_mode(narration_raw, source_mode):
    uppercased_narration = narration_raw.strip().upper()
    for token in re.split(r"[/\-]", uppercased_narration):
        if token in NARRATION_PREFIX_TO_PAYMENT_MODE:
            return NARRATION_PREFIX_TO_PAYMENT_MODE[token]
        if token:
            break
    return SOURCE_MODE_TO_PAYMENT_MODE.get(source_mode.strip().upper())


def extract_counterparty_handle(narration_raw):
    for token in re.split(r"[/\s]", narration_raw.strip()):
        if UPI_HANDLE_PATTERN.match(token):
            return token.upper()
    return None


def extract_handle_local_part(counterparty_handle):
    return counterparty_handle.split("@")[0].upper()


def extract_merchant_name(narration_clean, payment_mode, counterparty_handle):
    if counterparty_handle:
        return extract_handle_local_part(counterparty_handle)

    narration_tokens = [token for token in narration_clean.split("/") if token]
    if not narration_tokens:
        return None

    if payment_mode in {"NEFT", "POS", "CARD", "AUTO_DEBIT"}:
        return narration_tokens[0]

    if payment_mode == "IMPS":
        return narration_tokens[0] if len(narration_tokens) == 1 else None

    return None


def load_savings_statement(statement_file_path):
    transaction_block = read_savings_transaction_block(statement_file_path)
    opening_balance, transaction_rows = split_opening_balance_row(transaction_block)
    assembled_transactions = [assemble_savings_transaction(row) for _, row in transaction_rows.iterrows()]
    identified_transactions = assign_transaction_identifiers(assembled_transactions)
    return opening_balance, identified_transactions


def verify_balance_continuity(opening_balance, transactions):
    if opening_balance is None:
        raise ValueError("No opening balance available to verify against")

    discrepancies = []
    running_balance = opening_balance

    for position, transaction in enumerate(transactions):
        if transaction["amount"] is None or transaction["balance_after"] is None:
            discrepancies.append({
                "position": position,
                "transaction_id": transaction["transaction_id"],
                "expected_balance": None,
                "statement_balance": transaction["balance_after"],
                "reason": "Unparseable row breaks the balance walk",
            })
            break

        if transaction["direction"] == "credit":
            running_balance += transaction["amount"]
        else:
            running_balance -= transaction["amount"]

        if running_balance != transaction["balance_after"]:
            discrepancies.append({
                "position": position,
                "transaction_id": transaction["transaction_id"],
                "expected_balance": running_balance,
                "statement_balance": transaction["balance_after"],
                "reason": "Running balance does not match statement balance",
            })
            running_balance = transaction["balance_after"]

    return discrepancies


def parse_statement_period_date(raw_period_date):
    collapsed_date = re.sub(r"\s+", " ", raw_period_date.strip())
    try:
        return datetime.strptime(collapsed_date, STATEMENT_PERIOD_DATE_FORMAT).date()
    except ValueError:
        raise ValueError(f"Period date does not match {STATEMENT_PERIOD_DATE_FORMAT}: {raw_period_date!r}")


def read_savings_statement_period(statement_file_path):
    with Path(statement_file_path).open(newline="", encoding="utf-8-sig") as statement_handle:
        for row in csv.reader(statement_handle):
            for cell in row:
                match = STATEMENT_PERIOD_PATTERN.search(cell)
                if not match:
                    continue
                period_parts = match.group(1).split(" - ")
                if len(period_parts) != 2:
                    raise ValueError(f"Unrecognized statement period text: {cell!r}")
                return (
                    parse_statement_period_date(period_parts[0]),
                    parse_statement_period_date(period_parts[1]),
                )
    raise ValueError("Statement period not found in statement")