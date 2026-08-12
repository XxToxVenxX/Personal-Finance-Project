import json
import re
import time
from pathlib import Path

from pipeline_logging import get_pipeline_logger

from category_taxonomy import validate_classification

BOUNDARY_RULES_HEADING = "## Boundary Rules"
ALLOWED_CONFIDENCE_VALUES = ["high", "medium", "low"]
JSON_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
MERCHANT_CONTEXT_SUFFIX_PATTERN = re.compile(r"\s*\[source:.*$")


def load_boundary_rules_text(categories_file_path):
    document_text = Path(categories_file_path).read_text(encoding="utf-8")
    if BOUNDARY_RULES_HEADING not in document_text:
        raise ValueError(f"{BOUNDARY_RULES_HEADING} section not found in {categories_file_path}")
    section_text = document_text.split(BOUNDARY_RULES_HEADING, 1)[1]
    return section_text.split("\n---", 1)[0].strip()


def format_taxonomy_for_prompt(category_taxonomy):
    formatted_lines = []
    for category, subcategories in category_taxonomy.items():
        for subcategory in subcategories:
            formatted_lines.append(f"{category} > {subcategory}")
    return "\n".join(formatted_lines)


def build_merchant_contexts(transactions, build_merchant_cache_key):
    merchant_contexts = {}
    for transaction in transactions:
        if transaction["is_duplicate"]:
            continue
        merchant_cache_key = build_merchant_cache_key(transaction)
        context = merchant_contexts.setdefault(
            merchant_cache_key,
            {"sources": set(), "payment_modes": set(), "directions": set(), "occurrences": 0, "amounts": []},
        )
        if transaction["source_account"]:
            context["sources"].add(
                "credit_card" if transaction["source_account"].startswith("icici_credit_card") else "bank_account"
            )
        if transaction["payment_mode"]:
            context["payment_modes"].add(transaction["payment_mode"])
        if transaction["direction"]:
            context["directions"].add(transaction["direction"])
        context["occurrences"] += 1
        if transaction["amount"] is not None:
            context["amounts"].append(transaction["amount"])
    return merchant_contexts


def format_merchant_context(merchant_cache_key, context):
    if not context:
        return merchant_cache_key
    sources = "/".join(sorted(context["sources"])) or "unknown"
    payment_modes = "/".join(sorted(context["payment_modes"])) or "unknown"
    directions = "/".join(sorted(context["directions"])) or "unknown"
    amounts = context["amounts"]
    amount_summary = f"{min(amounts)}-{max(amounts)}" if amounts else "unknown"
    return (
        f"{merchant_cache_key}  [source: {sources}; mode: {payment_modes}; "
        f"direction: {directions}; times: {context['occurrences']}; amount range: {amount_summary}]"
    )


def build_classification_prompt(merchant_keys, category_taxonomy, boundary_rules_text, merchant_contexts=None):
    merchant_contexts = merchant_contexts or {}
    merchant_lines = "\n".join(
        f"{position}. {format_merchant_context(key, merchant_contexts.get(key))}"
        for position, key in enumerate(merchant_keys, start=1)
    )
    return f"""You are categorizing bank and credit card transactions for a personal finance ledger in India.

Assign each merchant string to exactly one category and subcategory from this closed list. Do not invent any category or subcategory that is not listed here.

{format_taxonomy_for_prompt(category_taxonomy)}

Apply these boundary rules literally. They override your general judgement.

{boundary_rules_text}

Each merchant string below is followed by context in square brackets. Use it.

A "source: credit_card" entry is a purchase at a merchant. Indian shops are commonly registered under the owner's personal name, so a person-like name from a credit card is a small business, not a transfer to an individual. Categorize it by what that business most likely sells.

An entry with mode POS, CARD, or AUTO_DEBIT is a purchase at a merchant, whatever the name looks like. Indian shops are routinely registered under the owner's personal name, so a POS swipe at a person-like name is a small business. Categorize it by what that business most likely sells.

A "source: bank_account" entry with mode UPI or IMPS and a person-like name is a transfer to an individual. Assign Uncategorized > Needs Review for those, as the boundary rules require.

This applies to credits as well as debits. Money received from an individual is a personal transfer, not income. Only assign Income > Refunds when the counterparty is a recognizable business that you can name. A merchant string that is only a phone number, a bare UPI handle, or a person's name is never a refund, never salary, and never a reimbursement, regardless of direction. Assign Uncategorized > Needs Review instead.

If a merchant string is unreadable, or you cannot tell what a business sells, assign Uncategorized > Needs Review rather than guessing.

Merchant strings to categorize:

{merchant_lines}

Respond with a JSON array only. No preamble, no markdown fences, no explanation outside the JSON. Each element must have exactly these fields:
- "index": the integer at the start of the merchant line, copied exactly
- "category": one of the categories listed above
- "subcategory": a subcategory belonging to that category
- "confidence": one of "high", "medium", "low"
- "reason": one short sentence explaining the assignment, using no double quote characters"""


def strip_json_fences(response_text):
    return JSON_FENCE_PATTERN.sub("", response_text.strip()).strip()


def resolve_entry_merchant_key(entry, requested_merchant_keys):
    entry_index = entry.get("index")
    if isinstance(entry_index, str) and entry_index.strip().isdigit():
        entry_index = int(entry_index.strip())
    if isinstance(entry_index, int) and 1 <= entry_index <= len(requested_merchant_keys):
        return requested_merchant_keys[entry_index - 1]

    merchant_key = entry.get("merchant_key")
    if isinstance(merchant_key, str):
        merchant_key = MERCHANT_CONTEXT_SUFFIX_PATTERN.sub("", merchant_key).strip()
        if merchant_key in set(requested_merchant_keys):
            return merchant_key
    return None


def parse_classification_response(response_text, category_taxonomy, requested_merchant_keys):
    try:
        parsed_response = json.loads(strip_json_fences(response_text))
    except json.JSONDecodeError as error:
        raise ValueError(f"Classification response was not valid JSON: {error}")

    if not isinstance(parsed_response, list):
        raise ValueError("Classification response was not a JSON array")

    requested_keys = set(requested_merchant_keys)
    validated_classifications = {}

    for entry in parsed_response:
        if not isinstance(entry, dict):
            continue
        merchant_key = resolve_entry_merchant_key(entry, requested_merchant_keys)
        if merchant_key is None or merchant_key in validated_classifications:
            continue

        category, subcategory, rejection_reason = validate_classification(
            category_taxonomy, entry.get("category"), entry.get("subcategory")
        )
        confidence = entry.get("confidence")
        if confidence not in ALLOWED_CONFIDENCE_VALUES:
            confidence = "low"

        validated_classifications[merchant_key] = {
            "category": category,
            "subcategory": subcategory,
            "confidence": confidence,
            "reason": entry.get("reason") or "",
            "rejection_reason": rejection_reason,
        }

    missing_merchant_keys = [key for key in requested_merchant_keys if key not in validated_classifications]
    return validated_classifications, missing_merchant_keys


SUPPORTED_CLASSIFICATION_PROVIDERS = ["anthropic", "gemini"]
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAXIMUM_CLASSIFICATION_ATTEMPTS = 4
RETRY_BACKOFF_SECONDS = 5


def read_api_key_from_environment(environment_variable_names):
    import os

    for variable_name in environment_variable_names:
        api_key = os.environ.get(variable_name)
        if api_key:
            return api_key
    raise ValueError(f"None of these environment variables are set: {', '.join(environment_variable_names)}")


class AnthropicClassificationClient:
    def __init__(self, model, max_tokens, api_key=None):
        import anthropic

        self.model = model
        self.max_tokens = max_tokens
        self.client = anthropic.Anthropic(api_key=api_key or read_api_key_from_environment(["ANTHROPIC_API_KEY"]))

    def generate_text(self, prompt):
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in response.content if block.type == "text")


class GeminiClassificationClient:
    def __init__(self, model, max_tokens, api_key=None):
        from google import genai

        self.model = model
        self.max_tokens = max_tokens
        self.client = genai.Client(
            api_key=api_key or read_api_key_from_environment(["GEMINI_API_KEY", "GOOGLE_API_KEY"])
        )

    def generate_text(self, prompt):
        from google.genai import types

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=self.max_tokens,
                response_mime_type="application/json",
            ),
        )
        return response.text


def create_classification_client(provider, model, max_tokens, api_key=None):
    if provider == "anthropic":
        return AnthropicClassificationClient(model, max_tokens, api_key)
    if provider == "gemini":
        return GeminiClassificationClient(model, max_tokens, api_key)
    raise ValueError(f"Unsupported provider {provider!r}. Supported: {', '.join(SUPPORTED_CLASSIFICATION_PROVIDERS)}")


def extract_error_status_code(error):
    for attribute_name in ("code", "status_code"):
        status_code = getattr(error, attribute_name, None)
        if isinstance(status_code, int):
            return status_code
    return None


def generate_text_with_retry(classification_client, prompt):
    for attempt_number in range(1, MAXIMUM_CLASSIFICATION_ATTEMPTS + 1):
        try:
            return classification_client.generate_text(prompt)
        except Exception as error:
            status_code = extract_error_status_code(error)
            if status_code not in RETRYABLE_STATUS_CODES:
                raise
            if attempt_number == MAXIMUM_CLASSIFICATION_ATTEMPTS:
                raise
            time.sleep(RETRY_BACKOFF_SECONDS * (2 ** (attempt_number - 1)))


def split_into_batches(merchant_keys, batch_size):
    if not isinstance(batch_size, int) or batch_size < 1:
        raise ValueError(f"batch_size must be a positive integer, got {batch_size!r}")
    return [merchant_keys[index : index + batch_size] for index in range(0, len(merchant_keys), batch_size)]


def classify_merchant_keys(
    merchant_keys,
    category_taxonomy,
    boundary_rules_text,
    classification_client,
    batch_size,
    merchant_contexts=None,
    on_batch_classified=None,
):
    all_classifications = {}
    all_missing_merchant_keys = []

    def classify_single_batch(batch, batch_label):
        prompt = build_classification_prompt(batch, category_taxonomy, boundary_rules_text, merchant_contexts)
        response_text = generate_text_with_retry(classification_client, prompt)
        try:
            return parse_classification_response(response_text, category_taxonomy, batch)
        except ValueError as error:
            if len(batch) == 1:
                get_pipeline_logger().warning(
                    f"   {batch_label} unparseable for a single merchant, skipping: {batch[0][:60]}"
                )
                return {}, list(batch)
            midpoint = len(batch) // 2
            get_pipeline_logger().warning(
                f"   {batch_label} unparseable, splitting {len(batch)} merchants: {error}"
            )
            first_classifications, first_missing = classify_single_batch(batch[:midpoint], f"{batch_label}a")
            second_classifications, second_missing = classify_single_batch(batch[midpoint:], f"{batch_label}b")
            first_classifications.update(second_classifications)
            return first_classifications, first_missing + second_missing

    batches = split_into_batches(merchant_keys, batch_size)
    for batch_index, batch in enumerate(batches):
        batch_label = f"batch {batch_index + 1}/{len(batches)}"
        try:
            batch_classifications, batch_missing_keys = classify_single_batch(batch, batch_label)
        except Exception as error:
            if extract_error_status_code(error) not in RETRYABLE_STATUS_CODES:
                raise
            get_pipeline_logger().warning(f"   {batch_label} failed after retries, stopping: {error}")
            for remaining_batch in batches[batch_index:]:
                all_missing_merchant_keys.extend(remaining_batch)
            return all_classifications, all_missing_merchant_keys

        all_classifications.update(batch_classifications)
        all_missing_merchant_keys.extend(batch_missing_keys)

        if on_batch_classified and batch_classifications:
            on_batch_classified(batch_classifications, batch_index + 1, len(batches))

    return all_classifications, all_missing_merchant_keys