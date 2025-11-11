import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from extractors import utils_validation

LOGGER = logging.getLogger("extractors.epc_parser")

DEFAULT_BASE = "https://find-energy-certificate.service.gov.uk"

@dataclass
class EPCParserConfig:
    timeout_seconds: int = 20
    delay_seconds: float = 0.0
    base_url: str = DEFAULT_BASE

class EPCParser:
    def __init__(
        self,
        session: Optional[requests.Session] = None,
        delay_seconds: float = 0.0,
        base_url: str = DEFAULT_BASE,
    ) -> None:
        self.session = session or requests.Session()
        self.config = EPCParserConfig(delay_seconds=delay_seconds, base_url=base_url)

    # ----- HTTP helpers -------------------------------------------------

    def _request(self, url: str) -> Optional[str]:
        try:
            LOGGER.debug("Fetching URL: %s", url)
            resp = self.session.get(url, timeout=self.config.timeout_seconds)
            if resp.status_code != 200:
                LOGGER.warning("Non-200 status %s for URL %s", resp.status_code, url)
                return None
            return resp.text
        except requests.RequestException as exc:
            LOGGER.error("Request error for %s: %s", url, exc)
            return None
        finally:
            if self.config.delay_seconds > 0:
                time.sleep(self.config.delay_seconds)

    def fetch_listing_page(self, url: str) -> Optional[str]:
        return self._request(url)

    def fetch_certificate(self, url: str) -> Optional[str]:
        return self._request(url)

    # ----- Listing parsing ----------------------------------------------

    @staticmethod
    def _build_absolute_url(href: str, base_url: str) -> str:
        if href.startswith("http://") or href.startswith("https://"):
            return href
        if href.startswith("/"):
            return urljoin(DEFAULT_BASE, href)
        return urljoin(base_url, href)

    def parse_listing_page(self, html: str, base_url: str) -> List[str]:
        soup = BeautifulSoup(html, "lxml")
        certificate_urls: Set[str] = set()

        # heuristic: EPC certificate links contain '/energy-certificate/'
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/energy-certificate/" in href:
                full = self._build_absolute_url(href, base_url)
                certificate_urls.add(full)

        # Fallback: some pages might expose direct certificate URLs in text
        if not certificate_urls:
            text = soup.get_text(" ", strip=True)
            token_prefix = "/energy-certificate/"
            for token in text.split():
                if token_prefix in token:
                    href = token[token.find(token_prefix) :]
                    certificate_urls.add(self._build_absolute_url(href, base_url))

        LOGGER.debug("Parsed %d certificate URLs from listing.", len(certificate_urls))
        return sorted(certificate_urls)

    # ----- Certificate parsing ------------------------------------------

    @staticmethod
    def _first_text(soup: BeautifulSoup, selectors: Iterable[str]) -> Optional[str]:
        for sel in selectors:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                return el.get_text(strip=True)
        return None

    @staticmethod
    def _text_after_label(soup: BeautifulSoup, label: str) -> Optional[str]:
        """
        Generic helper that finds a label (dt, th, strong, etc.) and returns
        text from the adjacent element (dd, td, span, etc.).
        """
        label = label.lower()
        for tag_name in ("dt", "th", "strong", "span", "p", "label"):
            for tag in soup.find_all(tag_name):
                if label in tag.get_text(" ", strip=True).lower():
                    # try a sibling
                    sib = tag.find_next_sibling()
                    if sib and sib.get_text(strip=True):
                        return sib.get_text(strip=True)
                    # or parent-based
                    if tag.parent and tag.parent is not tag:
                        parent_text = tag.parent.get_text(" ", strip=True)
                        if parent_text:
                            return parent_text
        return None

    @staticmethod
    def _parse_features(soup: BeautifulSoup) -> List[Dict[str, Any]]:
        features: List[Dict[str, Any]] = []

        # try table with headings like "Feature / Description / Rating"
        tables = soup.find_all("table")
        for table in tables:
            headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            if not headers:
                continue
            if not any("feature" in h for h in headers):
                continue

            # assume first 3 columns: name, description, rating
            for row in table.find_all("tr")[1:]:
                cols = row.find_all(["td", "th"])
                if not cols:
                    continue
                name = cols[0].get_text(strip=True) if len(cols) > 0 else None
                description = cols[1].get_text(strip=True) if len(cols) > 1 else None
                rating = cols[2].get_text(strip=True) if len(cols) > 2 else None
                if name or description or rating:
                    features.append(
                        {
                            "name": name,
                            "description": description,
                            "rating": rating,
                        }
                    )
        return features

    @staticmethod
    def _parse_changes(soup: BeautifulSoup) -> List[Dict[str, Any]]:
        changes: List[Dict[str, Any]] = []

        # look for sections that mention "Suggested improvements" or similar
        for header in soup.find_all(["h2", "h3", "h4"]):
            header_text = header.get_text(" ", strip=True).lower()
            if "improvement" not in header_text and "recommended measure" not in header_text:
                continue

            for table in header.find_all_next("table", limit=2):
                for row in table.find_all("tr")[1:]:
                    cols = row.find_all(["td", "th"])
                    if not cols:
                        continue
                    name = cols[0].get_text(strip=True) if len(cols) > 0 else None
                    installation_cost = cols[1].get_text(strip=True) if len(cols) > 1 else None
                    yearly_saving = cols[2].get_text(strip=True) if len(cols) > 2 else None
                    potential_rating = cols[3].get_text(strip=True) if len(cols) > 3 else None
                    if name or installation_cost or yearly_saving or potential_rating:
                        changes.append(
                            {
                                "name": name,
                                "installationCost": installation_cost,
                                "yearlySaving": yearly_saving,
                                "potentialRating": potential_rating,
                            }
                        )
                break  # don't process more than one table per header
        return changes

    def parse_certificate_page(self, html: str, url: str) -> Dict[str, Any]:
        soup = BeautifulSoup(html, "lxml")

        record: Dict[str, Any] = {
            "url": url,
        }

        # ID - try to extract from URL first
        try:
            path = urlparse(url).path
            if "/energy-certificate/" in path:
                record["id"] = path.split("/energy-certificate/")[-1].strip("/")
        except Exception:  # pragma: no cover - defensive
            pass

        # fallback: explicit label
        if not record.get("id"):
            id_text = self._text_after_label(soup, "Certificate number")
            if id_text:
                record["id"] = id_text.split()[0]

        # Basic location info
        record["postCode"] = self._text_after_label(soup, "Postcode")
        record["locality"] = self._text_after_label(soup, "Town")
        record["address"] = self._text_after_label(soup, "Address")

        # Ratings and scores
        record["rating"] = self._first_text(
            soup,
            [
                ".epc-rating",
                ".rating-band",
                "span.epc-rating",
                "p.epc-rating",
            ],
        ) or self._text_after_label(soup, "Rating")

        record["propertyType"] = self._text_after_label(soup, "Property type")
        record["floorArea"] = self._text_after_label(soup, "Total floor area")
        record["currentScore"] = self._text_after_label(soup, "Current rating")
        record["potentialScore"] = self._text_after_label(soup, "Potential rating")

        # numerical cost/CO2-related fields
        record["primaryUsage"] = utils_validation.parse_number(
            self._text_after_label(soup, "Primary energy use")
        )
        record["averageBill"] = utils_validation.parse_number(
            self._text_after_label(soup, "Current costs")
        )
        record["potentialSaving"] = utils_validation.parse_number(
            self._text_after_label(soup, "Potential savings")
        )
        record["averageCostYear"] = utils_validation.parse_year(
            self._text_after_label(soup, "Based on")
        )

        record["co2Produces"] = utils_validation.parse_number(
            self._text_after_label(soup, "Current emissions")
        )
        record["co2Potential"] = utils_validation.parse_number(
            self._text_after_label(soup, "Potential emissions")
        )

        # Features and recommended changes
        record["features"] = self._parse_features(soup)
        record["changes"] = self._parse_changes(soup)

        # Assessor details
        record["assessorName"] = self._text_after_label(soup, "Assessor's name")
        record["assessorPhone"] = self._text_after_label(soup, "Assessor's phone")
        record["assessorEmail"] = self._text_after_label(soup, "Assessor's email")

        record["accreditationScheme"] = self._text_after_label(soup, "Accreditation scheme")
        record["accreditationAssessorID"] = self._text_after_label(
            soup, "Accreditation number"
        )
        record["accreditationPhone"] = self._text_after_label(
            soup, "Accreditation scheme phone"
        )
        record["accreditationEmail"] = self._text_after_label(
            soup, "Accreditation scheme email"
        )

        # Dates and meta
        record["assessmentDate"] = self._text_after_label(soup, "Date of assessment")
        record["certificateDate"] = self._text_after_label(soup, "Date of certificate")
        record["assessmentType"] = self._text_after_label(soup, "Type of assessment")
        record["validtillDate"] = self._text_after_label(soup, "Expiry date")

        # expired flag will be set in normalize_record
        return record