import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple

LOGGER = logging.getLogger("monitoring.tracker")

def load_state(path: Path) -> Set[str]:
    if not path.exists():
        LOGGER.info("No previous monitoring state found at %s.", path)
        return set()
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return {str(x) for x in data}
        if isinstance(data, dict) and "ids" in data:
            return {str(x) for x in data["ids"]}
        return set()
    except json.JSONDecodeError as exc:
        LOGGER.error("Invalid state file %s: %s", path, exc)
        return set()

def save_state(path: Path, ids: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"ids": sorted(set(ids))}
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    LOGGER.info("Saved monitoring state (%d IDs) to %s", len(data["ids"]), path)

def detect_changes(
    current_records: List[Dict[str, Any]],
    previous_ids: Set[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Set[str]]:
    """
    Returns:
        new_records: records with IDs not in previous_ids
        removed_records: stub records for IDs that were present before but are now missing
        updated_id_set: union of previous and current IDs
    """
    current_ids: Set[str] = set()
    new_records: List[Dict[str, Any]] = []

    for rec in current_records:
        rec_id = rec.get("id")
        if not rec_id:
            continue
        current_ids.add(rec_id)
        if rec_id not in previous_ids:
            new_records.append(rec)

    removed_ids = previous_ids - current_ids
    removed_records: List[Dict[str, Any]] = [
        {
            "id": epc_id,
            "removed": True,
        }
        for epc_id in sorted(removed_ids)
    ]

    updated_id_set = previous_ids.union(current_ids)
    return new_records, removed_records, updated_id_set