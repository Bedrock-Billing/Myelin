#!/usr/bin/env python3
"""
CMS Downloader Module (clean rewrite of ``cms_downloader.py``).

Downloads and organizes the CMS software JARs needed for the MS-DRG Grouper,
MCE Editor, IOCE, HHA/CMG groupers and the CMS Web Pricers, along with their
shared dependencies (GFC, gRPC/protobuf, SLF4J).

The public surface mirrors the original module:

    downloader = CMSDownloader(jars_dir="jars")
    downloader.build_jar_environment(clean_existing=False)
    downloader.print_jar_inventory()

Each "component" declares the JARs it must produce in ``REQUIRED_JARS``. Most
components are discovered by scraping a CMS page, downloading a ZIP and
extracting the matching JARs; a few dependencies are plain JAR downloads.
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

CMS_ROOT = "https://www.cms.gov"


class CMSDownloader:
    """Download and manage CMS software JAR files and their dependencies."""

    # --- Source pages -------------------------------------------------------
    CMS_URL = "https://www.cms.gov/pricersourcecodesoftware"
    MSDRG_URL = "https://www.cms.gov/medicare/payment/prospective-payment-systems/acute-inpatient-pps/ms-drg-classifications-and-software"
    IOCE_URL = "https://www.cms.gov/medicare/coding-billing/outpatient-code-editor-oce/quarterly-release-files"
    HHAG_URL = "https://www.cms.gov/medicare/payment/prospective-payment-systems/home-health/home-health-grouper-software"
    CMG_URL = "https://www.cms.gov/medicare/payment/prospective-payment-systems/inpatient-rehabilitation/grouper-case-mix-group"

    # --- Scraping markers ---------------------------------------------------
    TARGET_HEADER = "Software (Executable JAR Files)"
    ZIP_PATH_PATTERN = "/files/zip/"
    JAVA_SOURCE_PATTERN = "java-source.zip"
    JAVA_STANDALONE_PATTERN = "java-standalone"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    )

    # (connect, read) timeout in seconds applied to every HTTP request.
    TIMEOUT = (10, 300)

    # Number of pricer ZIPs downloaded concurrently (bounded to stay polite).
    MAX_PRICER_WORKERS = 4

    # --- Direct dependency JARs: component -> [(url, filename), ...] ---------
    DIRECT_JARS: dict[str, list[tuple[str, str]]] = {
        "slf4j": [
            (
                "https://repo1.maven.org/maven2/org/slf4j/slf4j-simple/2.0.9/slf4j-simple-2.0.9.jar",
                "slf4j-simple-2.0.9.jar",
            ),
            (
                "https://repo1.maven.org/maven2/org/slf4j/slf4j-api/2.0.9/slf4j-api-2.0.9.jar",
                "slf4j-api-2.0.9.jar",
            ),
        ],
        "gfc": [
            (
                "https://github.com/3mcloud/GFC-Grouper-Foundation-Classes/releases/download/v3.4.9/gfc-base-api-3.4.9.jar",
                "gfc-base-api-3.4.9.jar",
            ),
        ],
        "grpc": [
            (
                "https://repo1.maven.org/maven2/com/google/protobuf/protobuf-java/3.22.2/protobuf-java-3.22.2.jar",
                "protobuf-java-3.22.2.jar",
            ),
            (
                "https://repo1.maven.org/maven2/com/google/protobuf/protobuf-java/3.21.7/protobuf-java-3.21.7.jar",
                "protobuf-java-3.21.7.jar",
            ),
        ],
    }

    # Required JARs per component. Components in REGEX_COMPONENTS match by
    # regular expression (versions vary); the rest match by exact filename.
    REQUIRED_JARS: dict[str, list[str]] = {
        "slf4j": ["slf4j-simple-2.0.9.jar", "slf4j-api-2.0.9.jar"],
        "gfc": ["gfc-base-api-3.4.9.jar"],
        "grpc": ["protobuf-java-3.22.2.jar", "protobuf-java-3.21.7.jar"],
        "msdrg": [
            r"msdrg-binary-access-[\d\.]+\.jar",
            r"msdrg-model-v2-[\d\.]+\.jar",
            r"msdrg-(?:v\d+-|core-)[\d\.]+\.jar",
            r"MCE-[\d\.]+-?[\d\.]+\.jar",
            r"mce-proto-[\d\.]+\.jar",
            r"Utility-[\d\.]+\.jar",
        ],
        "ioce": [r"ioce-standalone-[\d\.]+\.jar"],
        "hhag": ["HomeHealth.jar"],
        "cmg": ["CMG_550.jar", "irf-proto-1.2.0.jar", "gfc-base-factory-3.4.9.jar"],
        "pricers": [
            r"esrd-pricer-[\w\-\.]+(?:\.jar|\.zip)",
            r"fqhc-pricer-[\w\-\.]+(?:\.jar|\.zip)",
            r"hha-pricer-[\w\-\.]+(?:\.jar|\.zip)",
            r"hospice-pricer-[\w\-\.]+(?:\.jar|\.zip)",
            r"ipf-pricer-[\w\-\.]+(?:\.jar|\.zip)",
            r"ipps-pricer-[\w\-\.]+(?:\.jar|\.zip)",
            r"irf-pricer-[\w\-\.]+(?:\.jar|\.zip)",
            r"ltch-pricer-[\w\-\.]+(?:\.jar|\.zip)",
            r"opps-pricer-[\w\-\.]+(?:\.jar|\.zip)",
            r"snf-pricer-[\w\-\.]+(?:\.jar|\.zip)",
        ],
    }

    # Components whose required entries / extracted JARs are matched by regex.
    REGEX_COMPONENTS = {"msdrg", "ioce", "pricers"}

    def __init__(
        self,
        jars_dir: str = "jars",
        download_dir: str = "downloads",
        log_level: int = logging.INFO,
    ) -> None:
        self.jars_dir = Path(jars_dir)
        self.download_dir = Path(download_dir)
        self.pricers_dir = self.jars_dir / "pricers"

        self.logger = self._configure_logging(log_level)

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.USER_AGENT})

        # Per-thread sessions for concurrent downloads (requests sessions are
        # not guaranteed safe to share across threads).
        self._thread_local = threading.local()

    # ------------------------------------------------------------------ #
    # Logging
    # ------------------------------------------------------------------ #
    @staticmethod
    def _configure_logging(log_level: int) -> logging.Logger:
        """Configure a dedicated logger without touching global logging state."""
        logger = logging.getLogger("cms_downloader")
        logger.setLevel(log_level)
        if not logger.handlers:
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            for handler in (
                logging.FileHandler("cms_downloads.log"),
                logging.StreamHandler(),
            ):
                handler.setFormatter(formatter)
                logger.addHandler(handler)
        logger.propagate = False
        return logger

    # ------------------------------------------------------------------ #
    # Inventory / completeness checks
    # ------------------------------------------------------------------ #
    @staticmethod
    def _jars_in(directory: Path) -> set[str]:
        if not directory.exists():
            return set()
        return {p.name for p in directory.iterdir() if p.suffix == ".jar"}

    def check_existing_jars(self) -> dict[str, set[str]]:
        """Return the JAR filenames currently present, by location."""
        return {
            "main": self._jars_in(self.jars_dir),
            "pricers": self._jars_in(self.pricers_dir),
        }

    def get_missing_jars_for_component(
        self, component: str, existing_jars: dict[str, set[str]] | None = None
    ) -> list[str]:
        """Return the required JARs for ``component`` that are not yet present."""
        if component not in self.REQUIRED_JARS:
            return []

        existing_jars = existing_jars or self.check_existing_jars()
        location = "pricers" if component == "pricers" else "main"
        existing = existing_jars[location]
        required = self.REQUIRED_JARS[component]

        if component in self.REGEX_COMPONENTS:
            return [
                pattern
                for pattern in required
                if not any(re.match(pattern, jar) for jar in existing)
            ]
        return list(set(required) - existing)

    def is_component_complete(
        self, component: str, existing_jars: dict[str, set[str]] | None = None
    ) -> bool:
        """True if every required JAR for ``component`` is present."""
        return not self.get_missing_jars_for_component(component, existing_jars)

    def get_all_missing_jars(self) -> dict[str, list[str]]:
        """Return ``{component: [missing, ...]}`` for incomplete components."""
        existing = self.check_existing_jars()
        return {
            component: missing
            for component in self.REQUIRED_JARS
            if (missing := self.get_missing_jars_for_component(component, existing))
        }

    def list_jar_inventory(self) -> dict:
        """Build a detailed inventory of JAR status by component."""
        existing = self.check_existing_jars()
        components: dict[str, dict] = {}
        complete_count = 0

        for component in self.REQUIRED_JARS:
            missing = self.get_missing_jars_for_component(component, existing)
            is_complete = not missing
            complete_count += is_complete
            components[component] = {
                "complete": is_complete,
                "missing_jars": missing,
                "jar_count": len(self.REQUIRED_JARS[component])
                if component in ("slf4j", "gfc", "grpc")
                else "variable",
            }

        return {
            "summary": {
                "main_jars_count": len(existing["main"]),
                "pricer_jars_count": len(existing["pricers"]),
                "components_complete": complete_count,
                "components_missing": len(self.REQUIRED_JARS) - complete_count,
            },
            "components": components,
            "existing_jars": existing,
        }

    def validate_jar_environment(self) -> dict:
        """Summarize whether every component is complete."""
        missing = self.get_all_missing_jars()
        is_valid = not missing
        return {
            "is_valid": is_valid,
            "missing_components": missing,
            "total_components": len(self.REQUIRED_JARS),
            "complete_components": len(self.REQUIRED_JARS) - len(missing),
            "status_message": "Environment is complete"
            if is_valid
            else f"Missing {len(missing)} components",
        }

    def print_jar_inventory(self) -> None:
        """Print a human-readable report of the current JAR inventory."""
        inventory = self.list_jar_inventory()
        summary = inventory["summary"]

        print("\n=== JAR Environment Inventory ===")
        print(f"Main directory JARs: {summary['main_jars_count']}")
        print(f"Pricer directory JARs: {summary['pricer_jars_count']}")
        print(f"Complete components: {summary['components_complete']}")
        print(f"Missing components: {summary['components_missing']}")

        print("\n=== Component Status ===")
        for component, status in inventory["components"].items():
            icon = "✓" if status["complete"] else "✗"
            label = "Complete" if status["complete"] else "Missing"
            print(f"{icon} {component.upper()}: {label}")
            for jar in status["missing_jars"]:
                print(f"    - Missing: {jar}")

        for location, title in (("main", "Main"), ("pricers", "Pricer")):
            jars = inventory["existing_jars"][location]
            if jars:
                print(f"\n=== {title} JAR Files ({len(jars)}) ===")
                for jar in sorted(jars):
                    print(f"  - {jar}")

    # ------------------------------------------------------------------ #
    # HTTP helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _filename_from_url(url: str) -> str:
        return url.split("/")[-1]

    def _get_soup(self, url: str) -> BeautifulSoup:
        """Fetch ``url`` and parse it into a BeautifulSoup document."""
        response = self.session.get(url, timeout=self.TIMEOUT)
        response.raise_for_status()
        return BeautifulSoup(response.content, "html.parser")

    def _stream_to_file(
        self, response: requests.Response, file_path: Path, show_progress: bool = True
    ) -> None:
        """Stream a response body to disk, optionally with a per-file progress bar."""
        total_size = int(response.headers.get("content-length", 0))
        with (
            open(file_path, "wb") as f,
            tqdm(
                desc=file_path.name,
                total=total_size,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
                disable=not show_progress,
            ) as bar,
        ):
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    bar.update(f.write(chunk))

    def download_file(
        self,
        url: str,
        filename: str,
        directory: Path | str | None = None,
        session: requests.Session | None = None,
        show_progress: bool = True,
    ) -> Path | None:
        """Download ``url`` to ``directory/filename``; return the path or None."""
        directory = Path(directory) if directory else self.download_dir
        directory.mkdir(parents=True, exist_ok=True)
        session = session or self.session
        try:
            response = session.get(url, stream=True, timeout=self.TIMEOUT)
            response.raise_for_status()
            file_path = directory / filename
            self._stream_to_file(response, file_path, show_progress=show_progress)
            self.logger.info(f"Successfully downloaded: {filename}")
            return file_path
        except Exception as e:
            self.logger.error(f"Error downloading {url}: {e}")
            return None

    # ------------------------------------------------------------------ #
    # ZIP extraction
    # ------------------------------------------------------------------ #
    def _extract_jars_from_zip(
        self,
        zip_path: Path | None,
        component: str,
        dest_dir: Path | None = None,
        wanted_jars: list[str] | None = None,
    ) -> None:
        """
        Extract JARs from ``zip_path`` (including one level of nested ZIPs) into
        ``dest_dir``.

        If ``wanted_jars`` is given, only JARs matching that list are moved
        (regex match for regex components, exact match otherwise). When it is
        None, every JAR is moved; a name collision is preserved by appending the
        component and a timestamp.
        """
        dest_dir = dest_dir or self.jars_dir
        if not zip_path or not Path(zip_path).exists():
            self.logger.error(f"ZIP file not found: {zip_path}")
            return

        zip_path = Path(zip_path)
        dest_dir.mkdir(parents=True, exist_ok=True)
        use_regex = component in self.REGEX_COMPONENTS
        self.logger.info(f"Processing ZIP file: {zip_path.name}")

        temp_dir = Path(tempfile.mkdtemp(prefix="temp_extract_", dir=self.download_dir))
        try:
            self._unzip(zip_path, temp_dir)

            # Expand one level of nested ZIPs (e.g. the CMG package). Skip
            # dot-prefixed entries (e.g. macOS "._" AppleDouble metadata files).
            for nested in list(temp_dir.rglob("*.zip")):
                if nested.name.startswith("."):
                    continue
                self.logger.info(f"Extracting nested ZIP: {nested.name}")
                self._unzip(nested, temp_dir / f"nested_{nested.stem}")

            jar_files = sorted(
                jar for jar in temp_dir.rglob("*.jar") if not jar.name.startswith(".")
            )
            self.logger.info(f"Found {len(jar_files)} JAR files in {component} package")

            moved = skipped = 0
            for jar in jar_files:
                name = jar.name

                if wanted_jars is not None and not self._jar_wanted(
                    name, wanted_jars, use_regex
                ):
                    skipped += 1
                    continue

                dest_path = dest_dir / name
                if dest_path.exists():
                    if wanted_jars is not None:
                        self.logger.warning(
                            f"JAR {name} was requested but already exists at destination"
                        )
                        skipped += 1
                        continue
                    # Keep both copies when moving everything.
                    dest_path = dest_dir / f"{jar.stem}_{component}_{int(time.time())}{jar.suffix}"

                shutil.move(str(jar), str(dest_path))
                self.logger.info(f"Moved {component} JAR file: {dest_path.name}")
                moved += 1

            self.logger.info(
                f"{component} JAR extraction complete. Moved {moved}, skipped {skipped}."
            )
        except Exception as e:
            self.logger.error(f"Error processing ZIP file {zip_path.name}: {e}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def _unzip(zip_path: Path, dest_dir: Path) -> None:
        dest_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as archive:
            archive.extractall(dest_dir)

    @staticmethod
    def _jar_wanted(name: str, wanted_jars: Iterable[str], use_regex: bool) -> bool:
        if use_regex:
            return any(re.match(pattern, name) for pattern in wanted_jars)
        return name in wanted_jars

    # ------------------------------------------------------------------ #
    # Component discovery / download
    # ------------------------------------------------------------------ #
    def _download_msdrg(self) -> Path | None:
        """Find and download the newest MS-DRG Java Source Code ZIP."""
        self.logger.info(f"Fetching MS-DRG files from: {self.MSDRG_URL}")
        soup = self._get_soup(self.MSDRG_URL)

        candidates: list[tuple[float, str, str]] = []
        for link in soup.find_all("a", href=True):
            for strong in link.find_all("strong"):
                text = strong.get_text() or ""
                if "Java Source Code" not in text:
                    continue
                href = link["href"]
                if ".zip" in href.lower():
                    version = self._msdrg_version(text, href)
                    candidates.append((version, href, text.strip()))
                    self.logger.info(
                        f"Found MS-DRG Java Source: {href} (version {version})"
                    )
                break

        if not candidates:
            self.logger.error("No MS-DRG Java Source Code links found")
            return None

        version, href, _text = max(candidates, key=lambda c: c[0])
        self.logger.info(f"Selected MS-DRG file: {href} (version {version})")

        download_url = urljoin(CMS_ROOT, href) if href.startswith("/") else href
        # CMS sometimes appends numeric suffixes like ".zip-11"; normalize them.
        filename = re.sub(r"\.zip-\d+$", ".zip", self._filename_from_url(href))
        return self.download_file(download_url, filename)

    @staticmethod
    def _msdrg_version(text: str, href: str) -> float:
        """Best-effort version number from the link text, falling back to the URL."""
        for pattern in (r"Version\s+(\d+(?:\.\d+)?)", r"v(\d+(?:\.\d+)?)"):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return float(match.group(1))

        for pattern in (r"v(\d+(?:\.\d+)?)", r"(\d+\.\d+)", r"(\d+)"):
            match = re.search(pattern, href, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    continue
        return 0.0

    def _download_ioce(self) -> Path | None:
        """Accept the IOCE license agreement and download the standalone ZIP."""
        self.logger.info(f"Connecting to IOCE website: {self.IOCE_URL}")
        soup = self._get_soup(self.IOCE_URL)

        standalone_href = None
        for link in soup.find_all("a"):
            href = link.get("href", "")
            if (
                self.JAVA_STANDALONE_PATTERN in href.lower()
                or "Java Standalone" in link.get_text()
            ):
                standalone_href = href
                self.logger.info(f"Found IOCE standalone Java link: {href}")
                break

        if not standalone_href:
            self.logger.error(
                f"Could not find '{self.JAVA_STANDALONE_PATTERN}' link on the IOCE page"
            )
            return None

        license_url = urljoin(self.IOCE_URL, standalone_href)
        license_soup = self._get_soup(license_url)

        form = next(
            (
                f
                for f in license_soup.find_all("form")
                if f.find("input", attrs={"name": "agree"})
            ),
            None,
        )
        if not form:
            self.logger.error("Could not find license agreement form")
            return None

        form_action = form.get("action", "")
        if not form_action:
            self.logger.error("Could not find form action URL")
            return None

        form_data = {
            tag["name"]: tag.get("value", "")
            for tag in form.find_all("input")
            if tag.get("name")
        }
        form_data["agree"] = "Yes"

        self.logger.info("Submitting license agreement form")
        response = self.session.post(
            urljoin(license_url, form_action),
            data=form_data,
            stream=True,
            timeout=self.TIMEOUT,
        )
        response.raise_for_status()

        filename = (
            self._filename_from_disposition(response)
            or f"ioce_java_standalone_{int(time.time())}.zip"
        )
        file_path = self.download_dir / filename
        self._stream_to_file(response, file_path)
        self.logger.info(f"Successfully downloaded IOCE file: {filename}")
        return file_path

    @staticmethod
    def _filename_from_disposition(response: requests.Response) -> str | None:
        content_disposition = response.headers.get("Content-Disposition", "")
        match = re.search(r"filename=(.+)", content_disposition)
        return match.group(1).strip("\"'") if match else None

    def _download_hhagrouper(self) -> Path | None:
        """Download the (non-GUI) HHA PPS grouper software ZIP."""
        self.logger.info(f"Connecting to HHAGrouper website: {self.HHAG_URL}")
        soup = self._get_soup(self.HHAG_URL)

        hh_href = None
        for link in soup.find_all("a", href=re.compile(r"hh-pps-grouper-software.*\.zip")):
            if "-gui" in link["href"]:
                continue
            hh_href = link["href"]
            break

        if not hh_href:
            self.logger.error(
                "Could not find 'hh-pps-grouper-software' link on the HHAGrouper page"
            )
            return None

        full_url = urljoin(self.HHAG_URL, hh_href)
        # CMS names these generically (e.g. "2025.zip"), so prefix for clarity.
        filename = f"hhgs-{self._filename_from_url(full_url)}"
        self.logger.info(f"Found HHAGrouper zip: {filename} ({full_url})")
        return self.download_file(full_url, filename)

    def _download_cmg(self) -> Path | None:
        """Download the CMG (IRF) grouper ZIP."""
        self.logger.info(f"Connecting to CMG website: {self.CMG_URL}")
        soup = self._get_soup(self.CMG_URL)

        cmg_href = next(
            (
                link["href"]
                for link in soup.find_all(
                    "a", href=re.compile(r"/files/zip/cmg-version-\d+-final\.zip")
                )
            ),
            None,
        )
        if not cmg_href:
            self.logger.error("Could not find 'cmg-grouper' link on the CMS page")
            return None

        full_url = urljoin(self.CMG_URL, cmg_href)
        filename = self._filename_from_url(full_url)
        self.logger.info(f"Found CMG Grouper zip: {filename} ({full_url})")
        return self.download_file(full_url, filename)

    # ------------------------------------------------------------------ #
    # Web Pricers
    # ------------------------------------------------------------------ #
    def map_url_to_jar_filename(self, url: str) -> str | None:
        """
        Map a pricer download URL to the JAR filename it produces.

        Example: ``ipps-pricer-2026-0-v2-11-0-executable-jar.zip`` ->
        ``ipps-pricer-application-2.11.0.jar``.
        """
        filename = self._filename_from_url(url)
        match = re.match(
            r"(\w+)-pricer-(\d+(?:-\d+)*)-v(\d+(?:-\d+)*)-executable(?:-jar)?\.zip",
            filename,
        )
        if not match:
            return None

        pricer_type = match.group(1)
        version = match.group(3).replace("-", ".")
        return f"{pricer_type}-pricer-application-{version}.jar"

    def _find_pricer_links(self) -> list[str]:
        """Scrape the executable-JAR pricer download links from the CMS page."""
        soup = self._get_soup(self.CMS_URL)

        header = next(
            (h2 for h2 in soup.find_all("h2") if self.TARGET_HEADER in h2.text), None
        )
        if not header:
            self.logger.error(f"Could not find section with header: {self.TARGET_HEADER}")
            return []

        links: list[str] = []
        node = header.next_sibling
        while node is not None and getattr(node, "name", None) != "h2":
            if getattr(node, "name", None) == "a" and self.ZIP_PATH_PATTERN in node.get(
                "href", ""
            ):
                links.append(node["href"])
            elif hasattr(node, "find_all"):
                links.extend(
                    a["href"]
                    for a in node.find_all("a", href=re.compile(self.ZIP_PATH_PATTERN))
                )
            node = node.next_sibling
        return links

    def _filter_pricer_links_for_missing(
        self, links: list[str], missing: list[str]
    ) -> list[str]:
        """Keep only the pricer links that map to a missing JAR."""
        filtered: list[str] = []
        for link in links:
            full_url = urljoin(self.CMS_URL, link)
            expected_jar = self.map_url_to_jar_filename(full_url)
            if expected_jar and any(re.match(p, expected_jar) for p in missing):
                filtered.append(link)
                self.logger.info(
                    f"Will download {self._filename_from_url(full_url)} for: {expected_jar}"
                )
            elif expected_jar:
                self.logger.info(
                    f"Skipping {self._filename_from_url(full_url)} (JAR already present)"
                )
            else:
                self.logger.warning(f"Could not map URL to a JAR filename: {full_url}")
        return filtered

    def download_web_pricers(self, force_all_downloads: bool = False) -> None:
        """Scrape, download and extract the CMS Web Pricer JARs into pricers/."""
        if not force_all_downloads and self.is_component_complete("pricers"):
            self.logger.info("All pricer JARs already present; skipping download")
            return

        links = self._find_pricer_links()
        if not links:
            self.logger.warning("No pricer download links found")
            return
        self.logger.info(f"Found {len(links)} potential pricer files")

        self.pricers_dir.mkdir(parents=True, exist_ok=True)

        if not force_all_downloads:
            missing = self.get_missing_jars_for_component("pricers")
            links = self._filter_pricer_links_for_missing(links, missing)
            if not links:
                self.logger.info("No pricer downloads needed")
                return

        # Download the pricer ZIPs concurrently, extracting each one on the main
        # thread as it finishes (downloads parallel, extraction serialized).
        succeeded = 0
        with ThreadPoolExecutor(max_workers=self.MAX_PRICER_WORKERS) as pool:
            futures = {pool.submit(self._download_pricer, link): link for link in links}
            for future in tqdm(
                as_completed(futures), total=len(futures), desc="pricers", unit="file"
            ):
                zip_path = future.result()
                if zip_path:
                    succeeded += 1
                    self._extract_jars_from_zip(
                        zip_path, "pricers", dest_dir=self.pricers_dir
                    )

        self.logger.info(f"Downloaded and extracted {succeeded} of {len(links)} pricer files")

    def _worker_session(self) -> requests.Session:
        """Return a requests session unique to the calling thread."""
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update({"User-Agent": self.USER_AGENT})
            self._thread_local.session = session
        return session

    def _download_pricer(self, link: str) -> Path | None:
        """Download a single pricer ZIP (runs on a pool thread)."""
        full_url = urljoin(self.CMS_URL, link)
        return self.download_file(
            full_url,
            self._filename_from_url(full_url),
            session=self._worker_session(),
            show_progress=False,
        )

    # ------------------------------------------------------------------ #
    # Build orchestration
    # ------------------------------------------------------------------ #
    def _install_zip_component(
        self,
        component: str,
        downloader: Callable[[], Path | None],
        force: bool,
        restrict_to_required: bool = False,
    ) -> None:
        """
        Download and extract a ZIP-based component if it is missing or forced.

        Normally a forced run extracts every JAR in the package; ``restrict_to_required``
        keeps only the component's declared JARs even under force. This matters for
        CMG, whose LIB archive bundles many third-party dependencies we don't want.
        """
        if not force and self.is_component_complete(component):
            self.logger.info(f"{component} components already exist, skipping download")
            return

        self.logger.info(f"Starting {component} file download process")
        zip_path = downloader()
        if not zip_path:
            return

        if restrict_to_required:
            wanted = self.REQUIRED_JARS[component]
        elif force:
            wanted = None
        else:
            wanted = self.get_missing_jars_for_component(component)
        self._extract_jars_from_zip(zip_path, component, wanted_jars=wanted)

    def _install_direct_jars(self, component: str, force: bool) -> None:
        """Download plain dependency JARs straight into the jars directory."""
        if not force and self.is_component_complete(component):
            self.logger.info(f"{component} JARs already exist, skipping download")
            return

        for url, filename in self.DIRECT_JARS[component]:
            self.logger.info(f"Downloading {component} JAR: {filename}")
            path = self.download_file(url, filename)
            if path:
                shutil.move(str(path), str(self.jars_dir / filename))
                self.logger.info(f"Moved {component} JAR to jars directory: {filename}")

    def _remove_unwanted_jars(self) -> None:
        """Drop source and GUI JARs that are downloaded but never used."""
        for pattern in ("*source*.jar", "*GUI*.jar"):
            for jar in self.jars_dir.glob(pattern):
                jar.unlink()
                self.logger.info(f"Removed unwanted JAR file: {jar}")

    def build_jar_environment(
        self, clean_existing: bool = True, force_download: bool = False
    ) -> bool:
        """Build the complete JAR environment required for processing."""
        try:
            if clean_existing and self.jars_dir.exists():
                shutil.rmtree(self.jars_dir)
            force = clean_existing or force_download

            self.jars_dir.mkdir(parents=True, exist_ok=True)
            self.download_dir.mkdir(parents=True, exist_ok=True)

            self.logger.info("Starting CMS Software download process")
            if not clean_existing:
                missing = self.get_all_missing_jars()
                self.logger.info(
                    f"Missing components: {list(missing)}"
                    if missing
                    else "All JAR components are already present"
                )

            # ZIP-based components.
            self._install_zip_component("msdrg", self._download_msdrg, force)
            self._install_zip_component("ioce", self._download_ioce, force)
            self._install_zip_component("hhag", self._download_hhagrouper, force)

            # Plain dependency JARs.
            self._install_direct_jars("gfc", force)
            self._install_direct_jars("grpc", force)
            self._install_direct_jars("slf4j", force)

            # CMG ships nested ZIPs whose LIB bundle contains many dependencies;
            # keep only our declared JARs even on a forced rebuild.
            self._install_zip_component(
                "cmg", self._download_cmg, force, restrict_to_required=True
            )

            # Web pricers live in their own subdirectory.
            self.download_web_pricers(force_all_downloads=force)

            # Clean up and prune unused JARs.
            shutil.rmtree(self.download_dir, ignore_errors=True)
            self._remove_unwanted_jars()

            self.logger.info("JAR environment build complete!")
            return True

        except Exception as e:
            self.logger.error(f"An unhandled error occurred: {e}")
            shutil.rmtree(self.download_dir, ignore_errors=True)
            return False


if __name__ == "__main__":
    downloader = CMSDownloader()

    print("Checking current JAR environment...")
    downloader.print_jar_inventory()

    if downloader.build_jar_environment(clean_existing=False):
        print("\nJAR environment build completed successfully!")
        downloader.print_jar_inventory()
        print(f"\nEnvironment Validation: {downloader.validate_jar_environment()['status_message']}")
    else:
        print("JAR environment build failed. Check logs for details.")
