from __future__ import annotations

from codeseam.analysis import FileWithoutFunctionUnits, FunctionInventory
from codeseam.platform import Json

FUNCTION_INVENTORY_SUMMARY_SCHEMA = "codeseam.analysis.inventory_summary.v1"


def function_inventory_records_payload(inventory: FunctionInventory) -> list[Json]:
    return [record.to_json_object() for record in inventory.records]


def function_inventory_summary_payload(inventory: FunctionInventory) -> Json:
    return {
        "schema_version": FUNCTION_INVENTORY_SUMMARY_SCHEMA,
        "function_count": inventory.function_count,
        "selected_file_count": inventory.selected_file_count,
        "files_without_function_units": [
            file_without_function_units_payload(item)
            for item in inventory.files_without_function_units
        ],
    }


def file_without_function_units_payload(item: FileWithoutFunctionUnits) -> Json:
    return {
        "file": item.file,
        "language": item.language,
        "caveats": list(item.caveats),
    }


__all__ = [
    "FUNCTION_INVENTORY_SUMMARY_SCHEMA",
    "file_without_function_units_payload",
    "function_inventory_records_payload",
    "function_inventory_summary_payload",
]
