import re
from pathlib import Path

CATEGORY_HEADING_PATTERN = re.compile(r"^##\s+\d+\.\s+(.+?)\s*$")
TABLE_ROW_PATTERN = re.compile(r"^\|(.+?)\|")
UNCATEGORIZED_CATEGORY = "Uncategorized"
UNCATEGORIZED_SUBCATEGORY = "Needs Review"
MINIMUM_EXPECTED_CATEGORY_COUNT = 10


def load_category_taxonomy(categories_file_path):
    category_taxonomy = {}
    current_category = None

    for line in Path(categories_file_path).read_text(encoding="utf-8").splitlines():
        heading_match = CATEGORY_HEADING_PATTERN.match(line)
        if heading_match:
            current_category = heading_match.group(1)
            category_taxonomy[current_category] = []
            continue

        if current_category is None:
            continue

        row_match = TABLE_ROW_PATTERN.match(line.strip())
        if not row_match:
            continue

        first_cell = row_match.group(1).strip()
        if not first_cell or first_cell.lower() == "subcategory" or set(first_cell) <= set("- "):
            continue
        if first_cell not in category_taxonomy[current_category]:
            category_taxonomy[current_category].append(first_cell)

    if len(category_taxonomy) < MINIMUM_EXPECTED_CATEGORY_COUNT:
        raise ValueError(f"Parsed only {len(category_taxonomy)} categories from {categories_file_path}")

    return category_taxonomy


def is_valid_category_pair(category_taxonomy, category, subcategory):
    return subcategory in category_taxonomy.get(category, [])


def validate_classification(category_taxonomy, category, subcategory):
    if category and subcategory and is_valid_category_pair(category_taxonomy, category, subcategory):
        return category, subcategory, None
    rejection_reason = f"Classification outside taxonomy: {category!r} > {subcategory!r}"
    return UNCATEGORIZED_CATEGORY, UNCATEGORIZED_SUBCATEGORY, rejection_reason