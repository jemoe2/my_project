"""TOML configuration file fixer and formatter."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from tomlkit import TOMLDocument, array, dumps, parse, table
from tomlkit.items import Array, Item, Table


class TomlFixer:
    """Main class for fixing and formatting TOML files."""

    def __init__(self, file_path: str | Path) -> None:
        """Initialize with file path."""
        self.file_path = Path(file_path)
        self.original_content = ""
        self.doc: TOMLDocument | None = None

    def create_backup(self) -> Path:
        """Create a timestamped backup of the file."""
        timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
        backup_path = self.file_path.with_name(
            f"{self.file_path.stem}_{timestamp}{self.file_path.suffix}",
        )
        shutil.copy(self.file_path, backup_path)
        return backup_path

    def read_content(self) -> None:
        """Read file content into memory."""
        try:
            self.original_content = self.file_path.read_text(encoding="utf-8")
        except OSError as e:
            msg = f"File read error: {e}"
            raise RuntimeError(msg) from e

    def load_file(self) -> None:
        """Parse TOML content into document structure."""
        if not self.original_content:
            raise RuntimeError("No content to parse")

        try:
            self.doc = parse(self.original_content)
        except Exception as e:
            msg = f"TOML parsing failed: {e}"
            raise RuntimeError(msg) from e

    def validate_toml(self) -> bool:
        """Validate TOML syntax."""
        try:
            parsed = parse(self.original_content)
            return bool(parsed)
        except Exception as e:
            error_msg = f"Invalid TOML syntax: {e}"
            print(error_msg)  # noqa: T201
            return False

    def apply_fixes(self) -> None:
        """Apply all fixes to the TOML document."""
        if self.doc is None:
            raise RuntimeError("Document not loaded")

        self._ensure_section(
            ["tool", "ruff"],
            {
                "line-length": 88,
                "target-version": "py312",
                "select": ["ALL"],
                "ignore": ["D203", "D212", "PLR0913"],
            },
        )

        self._ensure_section(
            ["tool", "black"],
            {
                "line-length": 88,
                "preview": True,
                "target-version": ["py312"],
            },
        )

        self._manage_per_file_ignores()
        self._normalize_lists()
        self._sort_keys_recursive(cast(Item, self.doc))

    def _ensure_section(self, path: list[str], defaults: dict[str, Any]) -> None:
        """Ensure configuration section exists with defaults."""
        current = cast(Table, self.doc)
        for key in path:
            if key not in current or not isinstance(current[key], Table):
                current[key] = table()  # type: ignore[assignment]
            current = cast(Table, current[key])

        for k, v in defaults.items():
            if k not in current:
                current[k] = v  # type: ignore[index]

    def _manage_per_file_ignores(self) -> None:
        """Manage per-file ignore rules."""
        if self.doc is None:
            return

        tool_table = cast(Table, self.doc.get("tool", table()))
        ruff_table = cast(Table, tool_table.get("ruff", table()))
        per_file: Array = cast(Array, ruff_table.get("per-file-ignores", array()))

        required = {"tests/*": ["S101", "D"], "migrations/*": ["F401"]}

        for pattern, rules in required.items():
            existing = next(
                (entry for entry in per_file if pattern in entry),  # type: ignore[misc]
                None,
            )

            if existing:
                existing_rules: list[str] = existing[pattern]  # type: ignore[index]
                combined = sorted(set(existing_rules + rules))
                if combined != existing_rules:
                    existing[pattern] = combined  # type: ignore[index]
            else:
                new_entry = table()
                new_entry[pattern] = rules  # type: ignore[index]
                per_file.append(new_entry)

        ruff_table["per-file-ignores"] = per_file  # type: ignore[index]

    def _normalize_lists(self) -> None:
        """Normalize and deduplicate lists."""

        def process_item(item: Item) -> Item:
            if isinstance(item, Table):
                new_table = table()
                for k in sorted(item.keys()):
                    new_table[k] = process_item(item[k])
                return new_table
            if isinstance(item, Array):
                seen: set[str] = set()
                new_array = array()
                for element in item:
                    processed = process_item(element)
                    key = dumps(
                        cast(Mapping[str, Any], processed),
                        sort_keys=True,
                    )
                    if key not in seen:
                        seen.add(key)
                        new_array.append(processed)
                return new_array
            return item

        if self.doc:
            processed = process_item(self.doc)
            self.doc = cast(TOMLDocument, processed)

    def _sort_keys_recursive(self, node: Item) -> None:
        """Recursively sort dictionary keys."""
        if isinstance(node, Table):
            keys: list[str] = sorted(node.keys())
            for key in keys:
                self._sort_keys_recursive(node[key])
                value = node.pop(key)
                node[key] = value
        elif isinstance(node, Array):
            for item in node:
                self._sort_keys_recursive(item)

    def save_changes(self) -> None:
        """Save changes with validation."""
        if self.doc is None:
            raise RuntimeError("No document to save")

        new_content = dumps(self.doc, sort_keys=True).strip() + "\n"

        try:
            parse(new_content)
        except Exception as e:
            msg = f"Generated invalid TOML: {e}"
            raise RuntimeError(msg) from e

        if new_content != self.original_content:
            backup = self.create_backup()
            print(f"Created backup at {backup}")  # noqa: T201
            self.file_path.write_text(new_content, encoding="utf-8")
            print("Changes applied successfully!")  # noqa: T201
        else:
            print("No changes required.")  # noqa: T201

    def run(self) -> None:
        """Execute full fixing process."""
        try:
            self.read_content()
            if not self.validate_toml():
                return

            self.load_file()
            self.apply_fixes()
            self.save_changes()

        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)  # noqa: T201
            sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(  # noqa: T201
            "Usage: python toml_fixer.py <file.toml>",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        fixer = TomlFixer(sys.argv[1])
        fixer.run()
    except Exception as e:  # pylint: disable=broad-except
        print(f"Critical error: {e}", file=sys.stderr)  # noqa: T201
        sys.exit(2)
