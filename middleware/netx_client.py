"""
netx_client.py
Reusable functions for talking to the NetX JSON-RPC API:
authentication, making a call, and looking assets up by EMu IRN.
"""
import logging
import time

import requests

from . import config

logger = logging.getLogger(__name__)

# NetX attribute that holds the EMu IRN - the same one syncedMetadata.xml
# links on (<link field="irn" attribute="IRN"/>).
IRN_ATTRIBUTE = "IRN"
ACCESSION_ATTRIBUTE = "Accession Number"

# (connect, read) seconds
DEFAULT_TIMEOUT = (15, 60)


class NetXAPIError(Exception):
    """Raised when the NetX API can't be reached, returns a non-2xx response,
    or returns a JSON-RPC error.

    Wraps the underlying requests exception so callers get one exception type
    to catch and log, same as emu_client.EMuAPIError.
    """


def get_rpc_url():
    """NETX_BASE_URL -> the JSON-RPC endpoint. Accepts the base with or
    without a trailing /api."""
    if not config.NETX_BASE_URL:
        raise NetXAPIError("NETX_BASE_URL is not set in .env")
    base_url = config.NETX_BASE_URL
    if not base_url.endswith("/api"):
        base_url += "/api"
    return base_url + "/rpc/"


def get_session():
    """A requests.Session carrying the NetX API token.

    Make one and pass it as `session` when making many calls in a row, so
    they share a connection instead of each opening a new one.
    """
    if not config.NETX_API_TOKEN:
        raise NetXAPIError("NETX_API_TOKEN is not set in .env")
    session = requests.Session()
    session.headers.update({"Authorization": "apiToken " + config.NETX_API_TOKEN})
    return session


def call(method, params, session=None, timeout=DEFAULT_TIMEOUT):
    """
    Call a NetX JSON-RPC method and return its 'result'.
    See https://developer.netx.net/ for the methods and their params.
    """
    if session is None:
        session = get_session()

    request_body = {"jsonrpc": "2.0", "id": "1", "method": method, "params": params}

    try:
        resp = session.post(get_rpc_url(), json=request_body, timeout=timeout)
        if resp.status_code != 200:
            logger.error("NetX returned %s for %s: %s", resp.status_code, method, resp.text[:1000])
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        raise NetXAPIError(f"NetX call '{method}' failed: {e}") from e
    except ValueError as e:
        raise NetXAPIError(f"NetX returned an unparseable response for '{method}': {e}") from e

    # JSON-RPC errors come back as HTTP 200 with an 'error' member
    if "result" not in data:
        raise NetXAPIError(f"NetX call '{method}' returned an error: {data.get('error', data)}")

    return data["result"]


def find_assets_by_irn(irn, session=None, timeout=DEFAULT_TIMEOUT):
    """
    Return the NetX assets whose IRN attribute is exactly `irn` - an empty
    list if there are none, more than one if the IRN is duplicated in NetX.
    See https://developer.netx.net/#getassetsbyquery
    """
    irn = str(irn)
    result = call(
        "getAssetsByQuery",
        [
            {
                "query": [
                    {
                        "operator": "and",
                        "exact": {"attribute": IRN_ATTRIBUTE, "value": irn},
                    }
                ]
            },
            {
                "page": {"startIndex": 0, "size": 50},
                "data": ["asset.id", "asset.base", "asset.file", "asset.attributes"],
            },
        ],
        session=session,
        timeout=timeout,
    )

    # Guard against loose matches - keep only assets whose IRN attribute is this IRN
    matches = []
    for asset in result.get("results", []):
        attributes = asset.get("attributes")
        if attributes is None:
            matches.append(asset)
            continue

        asset_irns = attributes.get(IRN_ATTRIBUTE, [])
        if not isinstance(asset_irns, list):
            asset_irns = [asset_irns]
        if irn in [str(asset_irn).strip() for asset_irn in asset_irns]:
            matches.append(asset)

    return matches


def get_asset_filename(asset):
    """An asset's filename, or '' if the API didn't return one."""
    file_data = asset.get("file")
    if isinstance(file_data, dict) and file_data.get("name"):
        return file_data["name"]
    return asset.get("fileName") or asset.get("name") or ""


# One OR-ed getAssetsByQuery covers IRN_BATCH_SIZE IRNs. One IRN can match
# many assets (IRN 229430 -> 24), so a batch may return far more assets than
# IRNs; results are paged IRN_PAGE_SIZE at a time.
IRN_BATCH_SIZE = 25
IRN_PAGE_SIZE = 500


def irn_index_is_populated(session=None, timeout=DEFAULT_TIMEOUT):
    """Canary for unattended runs: True if NetX returns at least one asset
    that has any value in the IRN attribute.

    A Solr outage makes getAssetsByQuery return zero results instead of an
    error, so a zero-match is only trustworthy when this is True.
    """
    result = call(
        "getAssetsByQuery",
        [
            {"query": [{"operator": "and", "exists": {"attribute": IRN_ATTRIBUTE}}]},
            {"page": {"startIndex": 0, "size": 1}, "data": ["asset.id"]},
        ],
        session=session,
        timeout=timeout,
    )
    return bool(result.get("results"))


def find_existing_irns(irns, session=None, batch_size=IRN_BATCH_SIZE, timeout=DEFAULT_TIMEOUT):
    """Return the set of IRNs (as stripped strings) from `irns` that have at
    least one asset in NetX.

    Batched: each call ORs `batch_size` exact-IRN clauses together. Raises
    NetXAPIError on any failure so the caller never mistakes an error for
    'not found'.
    """
    if session is None:
        session = get_session()
    wanted = [str(irn).strip() for irn in irns]
    found = set()
    for start in range(0, len(wanted), batch_size):
        batch = set(wanted[start:start + batch_size])
        query = [
            {"operator": "or", "exact": {"attribute": IRN_ATTRIBUTE, "value": irn}}
            for irn in sorted(batch)
        ]
        found |= _irns_matched_by_query(query, batch, session, timeout)
    return found


def _irns_matched_by_query(query, batch, session, timeout):
    """Page through one OR-ed query and collect which IRNs of `batch` appear
    in the returned assets' IRN attribute (guards against loose matches)."""
    matched = set()
    start = 0
    while True:
        result = call(
            "getAssetsByQuery",
            [
                {"query": query},
                {
                    "page": {"startIndex": start, "size": IRN_PAGE_SIZE},
                    "data": ["asset.id", "asset.attributes"],
                },
            ],
            session=session,
            timeout=timeout,
        )
        assets = result.get("results", [])
        for asset in assets:
            attributes = asset.get("attributes")
            if attributes is None:
                raise NetXAPIError(
                    "getAssetsByQuery returned an asset without attributes; "
                    "cannot tell which IRN it matched"
                )
            asset_irns = attributes.get(IRN_ATTRIBUTE, [])
            if not isinstance(asset_irns, list):
                asset_irns = [asset_irns]
            for asset_irn in asset_irns:
                asset_irn = str(asset_irn).strip()
                if asset_irn in batch:
                    matched.add(asset_irn)
        if matched == batch or len(assets) < IRN_PAGE_SIZE:
            return matched
        start += IRN_PAGE_SIZE


def find_recent_assets_without_irn(days, session=None, page_size=100, timeout=DEFAULT_TIMEOUT):
    """Assets imported in the last `days` days that have no value in the IRN
    attribute (used by sweep.py). Returns the raw asset dicts (id, base,
    file, attributes).

    All pages are read BEFORE the caller changes anything: tagging an asset
    removes it from this result set, which would shift later pages and skip
    assets if the caller wrote while paging.
    """
    if session is None:
        session = get_session()
    since_ms = int((time.time() - days * 86400) * 1000)
    query = [
        {"operator": "and", "range": {
            "field": "importDate", "min": str(since_ms), "max": None,
            "includeMin": True, "includeMax": True,
        }},
        {"operator": "not", "exists": {"attribute": IRN_ATTRIBUTE}},
    ]
    assets = []
    start = 0
    while True:
        result = call(
            "getAssetsByQuery",
            [
                {"query": query},
                {
                    "page": {"startIndex": start, "size": page_size},
                    "data": ["asset.id", "asset.base", "asset.file", "asset.attributes"],
                },
            ],
            session=session,
            timeout=timeout,
        )
        page = result.get("results", [])
        assets.extend(page)
        if len(page) < page_size:
            return assets
        start += page_size


def set_asset_attributes(asset_id, attributes, session=None, timeout=DEFAULT_TIMEOUT):
    """Update custom attribute values on one asset, e.g.
    set_asset_attributes(123, {"IRN": ["229430"]}). Each value is a list.
    See https://developer.netx.net/#setassetattributes"""
    return call("setAssetAttributes", [asset_id, attributes], session=session, timeout=timeout)


def get_asset(asset_id, session=None, timeout=DEFAULT_TIMEOUT):
    """One asset by its NetX id (id, base, file, attributes), or None if NetX
    returns nothing for it. See https://developer.netx.net/#getassets"""
    result = call(
        "getAssets",
        [[int(asset_id)], {"data": ["asset.id", "asset.base", "asset.file", "asset.attributes"]}],
        session=session,
        timeout=timeout,
    )
    assets = result.get("results", []) if isinstance(result, dict) else result
    return assets[0] if assets else None
