import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

from extractors.epc_parser import EPCParser
from extractors import utils_validation
from monitoring.tracker import (
    load_state,
    save_state,
    detect_changes,
)
from outputs.exporters import export_all

def configure_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        config = json.load(f)
    return config

def load_input_urls(path: Path) -> List[str]:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        # allow a plain list of URLs
        return [str(u) for u in data]

    listing_urls = data.get("listingUrls") or data.get("urls") or []
    return [str(u) for u in listing_urls]

def deduplicate_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = {}
    anonymous_counter = 0

    for rec in records:
        rec_id = rec.get("id")
        if not rec_id:
            anonymous_counter += 1
            rec_id = f"anonymous-{anonymous_counter}"
            rec["id"] = rec_id
        seen[rec_id] = rec
    return list(seen.values())

def crawl_full(
    listing_urls: List[str],
    parser: EPCParser,
) -> List[Dict[str, Any]]:
    logger = logging.getLogger("main.full_crawl")
    all_records: List[Dict[str, Any]] = []

    for url in listing_urls:
        logger.info("Processing listing URL: %s", url)
        listing_html = parser.fetch_listing_page(url)
        if listing_html is None:
            logger.error("Failed to fetch listing page: %s", url)
            continue

        certificate_urls = parser.parse_listing_page(listing_html, base_url=url)
        logger.info("Found %d certificate URLs for listing %s", len(certificate_urls), url)

        for cert_url in certificate_urls:
            cert_html = parser.fetch_certificate(cert_url)
            if cert_html is None:
                logger.warning("Skipping certificate due to fetch error: %s", cert_url)
                continue

            try:
                record = parser.parse_certificate_page(cert_html, url=cert_url)
                record["url"] = cert_url  # ensure URL is present

                # normalize and validate
                record = utils_validation.normalize_record(record)
                is_valid, errors = utils_validation.validate_epc_record(record)
                if not is_valid:
                    logger.warning(
                        "Validation problems for certificate %s: %s", record.get("id"), "; ".join(errors)
                    )
                all_records.append(record)
            except Exception as exc:  # pragma: no cover - safety net
                logger.exception("Unexpected error parsing certificate %s: %s", cert_url, exc)

    return all_records

def run_from_config(args: argparse.Namespace) -> int:
    config_path = Path(args.config).resolve()
    config = load_config(config_path)

    input_file = Path(config.get("inputFile", "data/sample_input.json")).resolve()
    output_dir = Path(config.get("outputDir", "data")).resolve()
    formats = config.get("formats", ["json"])
    monitoring_mode = config.get("monitoring", False)

    if args.full:
        monitoring_mode = False
    if args.monitor:
        monitoring_mode = True

    state_file = Path(config.get("stateFile", "data/epc_state.json")).resolve()
    request_delay = float(config.get("requestDelaySeconds", 0.2))

    listing_urls = load_input_urls(input_file)
    if not listing_urls:
        logging.getLogger("main").error("No listing URLs provided in %s", input_file)
        return 1

    parser = EPCParser(delay_seconds=request_delay)

    # Full crawl
    records = crawl_full(listing_urls, parser)
    records = deduplicate_records(records)

    if monitoring_mode:
        logging.getLogger("main").info("Running in monitoring mode.")
        previous_ids = load_state(state_file)
        new_records, removed_records, updated_id_set = detect_changes(records, previous_ids)
        logging.getLogger("main").info(
            "Monitoring diff: %d new, %d removed",
            len(new_records),
            len(removed_records),
        )
        output_records = new_records + removed_records
        save_state(state_file, updated_id_set)
    else:
        logging.getLogger("main").info("Running in full scrape mode.")
        output_records = records

    output_dir.mkdir(parents=True, exist_ok=True)
    export_all(
        records=output_records,
        output_dir=output_dir,
        base_name="epc_results",
        formats=formats,
    )

    logging.getLogger("main").info(
        "Exported %d records to %s (formats: %s)",
        len(output_records),
        output_dir,
        ", ".join(formats),
    )
    return 0

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="EPC Data Scraper - scrape UK EPC certificate data."
    )
    parser.add_argument(
        "-c",
        "--config",
        default="src/config/settings.example.json",
        help="Path to JSON config file (default: src/config/settings.example.json)",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--full",
        action="store_true",
        help="Force full scrape mode (ignore monitoring flag in config).",
    )
    mode_group.add_argument(
        "--monitor",
        action="store_true",
        help="Force monitoring mode (ignore monitoring flag in config).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v, -vv).",
    )
    return parser

def main(argv: List[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)

    try:
        return run_from_config(args)
    except KeyboardInterrupt:
        logging.getLogger("main").warning("Interrupted by user.")
        return 130
    except Exception as exc:  # pragma: no cover - safety net
        logging.getLogger("main").exception("Fatal error: %s", exc)
        return 1

if __name__ == "__main__":
    sys.exit(main())