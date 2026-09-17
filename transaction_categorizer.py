from categorization_rules import apply_categorization_rules
from merchant_map_cache import build_merchant_cache_key

UNCATEGORIZED_CATEGORY = "Uncategorized"
UNCATEGORIZED_SUBCATEGORY = "Needs Review"
UNRESOLVED_REVIEW_REASON = "No rule or cache entry for merchant"
UNCATEGORIZED_CACHE_REVIEW_REASON = "Merchant classified as uncategorized"
RULE_CLASSIFICATION_CONFIDENCE = "high"
RULE_CLASSIFICATION_REASON = "Matched a structural categorization rule"
UNRESOLVED_CLASSIFICATION_CONFIDENCE = "low"


def append_review_reason(existing_review_reason, additional_review_reason):
    if not existing_review_reason:
        return additional_review_reason
    return f"{existing_review_reason}; {additional_review_reason}"


def categorize_transaction(transaction, merchant_map):
    categorized_transaction = dict(transaction)

    rule_result = apply_categorization_rules(transaction)
    if rule_result:
        categorized_transaction.update(rule_result)
        categorized_transaction["classification_confidence"] = RULE_CLASSIFICATION_CONFIDENCE
        categorized_transaction["classification_reason"] = RULE_CLASSIFICATION_REASON
        return categorized_transaction, None

    merchant_cache_key = build_merchant_cache_key(transaction)
    cache_entry = merchant_map.get(merchant_cache_key)
    if cache_entry:
        categorized_transaction["category"] = cache_entry["category"]
        categorized_transaction["subcategory"] = cache_entry["subcategory"]
        categorized_transaction["category_source"] = cache_entry["source"]
        categorized_transaction["classification_confidence"] = cache_entry.get("confidence", "low")
        categorized_transaction["classification_reason"] = cache_entry.get("reason", "")
        if cache_entry["category"] == UNCATEGORIZED_CATEGORY:
            categorized_transaction["needs_review"] = True
            categorized_transaction["review_reason"] = append_review_reason(
                transaction["review_reason"], UNCATEGORIZED_CACHE_REVIEW_REASON
            )
        return categorized_transaction, None

    categorized_transaction["category"] = UNCATEGORIZED_CATEGORY
    categorized_transaction["subcategory"] = UNCATEGORIZED_SUBCATEGORY
    categorized_transaction["classification_confidence"] = UNRESOLVED_CLASSIFICATION_CONFIDENCE
    categorized_transaction["classification_reason"] = UNRESOLVED_REVIEW_REASON
    categorized_transaction["needs_review"] = True
    categorized_transaction["review_reason"] = append_review_reason(
        transaction["review_reason"], UNRESOLVED_REVIEW_REASON
    )
    return categorized_transaction, merchant_cache_key


def categorize_transactions(transactions, merchant_map, skip_duplicates=True):
    categorized_transactions = []
    unresolved_merchant_keys = []

    for transaction in transactions:
        if skip_duplicates and transaction["is_duplicate"]:
            duplicate_transaction = dict(transaction)
            duplicate_transaction["classification_confidence"] = None
            duplicate_transaction["classification_reason"] = None
            categorized_transactions.append(duplicate_transaction)
            continue

        categorized_transaction, unresolved_merchant_key = categorize_transaction(transaction, merchant_map)
        categorized_transactions.append(categorized_transaction)
        if unresolved_merchant_key and unresolved_merchant_key not in unresolved_merchant_keys:
            unresolved_merchant_keys.append(unresolved_merchant_key)

    return categorized_transactions, unresolved_merchant_keys