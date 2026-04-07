"""
Data models for the Inventory Report service.

Migrated from: Z_INVENTORY_REPORT (ABAP ALV Report)
Source tables:  MARA, MAKT, MARC, MARD, MSEG/MKPF
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class StockStatus(str, Enum):
    """Traffic-light stock status indicator.

    Maps to ABAP stock_status field:
      '1' (red)    -> CRITICAL
      '2' (yellow) -> WARNING
      '3' (green)  -> HEALTHY
    """

    CRITICAL = "critical"
    WARNING = "warning"
    HEALTHY = "healthy"


class InventoryFilters(BaseModel):
    """Selection screen parameters — maps to ABAP selection screen block b01/b02."""

    plants: list[str] = Field(default_factory=list, description="Plant codes (s_werks)")
    storage_locations: list[str] = Field(
        default_factory=list, description="Storage location codes (s_lgort)"
    )
    material_groups: list[str] = Field(
        default_factory=list, description="Material group codes (s_matkl)"
    )
    material_types: list[str] = Field(
        default_factory=list, description="Material type codes (s_mtart)"
    )
    stale_days: int = Field(
        default=90,
        ge=1,
        description="Days since last receipt to flag as stale (p_stale)",
    )
    show_critical: bool = Field(default=True, description="Include red status (p_red)")
    show_warning: bool = Field(
        default=True, description="Include yellow status (p_yellow)"
    )
    show_healthy: bool = Field(
        default=False, description="Include green status (p_green)"
    )


class InventoryItem(BaseModel):
    """Single inventory line item — maps to ABAP ty_inventory structure."""

    material_number: str = Field(max_length=40, description="Material number (MATNR)")
    description: str = Field(max_length=80, description="Material description (MAKTX)")
    material_type: str = Field(max_length=10, description="Material type (MTART)")
    material_group: str = Field(max_length=10, description="Material group (MATKL)")
    plant: str = Field(max_length=10, description="Plant code (WERKS)")
    storage_location: str = Field(max_length=10, description="Storage location (LGORT)")
    available_stock: Decimal = Field(description="Unrestricted stock (LABST)")
    inspection_stock: Decimal = Field(
        default=Decimal("0"), description="Quality inspection stock (INSME)"
    )
    blocked_stock: Decimal = Field(
        default=Decimal("0"), description="Blocked stock (SPEME)"
    )
    total_stock: Decimal = Field(description="Sum of all stock categories")
    reorder_point: Decimal = Field(description="Reorder point (MINBE)")
    max_stock_level: Decimal = Field(
        default=Decimal("0"), description="Maximum stock level (MABST)"
    )
    stock_status: StockStatus = Field(description="Traffic-light indicator")
    stock_percentage: Decimal = Field(
        description="Stock level as % of reorder point"
    )
    last_receipt_date: Optional[date] = Field(
        default=None, description="Last goods receipt date"
    )
    currency: str = Field(default="USD", max_length=5, description="Currency code")
    stock_value: Decimal = Field(description="Estimated stock value")


class InventoryReportResponse(BaseModel):
    """Full report response — replaces ALV grid output."""

    generated_at: datetime
    filters_applied: InventoryFilters
    total_items: int
    summary: "InventoryReportSummary"
    items: list[InventoryItem]


class InventoryReportSummary(BaseModel):
    """Aggregated summary — additional value vs. the flat ALV grid."""

    critical_count: int = 0
    warning_count: int = 0
    healthy_count: int = 0
    total_stock_value: Decimal = Decimal("0")
    materials_below_reorder: int = 0
    stale_materials: int = 0
