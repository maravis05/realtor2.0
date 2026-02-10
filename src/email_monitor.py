"""Monitor Gmail via IMAP for Zillow listing alert emails."""

from __future__ import annotations

import email
import imaplib
import logging
import re
from dataclasses import dataclass
from email.message import Message

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

ZILLOW_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?zillow\.com/homedetails/(?:[^\s\"'<>]*?/)?(\d+)_zpid/?",
    re.IGNORECASE,
)

# "New Listing:" emails use a different URL format with zpid_target instead of homedetails
ZPID_TARGET_PATTERN = re.compile(
    r"zpid_target(?:/|%2F)(\d+)_zpid",
    re.IGNORECASE,
)


@dataclass
class ListingLink:
    url: str
    zpid: str
    address: str  # e.g. "408 Manchester Road, Auburn, NH"
    price: int = 0  # listing price from email, e.g. 485000


def connect(email_addr: str, app_password: str) -> imaplib.IMAP4_SSL:
    """Connect and authenticate to Gmail via IMAP."""
    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    imap.login(email_addr, app_password)
    return imap


def _extract_listing_data_from_html(html: str, subject: str = "") -> list[ListingLink]:
    """Extract listing data (URL, ZPID, address) from Zillow alert email HTML.

    Handles multiple Zillow email formats:
    - "Liked homes" digests use mw502 tables with homedetails URLs
    - "New Listing:" alerts use mw504 tables with zpid_target URLs
    - "Open House" alerts use mw502 for the primary + mw504 for similar homes

    Recommendations / "similar homes" sections are excluded.
    """
    # Strip recommendation sections so we only parse primary listings
    parse_html = html
    for marker in ["Our recommendations for you", "Check out these similar homes"]:
        idx = html.find(marker)
        if idx != -1:
            parse_html = html[:idx]
            logger.debug("Truncated email HTML at %r", marker)
            break

    soup = BeautifulSoup(parse_html, "lxml")
    links: list[ListingLink] = []
    seen_zpids: set[str] = set()

    # Strategy 1: Parse structured listing blocks from Zillow alert emails.
    # Liked-homes/open-house emails use "mw502", new-listing emails use "mw504".
    for table in soup.find_all("table", class_=re.compile(r"mw50[24]")):
        # Find the ZPID. Zillow wraps <a> hrefs in click-tracking redirects
        # (click.mail.zillow.com), so the real URLs only appear in VML markup
        # that BeautifulSoup can't parse as tags. Search the raw HTML instead.
        zpid = None
        url = None
        block_html = str(table)

        # Try homedetails URL first (liked-homes/open-house emails)
        match = ZILLOW_URL_PATTERN.search(block_html)
        if match:
            zpid = match.group(1)
            url = match.group(0).rstrip("/") + "/"
        else:
            # Fall back to zpid_target URL (new-listing emails)
            match = ZPID_TARGET_PATTERN.search(block_html)
            if match:
                zpid = match.group(1)
                url = f"https://www.zillow.com/homedetails/{zpid}_zpid/"

        if not zpid or not url or zpid in seen_zpids:
            continue

        address = _extract_address_from_block(table)
        if not address:
            address = _address_from_url(url)

        price = _extract_price_from_block(table)

        seen_zpids.add(zpid)
        links.append(ListingLink(url=url, zpid=zpid, address=address, price=price))

    # Strategy 2: If no structured blocks found, fall back to scanning all links
    # and trying to find nearby address text.
    if not links:
        links = _extract_urls_with_address_fallback(soup, html, seen_zpids)

    return links


def _extract_address_from_block(block: BeautifulSoup) -> str:
    """Extract a street address from a listing block element.

    Searches for text that looks like a US street address within the block.
    """
    # Common pattern: address is in a text node or <p>/<td>/<a> near the link
    text = block.get_text(separator="\n", strip=True)
    # Look for lines that resemble an address (number + street name + city/state)
    for line in text.split("\n"):
        line = line.strip()
        # Match patterns like "123 Main St, City, ST" or "123 Main St, City, ST 12345"
        if re.match(r"\d+\s+\w+.*,\s*\w+.*,\s*[A-Z]{2}", line):
            return line
    return ""


def _extract_price_from_block(block: BeautifulSoup) -> int:
    """Extract listing price from a listing block element.

    Zillow email alerts show the price in an <h5> tag like "$485,000".
    """
    h5 = block.find("h5")
    if h5:
        text = h5.get_text(strip=True)
        # Strip "$" and "," to get a plain number
        cleaned = text.replace("$", "").replace(",", "")
        try:
            return int(cleaned)
        except ValueError:
            pass
    return 0


def _address_from_url(url: str) -> str:
    """Extract a rough address from a Zillow URL slug.

    e.g. ".../homedetails/123-Main-St-City-ST-12345/..." → "123 Main St City ST 12345"
    """
    match = re.search(r"/homedetails/([^/]+)/\d+_zpid", url)
    if match:
        slug = match.group(1)
        return slug.replace("-", " ")
    return ""


def _extract_urls_with_address_fallback(
    soup: BeautifulSoup, html: str, seen_zpids: set[str]
) -> list[ListingLink]:
    """Fallback: extract URLs from all <a> tags and raw text, with best-effort address."""
    links: list[ListingLink] = []

    # Check all <a> tags
    for tag in soup.find_all("a", href=True):
        href = tag["href"]
        match = ZILLOW_URL_PATTERN.search(href)
        if match:
            zpid = match.group(1)
            if zpid not in seen_zpids:
                seen_zpids.add(zpid)
                clean_url = match.group(0).rstrip("/") + "/"
                address = _address_from_url(clean_url)
                links.append(ListingLink(url=clean_url, zpid=zpid, address=address))

    # Also search raw text for URLs
    for match in ZILLOW_URL_PATTERN.finditer(html):
        zpid = match.group(1)
        if zpid not in seen_zpids:
            seen_zpids.add(zpid)
            clean_url = match.group(0).rstrip("/") + "/"
            address = _address_from_url(clean_url)
            links.append(ListingLink(url=clean_url, zpid=zpid, address=address))

    return links


def _get_html_body(msg: Message) -> str:
    """Extract the HTML body from an email message."""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
    else:
        if msg.get_content_type() == "text/html":
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")

    # Fall back to plain text
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
    return ""


def fetch_new_listing_urls(
    imap: imaplib.IMAP4_SSL,
    mark_read: bool = True,
) -> list[ListingLink]:
    """Fetch unread Zillow emails and extract listing data.

    Returns deduplicated list of ListingLink objects with addresses.
    """
    imap.select("INBOX")

    # Search for unread emails from Zillow
    status, data = imap.search(None, '(UNSEEN FROM "zillow.com")')
    if status != "OK" or not data[0]:
        logger.info("No new Zillow emails found")
        return []

    msg_ids = data[0].split()
    logger.info("Found %d unread Zillow email(s)", len(msg_ids))

    all_links: list[ListingLink] = []
    seen_zpids: set[str] = set()

    for msg_id in msg_ids:
        status, msg_data = imap.fetch(msg_id, "(RFC822)")
        if status != "OK" or not msg_data[0]:
            continue

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)
        subject = msg.get("Subject", "(no subject)")
        logger.info("Processing email: %s", subject)
        html_body = _get_html_body(msg)

        if not html_body:
            logger.debug("No HTML body in email %s", msg_id)
            continue

        links = _extract_listing_data_from_html(html_body, subject=subject)
        for link in links:
            if link.zpid not in seen_zpids:
                seen_zpids.add(link.zpid)
                all_links.append(link)

        # Mark as read so we don't reprocess
        if mark_read:
            imap.store(msg_id, "+FLAGS", "\\Seen")

    logger.info("Extracted %d unique listing(s) from emails", len(all_links))
    return all_links


def disconnect(imap: imaplib.IMAP4_SSL) -> None:
    """Cleanly close the IMAP connection."""
    try:
        imap.close()
    except Exception:
        pass
    try:
        imap.logout()
    except Exception:
        pass
