"""
netx_client.py
Reusable functions for talking to the NetX JSON-RPC API:
authentication, making a call, and looking assets up by EMu IRN.
"""
import logging

import requests

from . import config

logger = logging.getLogger(__name__)

# NetX attribute that holds the EMu IRN - the same one syncedMetadata.xml
# links on (<link field="irn" attribute="IRN"/>).
IRN_ATTRIBUTE = "IRN"

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
