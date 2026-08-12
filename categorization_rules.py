CARD_SOURCE_ACCOUNT_PREFIX = "icici_credit_card"
SAVINGS_SOURCE_ACCOUNT = "icici_savings"


def match_reconciled_transfer(transaction):
    if transaction["is_transfer"]:
        return ("Transfers", "Credit Card Payment")
    return None


def match_bank_card_bill_payment(transaction):
    if transaction["source_account"] != SAVINGS_SOURCE_ACCOUNT:
        return None
    if "BILLPAY" in transaction["narration_clean"]:
        return ("Transfers", "Credit Card Payment")
    return None


def match_card_payment_received(transaction):
    if not transaction["source_account"].startswith(CARD_SOURCE_ACCOUNT_PREFIX):
        return None
    if "PAYMENT RECEIVED" in transaction["narration_clean"]:
        return ("Transfers", "Credit Card Payment")
    return None


def match_wallet_load(transaction):
    if "WALLET LOAD" in transaction["narration_clean"]:
        return ("Transfers", "Wallet Load")
    return None


def match_cash_withdrawal(transaction):
    if transaction["payment_mode"] == "ATM" and transaction["direction"] == "debit":
        return ("Transfers", "ATM Withdrawal")
    return None


def match_cash_deposit(transaction):
    if transaction["payment_mode"] == "ATM" and transaction["direction"] == "credit":
        return ("Transfers", "Self Transfer")
    return None


def match_mutual_fund_investment(transaction):
    if "WMS/MF" in transaction["narration_clean"]:
        return ("Financial", "Investments")
    return None


def match_emi_interest_component(transaction):
    if "INTEREST AMOUNT AMORTIZATION" in transaction["narration_clean"]:
        return ("Financial", "Interest Paid")
    return None


def match_emi_principal_component(transaction):
    if "PRINCIPAL AMOUNT AMORTIZATION" in transaction["narration_clean"]:
        return ("Financial", "Loan Repayment")
    return None


def match_card_tax_charge(transaction):
    narration_clean = transaction["narration_clean"]
    if narration_clean.startswith(("SGST-", "CGST-", "IGST-")):
        return ("Financial", "Bank Charges & Fees")
    return None


CATEGORIZATION_RULES = [
    match_reconciled_transfer,
    match_bank_card_bill_payment,
    match_card_payment_received,
    match_wallet_load,
    match_cash_withdrawal,
    match_cash_deposit,
    match_mutual_fund_investment,
    match_emi_interest_component,
    match_emi_principal_component,
    match_card_tax_charge,
]


def apply_categorization_rules(transaction):
    for rule in CATEGORIZATION_RULES:
        rule_result = rule(transaction)
        if rule_result:
            category, subcategory = rule_result
            return {"category": category, "subcategory": subcategory, "category_source": "rule"}
    return None