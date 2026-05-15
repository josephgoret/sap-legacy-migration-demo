"""
Tests for the Vendor Lookup service.

Validates functional equivalence between the ABAP Z_RFC_VENDOR_LOOKUP
function module and the migrated Python implementation.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from python_target.vendor_lookup.models import (
    PurchaseOrderItem,
    VendorLookupRequest,
)
from python_target.vendor_lookup.service import (
    VendorNotFoundError,
    calculate_po_aggregates,
    lookup_vendor,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_vendor_data() -> dict:
    """Vendor master record — represents joined LFA1 + LFB1 + ADR6 data."""
    return {
        "vendor_number": "0000001000",
        "name1": "Acme Supplies Inc.",
        "name2": "Eastern Division",
        "street": "123 Industrial Pkwy",
        "city": "Springfield",
        "region": "IL",
        "postal_code": "62701",
        "country": "US",
        "phone": "+1-217-555-0100",
        "fax": "+1-217-555-0101",
        "email": "orders@acme-supplies.example.com",
        "account_group": "LIEF",
        "payment_terms": "ZB30",
        "recon_account": "160000",
        "currency": "USD",
        "is_blocked": False,
        "is_deleted": False,
    }


@pytest.fixture()
def sample_po_data() -> list[dict]:
    """Purchase order items — represents EKKO + EKPO join."""
    today = date.today()
    return [
        {
            "po_number": "4500001234",
            "po_item": "00010",
            "po_date": (today - timedelta(days=30)).isoformat(),
            "material_number": "MAT-001",
            "short_text": "Widget A - Standard",
            "quantity": 100,
            "unit_of_measure": "EA",
            "net_price": 25.50,
            "currency": "USD",
            "delivery_completed": False,
            "purchase_requisition": "1000001234",
        },
        {
            "po_number": "4500001234",
            "po_item": "00020",
            "po_date": (today - timedelta(days=30)).isoformat(),
            "material_number": "MAT-002",
            "short_text": "Widget B - Premium",
            "quantity": 50,
            "unit_of_measure": "EA",
            "net_price": 42.00,
            "currency": "USD",
            "delivery_completed": True,
            "purchase_requisition": "1000001234",
        },
        {
            "po_number": "4500001100",
            "po_item": "00010",
            "po_date": (today - timedelta(days=90)).isoformat(),
            "material_number": "MAT-003",
            "short_text": "Gizmo C - Bulk",
            "quantity": 500,
            "unit_of_measure": "KG",
            "net_price": 8.75,
            "currency": "USD",
            "delivery_completed": True,
        },
    ]


# ---------------------------------------------------------------------------
# calculate_po_aggregates — mirrors ABAP LOOP aggregation
# ---------------------------------------------------------------------------

class TestCalculatePOAggregates:

    def test_total_value_calculation(self):
        """ABAP: lv_total = lv_total + ( ls_po-netpr * ls_po-menge )."""
        items = [
            PurchaseOrderItem(
                po_number="4500001234",
                po_item="00010",
                po_date=date.today(),
                quantity=Decimal("100"),
                unit_of_measure="EA",
                net_price=Decimal("25.50"),
                delivery_completed=False,
            ),
            PurchaseOrderItem(
                po_number="4500001234",
                po_item="00020",
                po_date=date.today(),
                quantity=Decimal("50"),
                unit_of_measure="EA",
                net_price=Decimal("42.00"),
                delivery_completed=True,
            ),
        ]

        total_value, open_count = calculate_po_aggregates(items)

        # 100 * 25.50 + 50 * 42.00 = 2550 + 2100 = 4650
        assert total_value == Decimal("4650.00")

    def test_open_po_count(self):
        """ABAP: IF ls_po-elikz = ' '. lv_open = lv_open + 1."""
        items = [
            PurchaseOrderItem(
                po_number="PO1",
                po_item="10",
                po_date=date.today(),
                quantity=Decimal("10"),
                unit_of_measure="EA",
                net_price=Decimal("5"),
                delivery_completed=False,  # Open
            ),
            PurchaseOrderItem(
                po_number="PO2",
                po_item="10",
                po_date=date.today(),
                quantity=Decimal("20"),
                unit_of_measure="EA",
                net_price=Decimal("10"),
                delivery_completed=True,  # Closed
            ),
        ]

        _, open_count = calculate_po_aggregates(items)
        assert open_count == 1

    def test_empty_po_list(self):
        total_value, open_count = calculate_po_aggregates([])
        assert total_value == Decimal("0")
        assert open_count == 0


# ---------------------------------------------------------------------------
# lookup_vendor — end-to-end function module logic
# ---------------------------------------------------------------------------

class TestLookupVendor:

    def test_successful_lookup(self, sample_vendor_data, sample_po_data):
        """Matches ABAP: ev_return_code = 0, successful retrieval."""
        request = VendorLookupRequest(vendor_number="0000001000")
        response = lookup_vendor(request, sample_vendor_data, sample_po_data)

        assert response.return_code == 0
        assert response.vendor.vendor_number == "0000001000"
        assert response.vendor.name1 == "Acme Supplies Inc."
        assert len(response.po_history) == 3
        assert response.vendor.total_po_value > 0
        assert "successfully" in response.return_message

    def test_vendor_not_found(self):
        """ABAP: IF sy-subrc <> 0. RAISE vendor_not_found."""
        request = VendorLookupRequest(vendor_number="9999999999")

        with pytest.raises(VendorNotFoundError) as exc_info:
            lookup_vendor(request, None, [])

        assert "9999999999" in str(exc_info.value)

    def test_po_date_filtering(self, sample_vendor_data, sample_po_data):
        """ABAP: WHERE h~bedat >= lv_date_from."""
        # Only include POs from the last 7 days (should exclude all sample POs)
        request = VendorLookupRequest(
            vendor_number="0000001000",
            date_from=date.today() - timedelta(days=7),
        )
        response = lookup_vendor(request, sample_vendor_data, sample_po_data)

        assert response.return_code == 0
        assert len(response.po_history) == 0

    def test_po_limit(self, sample_vendor_data, sample_po_data):
        """ABAP: UP TO iv_max_pos ROWS."""
        request = VendorLookupRequest(
            vendor_number="0000001000",
            max_po_items=2,
        )
        response = lookup_vendor(request, sample_vendor_data, sample_po_data)

        assert len(response.po_history) <= 2

    def test_po_sorted_descending(self, sample_vendor_data, sample_po_data):
        """ABAP: ORDER BY h~bedat DESCENDING."""
        request = VendorLookupRequest(vendor_number="0000001000")
        response = lookup_vendor(request, sample_vendor_data, sample_po_data)

        dates = [item.po_date for item in response.po_history]
        assert dates == sorted(dates, reverse=True)

    def test_blocked_vendor_still_returned(self, sample_vendor_data):
        """Vendor with central block is returned (block is informational)."""
        sample_vendor_data["is_blocked"] = True
        request = VendorLookupRequest(vendor_number="0000001000")
        response = lookup_vendor(request, sample_vendor_data, [])

        assert response.vendor.is_blocked is True
        assert response.return_code == 0
