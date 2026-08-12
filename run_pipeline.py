from datetime import date

from statement_loader import load_savings_statements, load_card_statements
from pipeline_logging import configure_pipeline_logging
from transaction_pipeline import (
    mark_duplicate_transactions,
    reconcile_card_payments,
    classify_unmatched_payment_legs,
)
from transaction_categorizer import categorize_transactions
from category_taxonomy import load_category_taxonomy
from merchant_classifier import (
    create_classification_client,
    classify_merchant_keys,
    load_boundary_rules_text,
    build_merchant_contexts,
)
from merchant_map_cache import (
    load_merchant_map,
    save_merchant_map,
    merge_classifications_into_merchant_map,
    record_merchant_map_hits,
    build_merchant_cache_key,
)
from workbook_writer import read_written_transaction_identifiers
from review_queue import (
    build_review_queue_rows,
    read_queued_merchant_keys,
    read_resolved_review_entries,
)
from pipeline_config import (
    SAVINGS_DIRECTORY,
    AMAZON_CARD_DIRECTORY,
    STANDARD_CARD_DIRECTORY,
    STATEMENT_FILE_PATTERN,
    CATEGORIES_PATH,
    MERCHANT_MAP_PATH,
    WORKBOOK_PATH,
    AMAZON_CARD_SOURCE_ACCOUNT,
    STANDARD_CARD_SOURCE_ACCOUNT,
    CLASSIFICATION_PROVIDER,
    CLASSIFICATION_MODEL,
    CLASSIFICATION_LIMIT,
    CLASSIFICATION_BATCH_SIZE,
    CLASSIFICATION_MAX_TOKENS,
    ABORT_ON_BALANCE_DISCREPANCY,
)


def run_pipeline():
    logger = configure_pipeline_logging()
    run_date = str(date.today())
    logger.info("=" * 62)
    logger.info(f"pipeline run start  : {run_date}")
    category_taxonomy = load_category_taxonomy(CATEGORIES_PATH)

    savings_transactions, statement_periods, balance_discrepancies, savings_failures = load_savings_statements(
        SAVINGS_DIRECTORY, STATEMENT_FILE_PATTERN
    )
    amazon_transactions, amazon_failures = load_card_statements(
        AMAZON_CARD_DIRECTORY, STATEMENT_FILE_PATTERN, AMAZON_CARD_SOURCE_ACCOUNT
    )
    standard_transactions, standard_failures = load_card_statements(
        STANDARD_CARD_DIRECTORY, STATEMENT_FILE_PATTERN, STANDARD_CARD_SOURCE_ACCOUNT
    )
    failed_files = savings_failures + amazon_failures + standard_failures

    logger.info(f"statement periods   : {len(statement_periods)} savings files")
    logger.info(f"rows loaded         : savings {len(savings_transactions)}, "
          f"amazon {len(amazon_transactions)}, standard {len(standard_transactions)}")
    if failed_files:
        logger.info(f"files that failed   : {len(failed_files)}")
        for failure in failed_files:
            logger.info(f"   {failure['statement_file'][:44]} - {failure['error'][:52]}")
    logger.info(f"balance discrepancies: {len(balance_discrepancies)}")
    if balance_discrepancies:
        for discrepancy in balance_discrepancies[:5]:
            logger.info(f"   {discrepancy['statement_file'][:40]} row {discrepancy['position']}")
    if balance_discrepancies and ABORT_ON_BALANCE_DISCREPANCY:
        logger.info("aborting - balance continuity failed")
        return None

    written_transaction_identifiers = read_written_transaction_identifiers(WORKBOOK_PATH)
    all_transactions = savings_transactions + amazon_transactions + standard_transactions
    marked_transactions = mark_duplicate_transactions(all_transactions, written_transaction_identifiers)
    logger.info(f"already in workbook : {len(written_transaction_identifiers)} rows")
    logger.info(f"duplicates skipped  : {sum(t['is_duplicate'] for t in marked_transactions)}")

    reconciled_transactions, unmatched_payment_legs = reconcile_card_payments(marked_transactions)
    anomalous_legs, pending_legs = classify_unmatched_payment_legs(
        unmatched_payment_legs, statement_periods
    )
    logger.info(f"transfers reconciled: {sum(t['is_transfer'] for t in reconciled_transactions)} legs")
    logger.info(f"unmatched legs      : {len(anomalous_legs)} anomalous, {len(pending_legs)} pending")

    merchant_map = load_merchant_map(MERCHANT_MAP_PATH)
    resolved_classifications, rejected_resolutions = read_resolved_review_entries(
        WORKBOOK_PATH, category_taxonomy
    )
    if resolved_classifications:
        merchant_map, resolved_keys, _ = merge_classifications_into_merchant_map(
            merchant_map, resolved_classifications, run_date, source="manual"
        )
        logger.info(f"review resolutions  : {len(resolved_keys)} applied as manual entries")
    if rejected_resolutions:
        logger.info(f"review rejections   : {len(rejected_resolutions)} invalid category pairs")
        for rejection in rejected_resolutions:
            logger.info(f"   {rejection['merchant_cache_key'][:38]} -> "
                  f"{rejection['category']} > {rejection['subcategory']}")

    categorized_transactions, unresolved_merchant_keys = categorize_transactions(
        reconciled_transactions, merchant_map
    )
    logger.info(f"cache entries       : {len(merchant_map)}")
    logger.info(f"unresolved merchants: {len(unresolved_merchant_keys)}")

    if unresolved_merchant_keys and CLASSIFICATION_LIMIT != 0:
        keys_to_classify = (
            unresolved_merchant_keys
            if CLASSIFICATION_LIMIT is None
            else unresolved_merchant_keys[:CLASSIFICATION_LIMIT]
        )
        logger.info(f"classifying         : {len(keys_to_classify)} merchants")

        boundary_rules_text = load_boundary_rules_text(CATEGORIES_PATH)
        classification_client = create_classification_client(
            CLASSIFICATION_PROVIDER,
            model=CLASSIFICATION_MODEL,
            max_tokens=CLASSIFICATION_MAX_TOKENS,
        )
        merchant_contexts = build_merchant_contexts(reconciled_transactions, build_merchant_cache_key)

        cache_state = {"merchant_map": merchant_map, "added": 0, "protected": 0, "batches_saved": 0}

        def save_batch_to_merchant_map(batch_classifications, batch_number, batch_count):
            updated_map, added_keys, protected_keys = merge_classifications_into_merchant_map(
                cache_state["merchant_map"], batch_classifications, run_date
            )
            cache_state["merchant_map"] = updated_map
            cache_state["added"] += len(added_keys)
            cache_state["protected"] += len(protected_keys)
            cache_state["batches_saved"] += 1
            save_merchant_map(updated_map, MERCHANT_MAP_PATH)
            logger.info(f"   batch {batch_number}/{batch_count} saved, "
                        f"{len(updated_map)} cache entries total")

        classifications, missing_merchant_keys = classify_merchant_keys(
            keys_to_classify,
            category_taxonomy,
            boundary_rules_text,
            classification_client,
            merchant_contexts=merchant_contexts,
            batch_size=CLASSIFICATION_BATCH_SIZE,
            on_batch_classified=save_batch_to_merchant_map,
        )
        merchant_map = cache_state["merchant_map"]
        logger.info(f"classified          : {len(classifications)} ok, {len(missing_merchant_keys)} no answer")
        logger.info(f"cache updated       : {cache_state['added']} added, "
              f"{cache_state['protected']} manual entries protected")

        rejected = [key for key, result in classifications.items() if result["rejection_reason"]]
        if rejected:
            logger.warning(f"rejected by taxonomy: {len(rejected)}")
            for key in rejected:
                logger.warning(f"   {key[:44]} - {classifications[key]['rejection_reason']}")

        categorized_transactions, unresolved_merchant_keys = categorize_transactions(
            reconciled_transactions, merchant_map
        )

    merchant_map = record_merchant_map_hits(merchant_map, categorized_transactions, run_date)
    save_merchant_map(merchant_map, MERCHANT_MAP_PATH)

    already_queued_merchant_keys = read_queued_merchant_keys(WORKBOOK_PATH)
    review_queue_rows = build_review_queue_rows(categorized_transactions, already_queued_merchant_keys)

    logger.info(f"still unresolved    : {len(unresolved_merchant_keys)}")
    logger.info(f"rows needing review : {sum(t['needs_review'] for t in categorized_transactions)} "
          f"of {len(categorized_transactions)}")
    logger.info(f"new review queue    : {len(review_queue_rows)} merchants "
          f"({len(already_queued_merchant_keys)} already queued)")

    logger.info("pipeline run end")

    return {
        "transactions": categorized_transactions,
        "review_queue_rows": review_queue_rows,
        "rejected_resolutions": rejected_resolutions,
        "anomalous_legs": anomalous_legs,
        "pending_legs": pending_legs,
        "failed_files": failed_files,
    }


if __name__ == "__main__":
    pipeline_result = run_pipeline()