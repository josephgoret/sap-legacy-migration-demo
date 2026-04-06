"""
Data models for the Order Sync service.

Migrated from: Z_IDOC_ORDER_SYNC (IDoc Processing Function Module)
IDoc type:     ORDERS05
Segments:      E1EDK01, E1EDK03, E1EDKA1, E1EDP01, E1EDP19
"""

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class OrderStatus(str, Enum):
    """Processing result for each order."""

    CREATED = "created"
    FAILED = "failed"
    VALIDATED = "validated"


class PartnerRole(str, Enum):
    """SAP partner function codes — maps to ABAP E1EDKA1-PARVW values."""

    SOLD_TO = "AG"    # Sold-to party
    SHIP_TO = "WE"    # Ship-to party
    BILL_TO = "RE"    # Bill-to party
    PAYER = "RG"      # Payer


class OrderPartner(BaseModel):
    """Partner in the order — maps to BAPIPARNR / E1EDKA1 segment."""

    role: PartnerRole = Field(description="Partner function (PARVW)")
    number: str = Field(description="Partner number (PARTN)")


class OrderItem(BaseModel):
    """Order line item — maps to E1EDP01 + E1EDP19 segments / BAPISDITM."""

    item_number: str = Field(description="Item number (POSEX)")
    material_number: Optional[str] = Field(
        default=None, description="SAP material number from E1EDP19 qualifier 002"
    )
    customer_material: Optional[str] = Field(
        default=None, description="Customer material number from E1EDP19 qualifier 003"
    )
    plant: Optional[str] = Field(default=None, description="Delivering plant")
    quantity: Decimal = Field(description="Order quantity (MENGE)")
    unit_of_measure: str = Field(default="EA", description="Unit of measure (MENEE)")
    net_price: Decimal = Field(
        default=Decimal("0"), description="Net price (VPREI)"
    )
    item_category: Optional[str] = Field(
        default=None, description="Item category (PSTYV)"
    )


class OrderHeader(BaseModel):
    """Order header — maps to E1EDK01 + E1EDK03 + E1EDKA1 segments.

    Combines data from multiple IDoc segments into a single structure,
    replacing the ABAP ty_order_header type and its incremental population
    across FORM parse_header_segment / parse_date_segment / parse_partner_segment.
    """

    document_type: str = Field(
        default="ZOR", description="Sales document type (BSART/AUART)"
    )
    sales_org: str = Field(max_length=4, description="Sales organization")
    distribution_channel: str = Field(max_length=2, description="Distribution channel")
    division: str = Field(max_length=2, description="Division")
    sold_to_party: str = Field(max_length=10, description="Sold-to customer number")
    ship_to_party: Optional[str] = Field(
        default=None, description="Ship-to customer number"
    )
    customer_po_number: Optional[str] = Field(
        default=None, description="Customer PO reference (BSTKD)"
    )
    customer_po_date: Optional[date] = Field(
        default=None, description="Customer PO date"
    )
    requested_delivery_date: Optional[date] = Field(
        default=None, description="Requested delivery date"
    )
    pricing_date: Optional[date] = Field(default=None, description="Pricing date")
    currency: str = Field(default="USD", description="Document currency (CURCY)")
    incoterms1: Optional[str] = Field(
        default=None, description="Incoterms part 1 (e.g., FOB)"
    )
    incoterms2: Optional[str] = Field(
        default=None, description="Incoterms part 2 (location)"
    )
    partners: list[OrderPartner] = Field(default_factory=list)
    items: list[OrderItem] = Field(default_factory=list)


class InboundOrderMessage(BaseModel):
    """Top-level inbound message — replaces the IDoc control + data structure.

    In the original ABAP, this was an IDoc (EDIDC control record + EDIDD data records).
    In the migrated system, this is a JSON message received from a message queue.
    """

    message_id: str = Field(
        min_length=1, max_length=70, description="Unique message ID (replaces IDoc DOCNUM)"
    )
    message_type: str = Field(
        default="ORDERS", description="Message type (replaces MESTYP)"
    )
    sender_system: Optional[str] = Field(
        default=None, description="Sending system identifier"
    )
    order: OrderHeader = Field(description="Parsed order data")


class OrderSyncResult(BaseModel):
    """Processing result for a single order — replaces IDoc status record."""

    message_id: str
    status: OrderStatus
    order_number: Optional[str] = Field(
        default=None, description="Created sales order number (VBELN)"
    )
    error_messages: list[str] = Field(default_factory=list)


class OrderSyncBatchResult(BaseModel):
    """Batch result — replaces the IDoc status table (BDIDOCSTAT)."""

    total_processed: int
    successful: int
    failed: int
    results: list[OrderSyncResult]
