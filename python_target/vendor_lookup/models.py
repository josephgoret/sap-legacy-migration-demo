"""
Data models for the Vendor Lookup service.

Migrated from: Z_RFC_VENDOR_LOOKUP (RFC Function Module)
Source tables:  LFA1, LFB1, ADR6, EKKO, EKPO
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class VendorDetail(BaseModel):
    """Vendor master data — maps to ABAP ty_vendor_detail structure.

    Combines data from LFA1 (general), LFB1 (company code), ADR6 (email).
    """

    vendor_number: str = Field(
        min_length=1, max_length=10, description="Vendor account number (LIFNR)"
    )
    name1: str = Field(max_length=35, description="Name line 1 (NAME1)")
    name2: Optional[str] = Field(default=None, description="Name line 2 (NAME2)")
    street: Optional[str] = Field(default=None, description="Street address (STRAS)")
    city: Optional[str] = Field(default=None, description="City (ORT01)")
    region: Optional[str] = Field(default=None, description="Region/state (REGIO)")
    postal_code: Optional[str] = Field(default=None, description="Postal code (PSTLZ)")
    country: Optional[str] = Field(default=None, description="Country key (LAND1)")
    phone: Optional[str] = Field(default=None, description="Telephone (TELF1)")
    fax: Optional[str] = Field(default=None, description="Fax number (TELFX)")
    email: Optional[str] = Field(
        default=None, description="Email address (ADR6-SMTP_ADDR)"
    )
    account_group: Optional[str] = Field(
        default=None, description="Vendor account group (KTOKK)"
    )
    payment_terms: Optional[str] = Field(
        default=None, description="Payment terms key (ZTERM)"
    )
    recon_account: Optional[str] = Field(
        default=None, description="Reconciliation account (AKONT)"
    )
    currency: str = Field(default="USD", description="Currency (WAERS)")
    is_blocked: bool = Field(default=False, description="Central block flag (SPERR)")
    is_deleted: bool = Field(
        default=False, description="Deletion flag (LOEVM)"
    )
    total_po_value: Decimal = Field(
        default=Decimal("0"), description="Sum of PO line values"
    )
    open_po_count: int = Field(
        default=0, description="Count of open (not delivered) PO items"
    )


class PurchaseOrderItem(BaseModel):
    """Purchase order line item — maps to ABAP ty_po_history structure."""

    po_number: str = Field(description="Purchase order number (EBELN)")
    po_item: str = Field(description="PO item number (EBELP)")
    po_date: date = Field(description="PO document date (BEDAT)")
    material_number: Optional[str] = Field(
        default=None, description="Material number (MATNR)"
    )
    short_text: Optional[str] = Field(
        default=None, description="Item short text (TXZ01)"
    )
    quantity: Decimal = Field(description="Order quantity (MENGE)")
    unit_of_measure: str = Field(description="Unit of measure (MEINS)")
    net_price: Decimal = Field(description="Net price per unit (NETPR)")
    currency: str = Field(default="USD", description="PO currency (WAERS)")
    delivery_completed: bool = Field(
        default=False, description="Delivery completed flag (ELIKZ)"
    )
    purchase_requisition: Optional[str] = Field(
        default=None, description="Purchase requisition number (BANFN)"
    )


class VendorLookupRequest(BaseModel):
    """Input parameters — maps to ABAP function module IMPORTING parameters."""

    vendor_number: str = Field(
        min_length=1, max_length=10, description="Vendor number (IV_LIFNR)"
    )
    company_code: str = Field(
        default="1000", min_length=1, max_length=4,
        description="Company code (IV_BUKRS)",
    )
    max_po_items: int = Field(
        default=50, ge=1, le=500, description="Max PO items to return (IV_MAX_POS)"
    )
    date_from: Optional[date] = Field(
        default=None,
        description="PO date range start; defaults to 12 months ago (IV_DATE_FROM)",
    )


class VendorLookupResponse(BaseModel):
    """Output — maps to ABAP function module EXPORTING parameters."""

    vendor: VendorDetail
    po_history: list[PurchaseOrderItem]
    return_code: int = Field(description="0=OK, 1=not found, 2=auth error")
    return_message: str
