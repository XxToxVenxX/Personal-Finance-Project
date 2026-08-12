from pathlib import Path

from savings_statement_reader import (
    load_savings_statement,
    read_savings_statement_period,
    verify_balance_continuity,
)
from credit_card_statement_reader import load_card_statement


def find_statement_files(statement_directory, filename_pattern):
    directory_path = Path(statement_directory)
    if not directory_path.exists():
        raise ValueError(f"Statement directory does not exist: {statement_directory}")
    return sorted(path for path in directory_path.glob(filename_pattern) if path.is_file())


def load_savings_statements(statement_directory, filename_pattern):
    transactions = []
    statement_periods = []
    balance_discrepancies = []
    failed_files = []

    for statement_path in find_statement_files(statement_directory, filename_pattern):
        try:
            opening_balance, file_transactions = load_savings_statement(statement_path)
            statement_period = read_savings_statement_period(statement_path)
        except Exception as error:
            failed_files.append({"statement_file": statement_path.name, "error": str(error)})
            continue

        file_discrepancies = verify_balance_continuity(opening_balance, file_transactions)
        for discrepancy in file_discrepancies:
            discrepancy["statement_file"] = statement_path.name
        balance_discrepancies.extend(file_discrepancies)

        transactions.extend(file_transactions)
        statement_periods.append(statement_period)

    return transactions, statement_periods, balance_discrepancies, failed_files


def load_card_statements(statement_directory, filename_pattern, source_account):
    transactions = []
    failed_files = []

    for statement_path in find_statement_files(statement_directory, filename_pattern):
        try:
            transactions.extend(load_card_statement(statement_path, source_account))
        except Exception as error:
            failed_files.append({"statement_file": statement_path.name, "error": str(error)})

    return transactions, failed_files