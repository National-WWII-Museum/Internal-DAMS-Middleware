"""
test_keyframes.py
One-off check that we can pull video keyframe metadata out of NetX with the
getKeyframesByAsset JSON-RPC method. Read-only: nothing in NetX is changed.

Needs NETX_BASE_URL and NETX_API_TOKEN in .env. The token's user must be
Producer level or higher (per the NetX API docs for getKeyframesByAsset).

Run from the repo root:
    python -m scripts.test_keyframes 2701          # a known video asset ID
    python -m scripts.test_keyframes --find        # look for a recent video first
    python -m scripts.test_keyframes --find --days 365
"""
import argparse
import json
import sys
import time

from middleware import netx_client

VIDEO_EXTENSIONS = (".mp4", ".mov", ".m4v", ".avi", ".mxf", ".mpg", ".mpeg", ".wmv", ".mkv", ".webm")
PAGE_SIZE = 100


def timepoint_to_seconds(timepoint):
    """'00:06' -> 6, '01:02:03' -> 3723. Returns None if it doesn't parse.
    NetX hands timepoint back as a string, not a number."""
    try:
        seconds = 0
        for part in str(timepoint).split(":"):
            seconds = seconds * 60 + int(part)
        return seconds
    except ValueError:
        return None


def get_keyframes(asset_id, session):
    """All keyframes for one video asset, paging until NetX's reported total."""
    keyframes = []
    start = 0
    while True:
        result = netx_client.call(
            "getKeyframesByAsset",
            [asset_id, {"page": {"startIndex": start, "size": PAGE_SIZE}}],
            session=session,
        )
        page = result.get("results", [])
        keyframes.extend(page)
        start += len(page)
        if not page or start >= result.get("size", 0):
            return keyframes, result.get("size")


def find_recent_video(days, session):
    """First recently-imported asset whose filename looks like a video.
    Uses the same importDate range query as find_recent_assets_without_irn.
    File type is matched on extension client-side because the NetX file-type
    query field hasn't been verified on this instance."""
    since_ms = int((time.time() - days * 86400) * 1000)
    start = 0
    while True:
        result = netx_client.call(
            "getAssetsByQuery",
            [
                {"query": [{"operator": "and", "range": {
                    "field": "importDate", "min": str(since_ms), "max": None,
                    "includeMin": True, "includeMax": True,
                }}]},
                {
                    "page": {"startIndex": start, "size": PAGE_SIZE},
                    "data": ["asset.id", "asset.base", "asset.file"],
                },
            ],
            session=session,
        )
        page = result.get("results", [])
        for asset in page:
            name = netx_client.get_asset_filename(asset)
            if name.lower().endswith(VIDEO_EXTENSIONS):
                return asset["id"], name
        if len(page) < PAGE_SIZE:
            return None, None
        start += PAGE_SIZE


def main():
    parser = argparse.ArgumentParser(description="Fetch keyframe metadata for a NetX video asset.")
    parser.add_argument("asset_id", nargs="?", type=int, help="NetX asset ID of a video")
    parser.add_argument("--find", action="store_true",
                        help="No asset ID? Search recent imports for a video file")
    parser.add_argument("--days", type=int, default=90, help="How far back --find looks (default 90)")
    args = parser.parse_args()

    if args.asset_id is None and not args.find:
        parser.error("give an asset ID, or use --find")

    session = netx_client.get_session()

    # 1. Auth / connectivity (getSelf is a documented no-arg-ish call)
    me = netx_client.call("getSelf", [None], session=session)
    print("Auth OK. getSelf ->", json.dumps(me, default=str)[:300])

    # 2. Pick the asset
    asset_id = args.asset_id
    if asset_id is None:
        asset_id, name = find_recent_video(args.days, session)
        if asset_id is None:
            sys.exit(f"No video found among assets imported in the last {args.days} days. "
                     "Pass an asset ID instead.")
        print(f"Found video: asset {asset_id} ({name})")

    # 3. Keyframes
    keyframes, total = get_keyframes(asset_id, session)
    print(f"\nasset {asset_id}: NetX reports size={total}, fetched {len(keyframes)} keyframes")

    if not keyframes:
        print("No keyframes returned. Either this isn't a video, NetX hasn't generated "
              "them yet, or the token user is below Producer level.")
        return

    print("\nRaw first keyframe (check these fields against the docs):")
    print(json.dumps(keyframes[0], indent=2))

    print(f"\n{'constituentId':>14}  {'timepoint':>10}  {'sec':>6}  thumb  modDate")
    for kf in keyframes:
        tp = kf.get("timepoint")
        secs = timepoint_to_seconds(tp)
        mod = kf.get("modDate")
        mod_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(mod / 1000)) if mod else "-"
        print(f"{kf.get('constituentId', '-'):>14}  {str(tp):>10}  {str(secs):>6}  "
              f"{'*' if kf.get('isAssetThumbnail') else ' ':^5}  {mod_str}")

    # Sanity checks
    if len(keyframes) != total:
        print(f"\nWARNING: fetched {len(keyframes)} but NetX reported {total}")
    unparsed = [kf.get("timepoint") for kf in keyframes if timepoint_to_seconds(kf.get("timepoint")) is None]
    if unparsed:
        print(f"WARNING: timepoints that did not parse as HH:MM:SS: {unparsed[:5]}")


if __name__ == "__main__":
    main()
