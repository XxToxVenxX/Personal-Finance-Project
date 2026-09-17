from run_pipeline import run_pipeline
from workbook_writer import (
    read_existing_category_rows,
    build_category_update_block,
    apply_category_updates,
)
from pipeline_config import WORKBOOK_PATH
from pipeline_logging import configure_pipeline_logging


def refresh_workbook_categories():
    logger = configure_pipeline_logging()
    pipeline_result = run_pipeline(categorize_all=True)
    if pipeline_result is None:
        return

    existing_category_rows = read_existing_category_rows(WORKBOOK_PATH)
    logger.info(f"existing rows       : {len(existing_category_rows)}")
    if not existing_category_rows:
        logger.info("nothing to refresh")
        return

    updated_block, changed_row_summaries = build_category_update_block(
        existing_category_rows, pipeline_result["transactions"]
    )
    logger.info(f"rows changing       : {len(changed_row_summaries)}")

    if not changed_row_summaries:
        return

    for change in changed_row_summaries[:15]:
        logger.info(f"   row {change['row_number']}: {change['from_category']} -> {change['to_category']}")
    if len(changed_row_summaries) > 15:
        logger.info(f"   ... and {len(changed_row_summaries) - 15} more")

    if input("apply these category updates? type yes to confirm: ").strip().lower() != "yes":
        logger.info("categories not updated")
        return

    updated_row_count = apply_category_updates(WORKBOOK_PATH, updated_block)
    logger.info(f"categories refreshed: {updated_row_count} rows rewritten")


if __name__ == "__main__":
    refresh_workbook_categories()