from run_pipeline import run_pipeline
from workbook_writer import (
    build_workbook_rows,
    summarize_workbook_rows,
    format_workbook_summary,
    append_transaction_rows,
)
from review_queue import append_review_queue_rows
from pipeline_config import WORKBOOK_PATH
from pipeline_logging import configure_pipeline_logging


def confirm(prompt_text):
    return input(f"{prompt_text} type yes to confirm: ").strip().lower() == "yes"


def run_monthly_update():
    logger = configure_pipeline_logging()
    pipeline_result = run_pipeline()
    if pipeline_result is None:
        return

    transaction_rows = build_workbook_rows(pipeline_result["transactions"])
    review_queue_rows = pipeline_result["review_queue_rows"]

    logger.info("")
    logger.info(f"workbook            : {WORKBOOK_PATH}")

    if not transaction_rows:
        logger.info("no new transactions to append")
    else:
        logger.info("")
        logger.info(format_workbook_summary(summarize_workbook_rows(transaction_rows)))
        logger.info("")
        if confirm("append these transactions?"):
            written_range = append_transaction_rows(WORKBOOK_PATH, transaction_rows)
            logger.info(f"transactions written to rows {written_range[0]}-{written_range[1]}")
        else:
            logger.info("transactions not written")
            return

    if not review_queue_rows:
        logger.info("no new review queue rows to append")
        return

    logger.info("")
    logger.info(f"review queue rows   : {len(review_queue_rows)}")
    for row in review_queue_rows[:5]:
        logger.info(f"   {row[0][:40]:<42} x{row[2]}")
    if len(review_queue_rows) > 5:
        logger.info(f"   ... and {len(review_queue_rows) - 5} more")
    logger.info("")
    if confirm("append these review queue rows?"):
        written_range = append_review_queue_rows(WORKBOOK_PATH, review_queue_rows)
        logger.info(f"review queue written to rows {written_range[0]}-{written_range[1]}")
    else:
        logger.info("review queue not written")


if __name__ == "__main__":
    run_monthly_update()