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
# --------------------------------------------------------------------------
def fetch_xmu(date):
    from xmu import EMuAPI, range_  # noqa: import here so --help works without xmu

    next_day = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    api = EMuAPI(
        # xmu wants the tenant baked into the URL; config.EMU_BASE_URL stops at host:port
        url=f"{config.EMU_BASE_URL}/{config.EMU_TENANT}",
        username=config.EMU_USERNAME,
        password=config.EMU_PASSWORD,
        autopage=True,          # follow Next-Search for us
    )
    # If an emurestapi.toml ever lands in the repo root it'd override the kwargs
    # above -- there isn't one now, and xmu falls back to kwargs when it's absent.

    resp = api.search(
        MODULE,
        select=XMU_SELECT,
        filter_={"AdmDateModified": range_(gte=date, lt=next_day, mode="date")},
        limit=500,
    )

    out = {}
    try:
        for rec in resp:                   # autopage=True -> iterates all pages
            rec = dict(rec)
            irn = str(rec.get("irn"))
            _resolve_refs_xmu(api, rec)
            out[irn] = rec
    except ValueError as e:
        # xmu raises instead of yielding nothing when matches == []
        if "No records found" not in str(e):
            raise
        print("  [xmu] server returned zero matches for this date")
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
