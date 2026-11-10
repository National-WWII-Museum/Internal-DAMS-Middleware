"""
clips.py
JSON endpoints for NetX video clip timestamps, for other systems to pull.

  GET /api/assets/{asset_id}/clips
  GET /api/clips?asset_ids=206839,206840

The data comes straight from the NetX database (the NetX JSON-RPC API has no
clip method)
"""
from fastapi import APIRouter, Depends, HTTPException, Query

from common import netx_db
from common.netx_db import get_netx_db

router = APIRouter()


@router.get("/api/assets/{asset_id}/clips")
def asset_clips(asset_id: int, conn=Depends(get_netx_db)):
    found = netx_db.get_clips(conn, [asset_id])
    if asset_id not in found:
        raise HTTPException(status_code=404, detail=f"asset {asset_id} not found in NetX")
    return {"asset_id": asset_id, **found[asset_id]}


@router.get("/api/clips")
def clips_for_assets(
    asset_ids: str = Query(..., description="Comma-separated NetX asset IDs"),
    conn=Depends(get_netx_db),
):
    try:
        ids = [int(part) for part in asset_ids.split(",") if part.strip()]
    except ValueError:
        raise HTTPException(status_code=422, detail="asset_ids must be comma-separated integers")
    if not ids:
        raise HTTPException(status_code=422, detail="asset_ids is empty")
    if len(set(ids)) > netx_db.MAX_ASSETS:
        raise HTTPException(
            status_code=422, detail=f"at most {netx_db.MAX_ASSETS} asset ids per request"
        )

    found = netx_db.get_clips(conn, ids)
    return {
        "assets": [{"asset_id": i, **found[i]} for i in dict.fromkeys(ids) if i in found],
        "not_found": [i for i in dict.fromkeys(ids) if i not in found],
    }
