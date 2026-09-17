import re

from category_taxonomy import load_category_taxonomy
from review_queue import (
    REVIEW_QUEUE_SHEET_NAME,
    RESOLVED_CATEGORY_COLUMN_INDEX,
    RESOLVED_SUBCATEGORY_COLUMN_INDEX,
)
from pipeline_config import CATEGORIES_PATH, WORKBOOK_PATH
from pipeline_logging import configure_pipeline_logging

TAXONOMY_SHEET_NAME = "Taxonomy_Lookup"
CATEGORY_LIST_RANGE_NAME = "TaxonomyCategories"
CATEGORY_KEY_COLUMN_INDEX = 1
CATEGORY_NAME_COLUMN_INDEX = 2
SUBCATEGORY_START_COLUMN_INDEX = 4
VALIDATION_LAST_ROW = 1048576


def column_index_to_letter(column_index):
    letters = ""
    while column_index > 0:
        column_index, remainder = divmod(column_index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def build_range_name(category_name):
    sanitized_name = re.sub(r"[^A-Za-z0-9]", "", category_name)
    return f"Sub{sanitized_name}"


def build_taxonomy_layout(category_taxonomy):
    layout_rows = []
    for row_offset, (category_name, subcategories) in enumerate(category_taxonomy.items()):
        layout_rows.append(
            {
                "row_number": row_offset + 2,
                "category_name": category_name,
                "range_name": build_range_name(category_name),
                "subcategories": subcategories,
            }
        )
    return layout_rows


def write_taxonomy_sheet(workbook, layout_rows):
    if TAXONOMY_SHEET_NAME in [sheet.name for sheet in workbook.sheets]:
        taxonomy_sheet = workbook.sheets[TAXONOMY_SHEET_NAME]
        taxonomy_sheet.clear()
    else:
        taxonomy_sheet = workbook.sheets.add(TAXONOMY_SHEET_NAME, after=workbook.sheets[-1])

    taxonomy_sheet.range((1, 1)).value = ["Range_Key", "Category", "", "Subcategories"]

    widest_subcategory_count = max(len(layout_row["subcategories"]) for layout_row in layout_rows)
    block = []
    for layout_row in layout_rows:
        padded_subcategories = list(layout_row["subcategories"]) + [None] * (
            widest_subcategory_count - len(layout_row["subcategories"])
        )
        block.append([layout_row["range_name"], layout_row["category_name"], None] + padded_subcategories)

    taxonomy_sheet.range((2, 1)).value = block
    return taxonomy_sheet


def delete_existing_name(workbook, range_name):
    for existing_name in list(workbook.names):
        if existing_name.name == range_name:
            existing_name.delete()


def define_taxonomy_names(workbook, taxonomy_sheet, layout_rows):
    category_reference = (
        f"={TAXONOMY_SHEET_NAME}!$B$2:$B${len(layout_rows) + 1}"
    )
    delete_existing_name(workbook, CATEGORY_LIST_RANGE_NAME)
    workbook.names.add(CATEGORY_LIST_RANGE_NAME, category_reference)

    for layout_row in layout_rows:
        last_column_letter = column_index_to_letter(
            SUBCATEGORY_START_COLUMN_INDEX + len(layout_row["subcategories"]) - 1
        )
        start_column_letter = column_index_to_letter(SUBCATEGORY_START_COLUMN_INDEX)
        subcategory_reference = (
            f"={TAXONOMY_SHEET_NAME}!${start_column_letter}${layout_row['row_number']}"
            f":${last_column_letter}${layout_row['row_number']}"
        )
        delete_existing_name(workbook, layout_row["range_name"])
        workbook.names.add(layout_row["range_name"], subcategory_reference)


def apply_review_queue_validation(workbook, layout_rows):
    review_sheet = workbook.sheets[REVIEW_QUEUE_SHEET_NAME]

    category_range = review_sheet.range(
        (2, RESOLVED_CATEGORY_COLUMN_INDEX), (VALIDATION_LAST_ROW, RESOLVED_CATEGORY_COLUMN_INDEX)
    )
    category_range.api.Validation.Delete()
    category_range.api.Validation.Add(3, 1, 1, f"={CATEGORY_LIST_RANGE_NAME}")
    category_range.api.Validation.IgnoreBlank = True
    category_range.api.Validation.InCellDropdown = True

    category_column_letter = chr(ord("A") + RESOLVED_CATEGORY_COLUMN_INDEX - 1)
    last_taxonomy_row = len(layout_rows) + 1
    lookup_formula = (
        f"=INDIRECT(IFERROR("
        f"INDEX({TAXONOMY_SHEET_NAME}!$A$2:$A${last_taxonomy_row},"
        f"MATCH({category_column_letter}2,{TAXONOMY_SHEET_NAME}!$B$2:$B${last_taxonomy_row},0)),"
        f'"{CATEGORY_LIST_RANGE_NAME}"))'
    )

    subcategory_range = review_sheet.range(
        (2, RESOLVED_SUBCATEGORY_COLUMN_INDEX), (VALIDATION_LAST_ROW, RESOLVED_SUBCATEGORY_COLUMN_INDEX)
    )
    subcategory_range.api.Validation.Delete()
    subcategory_range.api.Validation.Add(3, 1, 1, lookup_formula)
    subcategory_range.api.Validation.IgnoreBlank = True
    subcategory_range.api.Validation.InCellDropdown = True
    subcategory_range.api.Validation.ShowError = False


def add_review_queue_dropdowns():
    import xlwings

    logger = configure_pipeline_logging()

    category_taxonomy = load_category_taxonomy(CATEGORIES_PATH)
    layout_rows = build_taxonomy_layout(category_taxonomy)
    logger.info(f"taxonomy            : {len(layout_rows)} categories, "
                f"{sum(len(row['subcategories']) for row in layout_rows)} subcategories")

    workbook = xlwings.Book(WORKBOOK_PATH)
    excel_application = workbook.app
    excel_application.display_alerts = False
    excel_application.screen_updating = False
    try:
        if REVIEW_QUEUE_SHEET_NAME not in [sheet.name for sheet in workbook.sheets]:
            raise ValueError(f"Sheet {REVIEW_QUEUE_SHEET_NAME!r} not found in the workbook")

        taxonomy_sheet = write_taxonomy_sheet(workbook, layout_rows)
        logger.info("taxonomy sheet      : written")
        define_taxonomy_names(workbook, taxonomy_sheet, layout_rows)
        logger.info(f"named ranges        : {len(layout_rows) + 1} defined")
        apply_review_queue_validation(workbook, layout_rows)
        logger.info(f"dropdowns applied   : rows 2 to {VALIDATION_LAST_ROW}")
        taxonomy_sheet.visible = False
        workbook.save()
        logger.info("workbook saved")
    finally:
        excel_application.display_alerts = True
        excel_application.screen_updating = True


if __name__ == "__main__":
    add_review_queue_dropdowns()