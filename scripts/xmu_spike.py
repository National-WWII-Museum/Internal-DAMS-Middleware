"""
xmu_spike.py  --  THROWAWAY evaluation script, delete after deciding.

Question this answers: can the community `xmu` package's REST client
(https://xmu.readthedocs.io) replace middleware/emu_client.py?

It runs the SAME query two ways for one day of ecatalogue changes and diffs
the results:

    legacy : emu_client.search_modified_on() + emu_client.resolve_references()
    xmu    : EMuAPI.search(... range_ filter ...) + EMuAPI.retrieve() for refs

then reports:
  - IRNs present in one result set but not the other
  - per-field value differences for IRNs in both (nested-vs-flattened noise
    is expected on the _tab / _grp fields; anything else is a real gap)

Requirements (NOT satisfied on the WSL dev box out of the box):
  - Python >= 3.11               (xmu requirement)
  - pip install xmu              (pulls joblib, lxml, pyyaml, requests)
  - a populated .env             (EMU_HOST/PORT/TENANT/USERNAME/PASSWORD)
  - network route to the EMu VM  (port 8084)

Run from the repo root:
    python -m scripts.xmu_spike 2026-08-01
    python scripts/xmu_spike.py 2026-08-01
"""
import json
import sys
from datetime import datetime, timedelta

from middleware import config, emu_client

MODULE = "ecatalogue"

# emu_client.PLACEHOLDER_FIELDS carry a "data." prefix; xmu's _prep_select adds
# that itself, so strip it for the xmu call.
XMU_SELECT = [f[len("data."):] if f.startswith("data.") else f
              for f in emu_client.PLACEHOLDER_FIELDS]


# --------------------------------------------------------------------------
# legacy path -- exactly what polling_single_day.run() does today
# --------------------------------------------------------------------------
def fetch_legacy(date):
    records = emu_client.search_modified_on(MODULE, date)
    ref_headers = emu_client.get_auth_headers()
    for rec in records:
        emu_client.resolve_references(rec, headers=ref_headers)
    return {str(rec.get("irn")): rec for rec in records}


# --------------------------------------------------------------------------
# xmu path
#
# NOTE: signatures below are from xmu 0.2b1 docs/source. If the installed
# version differs, this function is the only thing to adjust.
#
# xmu's built-in autopage (`for rec in resp`) does NOT work against this
# emurestapi build: it stops paging once `count >= resp.hits`, but this shim
# never sends a `hits` field, so it quits after page 1. We drive next_page()
# by hand here, following the Next-Search header the way emu_client does.
# --------------------------------------------------------------------------
def _last_seg(v):
    if v is None:
        return None
    return str(v).rstrip("/").split("/")[-1]


def _write_xmu_config():
    """xmu can't renew a token from in-memory creds -- on a 401 its get_token()
    re-reads `config_path` from disk. So a plaintext emurestapi.toml is
    mandatory for any run long enough to outlive one token. Write a throwaway
    one and hand its path to EMuAPI(config_path=...).
    """
    from pathlib import Path
    cfg = Path(__file__).resolve().parent.parent / "data" / "junk" / "_xmu_spike_emurestapi.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        "[params]\n"
        f'url = "{config.EMU_BASE_URL}/{config.EMU_TENANT}"\n'
        f'username = "{config.EMU_USERNAME}"\n'
        f'password = "{config.EMU_PASSWORD}"\n'
        "autopage = false\n"
    )
    return cfg


def fetch_xmu(date):
    from pathlib import Path
    from xmu import EMuAPI, range_  # noqa: import here so --help works without xmu

    next_day = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    # start clean: xmu will blindly reuse a stale ./token file if one is present
    Path("token").unlink(missing_ok=True)
    cfg = _write_xmu_config()

    try:
        api = EMuAPI(config_path=str(cfg))

        resp = api.search(
            MODULE,
            select=XMU_SELECT,
            filter_={"AdmDateModified": range_(gte=date, lt=next_day, mode="date")},
            limit=1000,
        )
        out = _drain(api, resp)
    finally:
        cfg.unlink(missing_ok=True)
        Path("token").unlink(missing_ok=True)
    return out


def _drain(api, resp):
    out = {}
    page = 1
    while True:
        matches = resp.json().get("matches", [])
        for m in matches:
            data = dict(m.get("data", {}))
            key = _last_seg(m.get("id") or data.get("irn"))
            data["irn"] = key
            _resolve_refs_xmu(api, data)
            out[key] = data
        print(f"  [xmu] page {page}: {len(matches)} record(s) (running total {len(out)})")
        try:
            resp = resp.next_page()
        except (ValueError, KeyError):
            # ValueError / KeyError == no Next-Search header, i.e. last page
            break
        page += 1
    return out


def _resolve_refs_xmu(api, rec):
    """Mirror emu_client.REFERENCE_FIELD_MAP using xmu's retrieve()."""
    for field_name, mapping in emu_client.REFERENCE_FIELD_MAP.items():
        value = rec.get(field_name)
        if value is None:
            continue
        target_module = mapping["module"]
        target_fields = mapping["fields"]

        def _one(ref):
            irn = _ref_irn(ref)
            if irn is None:
                return ref
            r = api.retrieve(target_module, irn, select=target_fields)
            return dict(r.first() or {})

        rec[field_name] = [_one(v) for v in value] if isinstance(value, list) else _one(value)


def _ref_irn(ref):
    if isinstance(ref, dict):
        rid = ref.get("id") or ref.get("irn")
        if isinstance(rid, dict):
            rid = rid.get("id")
        if isinstance(rid, str) and "/" in rid:
            return rid.rstrip("/").split("/")[-1]
        return rid
    if isinstance(ref, (int, str)):
        return str(ref)
    return None


# --------------------------------------------------------------------------
# diffing
# --------------------------------------------------------------------------
def _norm(value):
    """Collapse nested-vs-flattened noise: sort lists of dicts by their JSON,
    drop empty containers, so only genuine value differences survive."""
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in sorted(value.items()) if v not in (None, [], {}, "")}
    if isinstance(value, list):
        return sorted((_norm(v) for v in value), key=lambda x: json.dumps(x, sort_keys=True, default=str))
    return value


def diff(legacy, xmu):
    l_irns, x_irns = set(legacy), set(xmu)

    print(f"\nlegacy: {len(l_irns)} records   xmu: {len(x_irns)} records")
    only_legacy = l_irns - x_irns
    only_xmu = x_irns - l_irns
    if only_legacy:
        print(f"  IRNs only in legacy ({len(only_legacy)}): {sorted(only_legacy)[:20]}")
    if only_xmu:
        print(f"  IRNs only in xmu    ({len(only_xmu)}): {sorted(only_xmu)[:20]}")

    field_mismatches = 0
    for irn in sorted(l_irns & x_irns):
        lrec, xrec = legacy[irn], xmu[irn]
        for field in sorted(set(lrec) | set(xrec)):
            lv, xv = _norm(lrec.get(field)), _norm(xrec.get(field))
            if lv != xv:
                field_mismatches += 1
                if field_mismatches <= 40:
                    print(f"\n  irn {irn}  field {field!r}")
                    print(f"    legacy: {json.dumps(lv, default=str)[:300]}")
                    print(f"    xmu   : {json.dumps(xv, default=str)[:300]}")

    print(f"\n{'-'*60}")
    print(f"shared IRNs: {len(l_irns & x_irns)}   field mismatches: {field_mismatches}")
    if not only_legacy and not only_xmu and field_mismatches == 0:
        print("MATCH -- xmu produced equivalent output. Safe to proceed.")
    else:
        print("DIFFERENCES -- inspect above before switching.")


def probe(since="2026-01-01"):
    """List every AdmDateModified value (and count) since `since`, via the
    legacy client, so you can pick a date that actually has records."""
    import collections
    recs = emu_client.search_modified_since(
        MODULE, since, fields=["data.irn", "data.AdmDateModified"]
    )
    counts = collections.Counter(r.get("AdmDateModified") for r in recs)
    print(f"{MODULE}: {len(recs)} records modified since {since}")
    for day, n in sorted(counts.items()):
        print(f"  {day}: {n}")


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--probe":
        probe(sys.argv[2])
        return
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.xmu_spike YYYY-MM-DD")
        print("       python -m scripts.xmu_spike --probe YYYY-MM-DD   (list dates with data)")
        sys.exit(1)
    date = sys.argv[1]

    print(f"[legacy] fetching {MODULE} modified on {date} ...")
    legacy = fetch_legacy(date)
    print(f"[legacy] {len(legacy)} record(s)")
    print(f"[xmu]    fetching {MODULE} modified on {date} ...")
    xmu = fetch_xmu(date)
    print(f"[xmu]    {len(xmu)} record(s)")

    # dump both for eyeballing
    from pathlib import Path
    out_dir = Path(__file__).resolve().parent.parent / "data" / "junk"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"xmu_spike_legacy_{date}.json").write_text(json.dumps(legacy, indent=2, default=str))
    (out_dir / f"xmu_spike_xmu_{date}.json").write_text(json.dumps(xmu, indent=2, default=str))
    print(f"wrote raw dumps to {out_dir}")

    diff(legacy, xmu)


if __name__ == "__main__":
    main()
