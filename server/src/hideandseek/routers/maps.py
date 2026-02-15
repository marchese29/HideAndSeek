"""Map browsing endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from hideandseek.db import get_session
from hideandseek.queries.maps import get_map as query_get_map
from hideandseek.queries.maps import list_maps as query_list_maps
from hideandseek.schemas.common import pagination_params
from hideandseek.schemas.response import MapDetail, MapSummary

router = APIRouter(prefix='/maps', tags=['maps'], dependencies=[Depends(get_session)])


@router.get('', response_model=list[MapSummary])
def list_maps(
    pagination: tuple[int, int] = Depends(pagination_params),
) -> list[MapSummary]:
    """List available maps with name, size, and region."""
    offset, limit = pagination
    rows = query_list_maps(offset=offset, limit=limit)
    return [MapSummary.from_model(gm, region) for gm, region in rows]


@router.get('/{map_id}', response_model=MapDetail)
def get_map(map_id: uuid.UUID) -> MapDetail:
    """Full map detail including geometry. Omits stops/routes."""
    gm = query_get_map(map_id)
    if not gm:
        raise HTTPException(status_code=404, detail='Map not found.')
    return MapDetail.from_model(gm)
