"""Shared pagination query params, reused by every module's list endpoints."""
from fastapi import Query
from pydantic import BaseModel


class PageParams(BaseModel):
    limit: int = 20
    offset: int = 0


def pagination_params(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)) -> PageParams:
    return PageParams(limit=limit, offset=offset)