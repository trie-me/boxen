from dataclasses import dataclass

from boxen.shared.errors import require
from boxen.shared.values import markdown_value, quantity_milli, text_value


@dataclass
class InventoryItem:
    name: str
    quantity: str | None = None
    unit: str | None = None
    notes_markdown: str = ""

    def validate(self) -> None:
        self.name = text_value(self.name, 160, "Item name")
        quantity_milli(self.quantity)
        if self.unit is not None:
            self.unit = text_value(self.unit, 24, "Unit")
        markdown_value(self.notes_markdown, 16384)

    @staticmethod
    def merged_quantity(items: list[dict]) -> int | None:
        require(
            len({item["unit"] for item in items}) == 1,
            "item.merge_conflict",
            "These units differ. Specify the merged quantity and unit.",
        )
        if any(item["quantity_milli"] is None for item in items):
            return None
        value = sum(item["quantity_milli"] for item in items)
        require(value <= 999999999, "item.merge_conflict", "The merged quantity exceeds the supported limit.")
        return value
