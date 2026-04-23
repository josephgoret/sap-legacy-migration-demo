"""
Data models for the Vendor Lookup service.

Migrated from: CI_VENDOR_LOOKUP (Component Interface PeopleCode)
Source tables:  PS_VENDOR, PS_VENDOR_ADDR, PS_VNDR_BANK_ACCT, PS_PO_HDR, PS_PO_LINE
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class VendorDetail(BaseModel):
    """Vendor master data — maps to PeopleCode CI output fields.

    Combines data from PS_VENDOR (general), PS_VENDOR_ADDR (address),
    PS_VNDR_BANK_ACCT (banking).
    """

    vendor_id: str = Field(description="Vendor ID (PS_VENDOR.VENDOR_ID)")
    name1: str = Field(description="Name line 1 (PS_VENDOR.NAME1)")
    name2: str | None = Field(default=None, description="Name line 2 (PS_VENDOR.NAME2)")
    vendor_status: str = Field(
        default="A", description="Vendor status (PS_VENDOR.VENDOR_STATUS)"
    )
    vendor_class: str | None = Field(
        default=None, description="Vendor classification (PS_VENDOR.VNDR_CLASS)"
    )
    address1: str | None = Field(
        default=None, description="Street address (PS_VENDOR_ADDR.ADDRESS1)"
    )
    address2: str | None = Field(
        default=None, description="Address line 2 (PS_VENDOR_ADDR.ADDRESS2)"
    )
    city: str | None = Field(default=None, description="City (PS_VENDOR_ADDR.CITY)")
    state: str | None = Field(default=None, description="State (PS_VENDOR_ADDR.STATE)")
    postal: str | None = Field(
        default=None, description="Postal code (PS_VENDOR_ADDR.POSTAL)"
    )
    country: str | None = Field(
        default=None, description="Country (PS_VENDOR_ADDR.COUNTRY)"
    )
    phone: str | None = Field(
        default=None, description="Phone number (PS_VENDOR_ADDR.PHONE)"
    )
    fax: str | None = Field(default=None, description="Fax (PS_VENDOR_ADDR.FAX)")
    email: str | None = Field(
        default=None, description="Email (PS_VENDOR_ADDR.EMAILID)"
    )
    bank_code: str | None = Field(
        default=None, description="Bank code (PS_VNDR_BANK_ACCT.BANK_CD)"
    )
    bank_account_type: str | None = Field(
        default=None, description="Account type (PS_VNDR_BANK_ACCT.BANK_ACCT_TYPE)"
    )
    beneficiary_name: str | None = Field(
        default=None, description="Beneficiary (PS_VNDR_BANK_ACCT.BENEFICIARY_NAME)"
    )
    total_po_value: Decimal = Field(
        default=Decimal("0"), description="Sum of PO line values"
    )
    open_po_count: int = Field(
        default=0, description="Count of open (not fully received) PO items"
    )


class PurchaseOrderItem(BaseModel):
    """Purchase order line item — maps to PS_PO_HDR + PS_PO_LINE join."""

    po_id: str = Field(description="Purchase order ID (PS_PO_HDR.PO_ID)")
    line_number: int = Field(description="PO line number (PS_PO_LINE.LINE_NBR)")
    po_date: date = Field(description="PO date (PS_PO_HDR.PO_DT)")
    item_id: str | None = Field(
        default=None, description="Inventory item (PS_PO_LINE.INV_ITEM_ID)"
    )
    description: str | None = Field(
        default=None, description="Line description (PS_PO_LINE.DESCR254)"
    )
    quantity: Decimal = Field(description="Order quantity (PS_PO_LINE.QTY_PO)")
    unit_of_measure: str = Field(
        description="Unit of measure (PS_PO_LINE.UNIT_OF_MEASURE)"
    )
    price: Decimal = Field(description="PO price (PS_PO_LINE.PRICE_PO)")
    currency: str = Field(default="USD", description="Currency (PS_PO_HDR.CURRENCY_CD)")
    receive_status: str = Field(
        default="N",
        description="Receive status N=Not/P=Partial/F=Full (PS_PO_LINE.RECV_STATUS)",
    )
    cancel_status: str = Field(
        default="",
        description="Cancel status X=Cancelled (PS_PO_LINE.CANCEL_STATUS)",
    )
    requisition_id: str | None = Field(
        default=None, description="Source requisition (PS_PO_LINE.REQ_ID)"
    )


class VendorLookupRequest(BaseModel):
    """Input parameters — maps to Component Interface input properties."""

    vendor_id: str = Field(description="Vendor ID (CI.VENDOR_ID)")
    set_id: str = Field(default="SHARE", description="SetID (CI.SETID)")
    business_unit: str = Field(
        default="US001", description="Business unit (CI.BUSINESS_UNIT)"
    )
    max_po_items: int = Field(
        default=50, ge=1, le=500, description="Max PO items to return (CI.MAX_PO_ITEMS)"
    )
    date_from: date | None = Field(
        default=None,
        description="PO date range start; defaults to 12 months ago (CI.DATE_FROM)",
    )


class VendorLookupResponse(BaseModel):
    """Output — maps to Component Interface output properties."""

    vendor: VendorDetail
    po_history: list[PurchaseOrderItem]
    return_code: int = Field(description="0=OK, 1=not found, 2=auth error")
    return_message: str
