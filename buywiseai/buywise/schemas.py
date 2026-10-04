"""Pydantic models shared by all agents."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class RawResult(BaseModel):
    """One raw hit from a search provider, before extraction."""

    title: str
    url: str
    snippet: str = ""
    price_text: Optional[str] = None      # price as a string, if the API supplied one
    price: Optional[float] = None         # numeric price, if the API supplied one
    currency: Optional[str] = None
    source: Optional[str] = None          # merchant name (Google Shopping style)
    rating: Optional[float] = None
    provider: str = ""
    from_shopping: bool = False


class Listing(BaseModel):
    """A normalised product listing: the strict extraction schema."""

    title: str
    price: Optional[float] = None         # in original currency
    currency: str = "PKR"
    price_pkr: Optional[float] = None
    source: str                           # platform display name
    domain: str
    url: str
    rating: Optional[float] = None
    availability: Optional[str] = None
    snippet: str = ""
    trust_score: int = 3
    provider: str = ""
    price_origin: str = "api"             # api | text | llm | page-meta
    relevance: float = 0.0                # reranker / fused score
    score: float = 0.0                    # final ranking score
    flags: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class QueryPlan(BaseModel):
    """Output of the Query Understanding Agent."""

    original: str
    product: str
    brand: Optional[str] = None
    categories: list[str] = Field(default_factory=lambda: ["general"])
    max_budget_pkr: Optional[float] = None
    variants: list[str] = Field(default_factory=list)
    used_ok: bool = False
