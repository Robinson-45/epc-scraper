import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from dateutil import parser as date_parser

LOGGER = logging.getLogger("extractors.utils_validation")

RE_NUMBER = re.compile(r"[-+]?\d*\.?\d+")
RE_YEAR = re.compile(r"\b(19|20)\d{2}\b")

def parse_number(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    match = RE_NUMBER.search(value.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None

def parse_year(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    match = RE_YEAR.search(value)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None

def parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return date_parser.parse(value, dayfirst=True)
    except (ValueError, TypeError, OverflowError):
        return None

def is_expired(valid_till: Optional[str], reference: Optional[datetime] = None) -> Optional[bool]:
    if not valid_till:
        return None
    ref = reference or datetime.utcnow()
    dt = parse_date(valid_till)
    if not dt:
        return None
    return dt < ref

def normalize_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure all expected keys exist and derive computed fields like 'expired'.
    """
    defaults: Dict[str, Any] = {
        "url": None,
        "postCode": None,
        "locality": None,
        "address": None,
        "rating": None,
        "id": None,
        "propertyType": None,
        "floorArea": None,
        "currentScore": None,
        "potentialScore": None,
        "primaryUsage": None,
        "averageBill": None,
        "potentialSaving": None,
        "averageCostYear": None,
        "co2Produces": None,
        "co2Potential": None,
        "features": [],
        "changes": [],
        "assessorName": None,
        "assessorPhone": None,
        "assessorEmail": None,
        "accreditationScheme": None,
        "accreditationAssessorID": None,
        "accreditationPhone": None,
        "accreditationEmail": None,
        "assessmentDate": None,
        "certificateDate": None,
        "assessmentType": None,
        "validtillDate": None,
        "expired": None,
    }

    for key, default in defaults.items():
        record.setdefault(key, default)

    if record.get("expired") is None:
        record["expired"] = is_expired(record.get("validtillDate"))

    return record

def validate_epc_record(record: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors: List[str] = []

    required_fields = ("url", "id", "postCode", "address")
    for field in required_fields:
        if not record.get(field):
            errors.append(f"Missing required field '{field}'")

    if record.get("rating"):
        rating = str(record["rating"]).strip().upper()
        # Accept strings like "75 C" or "C" or "79 C"
        parts = rating.split()
        band = parts[-1]
        if band not in list("ABCDEFG"):
            errors.append(f"Unexpected rating band: {record['rating']}")

    if record.get("validtillDate") and record.get("expired") is None:
        errors.append("validtillDate present but expired flag missing")

    return len(errors) == 0, errors