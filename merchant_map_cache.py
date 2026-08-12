import json
from pathlib import Path

MANUAL_CACHE_SOURCE = "manual"


def build_merchant_cache_key(transaction):
    if transaction.get("counterparty_handle"):
        return transaction["counterparty_handle"].upper()
    if transaction.get("merchant_name"):
        return transaction["merchant_name"].upper()
    return transaction["narration_clean"].upper()


def load_merchant_map(merchant_map_file_path):
    merchant_map_path = Path(merchant_map_file_path)
    if not merchant_map_path.exists():
        return {}
    with merchant_map_path.open(encoding="utf-8") as merchant_map_handle:
        return json.load(merchant_map_handle)


def save_merchant_map(merchant_map, merchant_map_file_path):
    merchant_map_path = Path(merchant_map_file_path)
    merchant_map_path.parent.mkdir(parents=True, exist_ok=True)
    with merchant_map_path.open("w", encoding="utf-8") as merchant_map_handle:
        json.dump(merchant_map, merchant_map_handle, indent=2, sort_keys=True, ensure_ascii=False)


def look_up_merchant_category(merchant_map, merchant_cache_key):
    cache_entry = merchant_map.get(merchant_cache_key)
    if not cache_entry:
        return None
    return {
        "category": cache_entry["category"],
        "subcategory": cache_entry["subcategory"],
        "category_source": cache_entry["source"],
    }


def build_merchant_map_entry(classification, observed_date, source):
    return {
        "category": classification["category"],
        "subcategory": classification["subcategory"],
        "source": source,
        "confidence": classification.get("confidence", "low"),
        "reason": classification.get("reason", ""),
        "rejection_reason": classification.get("rejection_reason"),
        "first_seen": observed_date,
        "last_seen": observed_date,
        "hit_count": 0,
    }


def merge_classifications_into_merchant_map(merchant_map, classifications, observed_date, source="llm"):
    updated_merchant_map = dict(merchant_map)
    added_merchant_keys = []
    protected_merchant_keys = []

    for merchant_cache_key, classification in classifications.items():
        existing_entry = updated_merchant_map.get(merchant_cache_key)
        if existing_entry and existing_entry["source"] == MANUAL_CACHE_SOURCE:
            protected_merchant_keys.append(merchant_cache_key)
            continue

        new_entry = build_merchant_map_entry(classification, observed_date, source)
        if existing_entry:
            new_entry["first_seen"] = existing_entry["first_seen"]
            new_entry["hit_count"] = existing_entry["hit_count"]
        updated_merchant_map[merchant_cache_key] = new_entry
        added_merchant_keys.append(merchant_cache_key)

    return updated_merchant_map, added_merchant_keys, protected_merchant_keys


def record_merchant_map_hits(merchant_map, transactions, observed_date):
    updated_merchant_map = dict(merchant_map)

    for transaction in transactions:
        if transaction["is_duplicate"]:
            continue
        merchant_cache_key = build_merchant_cache_key(transaction)
        existing_entry = updated_merchant_map.get(merchant_cache_key)
        if not existing_entry:
            continue
        updated_entry = dict(existing_entry)
        updated_entry["hit_count"] = existing_entry["hit_count"] + 1
        updated_entry["last_seen"] = observed_date
        updated_merchant_map[merchant_cache_key] = updated_entry

    return updated_merchant_map