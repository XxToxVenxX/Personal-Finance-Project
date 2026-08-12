from run_pipeline import run_pipeline
from review_queue import append_review_queue_rows
from pipeline_config import WORKBOOK_PATH
from pipeline_logging import configure_pipeline_logging


def write_review_queue():
    logger = configure_pipeline_logging()
    pipeline_result = run_pipeline()
    if pipeline_result is None:
        return

    review_queue_rows = pipeline_result["review_queue_rows"]
    if not review_queue_rows:
        logger.info("no new review queue rows to append")
        return

    logger.info("")
    logger.info(f"workbook            : {WORKBOOK_PATH}")
    logger.info(f"review queue rows   : {len(review_queue_rows)}")
    logger.info("")
    logger.info("top rows by value:")
    for row in review_queue_rows[:10]:
        total_debit = row[3] or 0
        total_credit = row[4] or 0
        logger.info(f"   dr {total_debit:>12,.2f}  cr {total_credit:>11,.2f}  x{row[2]:<4} {row[0][:44]}")
    logger.info("")

    if input("append these review queue rows? type yes to confirm: ").strip().lower() != "yes":
        logger.info("review queue not written")
        return

    written_range = append_review_queue_rows(WORKBOOK_PATH, review_queue_rows)
    logger.info(f"review queue written to rows {written_range[0]}-{written_range[1]}")


if __name__ == "__main__":
    write_review_queue()