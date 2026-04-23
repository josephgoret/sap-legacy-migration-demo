"""
Vendor Lookup Service — migrated from CI_VENDOR_LOOKUP.

Original PeopleCode: Component Interface querying PS_VENDOR, PS_VENDOR_ADDR,
                     PS_VNDR_BANK_ACCT, PS_PO_HDR, PS_PO_LINE
Target:              FastAPI endpoint returning structured JSON.

Migration notes:
- Component Interface properties -> REST request/response models
- PeopleCode IsUserInRole -> API key / JWT middleware (not shown in service layer)
- PeopleCode SQLExec/CreateRowset/Fill -> data warehouse query or ORM
- PeopleCode Error() -> Python exceptions / HTTP error responses
- CI return code -> HTTP status codes + response body
"""

from datetime import date, timedelta
from decimal import Decimal

from .models import (
    PurchaseOrderItem,
    VendorDetail,
    VendorLookupRequest,
    VendorLookupResponse,
)


class VendorNotFoundError(Exception):
    """Replaces PeopleCode: Error("Vendor " | &vendorId | " not found")."""

    def __init__(self, vendor_id: str) -> None:
        self.vendor_id = vendor_id
        super().__init__(f"Vendor {vendor_id} not found")


class AuthorizationError(Exception):
    """Replaces PeopleCode: IsUserInRole check failure."""

    def __init__(self, user: str) -> None:
        self.user = user
        super().__init__(f"Authorization failed for user {user}")


def calculate_po_aggregates(
    po_items: list[PurchaseOrderItem],
) -> tuple[Decimal, int]:
    """Calculate total PO value and open PO count.

    Matches PeopleCode aggregation loop:
      &totalPOValue = &totalPOValue + (&recPO.PRICE_PO.Value * &recPO.QTY_PO.Value)
      If &recPO.RECV_STATUS.Value <> "F" And &recPO.CANCEL_STATUS.Value <> "X"
    """
    total_value = Decimal("0")
    open_count = 0

    for item in po_items:
        total_value += item.price * item.quantity
        if item.receive_status != "F" and item.cancel_status != "X":
            open_count += 1

    return total_value, open_count


def lookup_vendor(
    request: VendorLookupRequest,
    vendor_data: dict | None,
    po_data: list[dict],
) -> VendorLookupResponse:
    """Main lookup logic — replaces the Component Interface OnExecute body.

    Args:
        request:     Lookup parameters (vendor ID, set ID, etc.)
        vendor_data: Vendor master record from data warehouse. None if not found.
        po_data:     Purchase order line items from data warehouse.

    Returns:
        VendorLookupResponse with vendor details and PO history.

    Raises:
        VendorNotFoundError: If vendor_data is None.
    """
    # Vendor not found — maps to PeopleCode: If &rsVendor.ActiveRowCount = 0
    if vendor_data is None:
        raise VendorNotFoundError(request.vendor_id)

    vendor = VendorDetail(
        vendor_id=vendor_data["vendor_id"],
        name1=vendor_data.get("name1", ""),
        name2=vendor_data.get("name2"),
        vendor_status=vendor_data.get("vendor_status", "A"),
        vendor_class=vendor_data.get("vendor_class"),
        address1=vendor_data.get("address1"),
        address2=vendor_data.get("address2"),
        city=vendor_data.get("city"),
        state=vendor_data.get("state"),
        postal=vendor_data.get("postal"),
        country=vendor_data.get("country"),
        phone=vendor_data.get("phone"),
        fax=vendor_data.get("fax"),
        email=vendor_data.get("email"),
        bank_code=vendor_data.get("bank_code"),
        bank_account_type=vendor_data.get("bank_account_type"),
        beneficiary_name=vendor_data.get("beneficiary_name"),
    )

    # Build PO history — maps to PeopleCode SELECT from PS_PO_HDR/PS_PO_LINE
    date_from = request.date_from or (date.today() - timedelta(days=365))

    po_items: list[PurchaseOrderItem] = []
    for row in po_data:
        po_date = row.get("po_date")
        if isinstance(po_date, str):
            po_date = date.fromisoformat(po_date)

        # Apply date filter — matches PeopleCode: WHERE PH.PO_DT >= &dateFrom
        if po_date is not None and po_date < date_from:
            continue

        item = PurchaseOrderItem(
            po_id=row["po_id"],
            line_number=row["line_number"],
            po_date=po_date,
            item_id=row.get("item_id"),
            description=row.get("description"),
            quantity=Decimal(str(row.get("quantity", 0))),
            unit_of_measure=row.get("unit_of_measure", "EA"),
            price=Decimal(str(row.get("price", 0))),
            currency=row.get("currency", "USD"),
            receive_status=row.get("receive_status", "N"),
            cancel_status=row.get("cancel_status", ""),
            requisition_id=row.get("requisition_id"),
        )
        po_items.append(item)

    # Sort by date descending and limit — matches PeopleCode: ORDER BY PH.PO_DT DESC + maxPOItems
    po_items.sort(key=lambda x: x.po_date, reverse=True)
    po_items = po_items[: request.max_po_items]

    total_value, open_count = calculate_po_aggregates(po_items)
    vendor.total_po_value = total_value
    vendor.open_po_count = open_count

    return VendorLookupResponse(
        vendor=vendor,
        po_history=po_items,
        return_code=0,
        return_message=(
            f"Vendor {request.vendor_id} retrieved successfully. "
            f"{len(po_items)} PO items returned."
        ),
    )
