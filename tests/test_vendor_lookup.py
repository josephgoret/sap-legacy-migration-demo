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
    VendorDetail,
    VendorLookupRequest,
    VendorLookupResponse,
)
from python_target.vendor_lookup.service import (
    AuthorizationError,
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

    def test_all_items_open(self):
        """ABAP: every item has elikz = ' ' (delivery not completed)."""
        items = [
            PurchaseOrderItem(
                po_number="PO1", po_item="10", po_date=date.today(),
                quantity=Decimal("10"), unit_of_measure="EA",
                net_price=Decimal("5"), delivery_completed=False,
            ),
            PurchaseOrderItem(
                po_number="PO2", po_item="10", po_date=date.today(),
                quantity=Decimal("20"), unit_of_measure="EA",
                net_price=Decimal("10"), delivery_completed=False,
            ),
        ]
        total_value, open_count = calculate_po_aggregates(items)
        assert open_count == 2
        assert total_value == Decimal("250")  # 10*5 + 20*10

    def test_all_items_completed(self):
        """ABAP: every item has elikz = 'X' — open count should be 0."""
        items = [
            PurchaseOrderItem(
                po_number="PO1", po_item="10", po_date=date.today(),
                quantity=Decimal("10"), unit_of_measure="EA",
                net_price=Decimal("5"), delivery_completed=True,
            ),
            PurchaseOrderItem(
                po_number="PO2", po_item="10", po_date=date.today(),
                quantity=Decimal("20"), unit_of_measure="EA",
                net_price=Decimal("10"), delivery_completed=True,
            ),
        ]
        _, open_count = calculate_po_aggregates(items)
        assert open_count == 0

    def test_single_item(self):
        """Boundary: single PO item aggregation."""
        items = [
            PurchaseOrderItem(
                po_number="PO1", po_item="10", po_date=date.today(),
                quantity=Decimal("7"), unit_of_measure="EA",
                net_price=Decimal("3.50"), delivery_completed=False,
            ),
        ]
        total_value, open_count = calculate_po_aggregates(items)
        assert total_value == Decimal("24.50")
        assert open_count == 1

    def test_zero_price_item_contributes_nothing(self):
        """ABAP: netpr * menge — zero price means zero contribution."""
        items = [
            PurchaseOrderItem(
                po_number="PO1", po_item="10", po_date=date.today(),
                quantity=Decimal("100"), unit_of_measure="EA",
                net_price=Decimal("0"), delivery_completed=False,
            ),
        ]
        total_value, _ = calculate_po_aggregates(items)
        assert total_value == Decimal("0")

    def test_zero_quantity_item_contributes_nothing(self):
        """ABAP: netpr * menge — zero quantity means zero contribution."""
        items = [
            PurchaseOrderItem(
                po_number="PO1", po_item="10", po_date=date.today(),
                quantity=Decimal("0"), unit_of_measure="EA",
                net_price=Decimal("99.99"), delivery_completed=False,
            ),
        ]
        total_value, _ = calculate_po_aggregates(items)
        assert total_value == Decimal("0")


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

    def test_deleted_vendor_still_returned(self, sample_vendor_data):
        """ABAP: loevm (deletion flag) is informational — vendor is still returned."""
        sample_vendor_data["is_deleted"] = True
        request = VendorLookupRequest(vendor_number="0000001000")
        response = lookup_vendor(request, sample_vendor_data, [])

        assert response.vendor.is_deleted is True
        assert response.return_code == 0

    def test_vendor_with_no_po_history(self, sample_vendor_data):
        """Vendor exists but has no purchase orders — aggregates should be zero."""
        request = VendorLookupRequest(vendor_number="0000001000")
        response = lookup_vendor(request, sample_vendor_data, [])

        assert response.return_code == 0
        assert response.po_history == []
        assert response.vendor.total_po_value == Decimal("0")
        assert response.vendor.open_po_count == 0
        assert "0 PO items" in response.return_message

    def test_default_date_from_is_365_days(self, sample_vendor_data):
        """ABAP: IF iv_date_from IS INITIAL. lv_date_from = sy-datum - 365."""
        today = date.today()
        old_po = {
            "po_number": "4500000001",
            "po_item": "00010",
            "po_date": (today - timedelta(days=400)).isoformat(),
            "quantity": 10,
            "unit_of_measure": "EA",
            "net_price": 5.0,
            "delivery_completed": False,
        }
        recent_po = {
            "po_number": "4500000002",
            "po_item": "00010",
            "po_date": (today - timedelta(days=100)).isoformat(),
            "quantity": 10,
            "unit_of_measure": "EA",
            "net_price": 5.0,
            "delivery_completed": False,
        }
        request = VendorLookupRequest(vendor_number="0000001000")
        response = lookup_vendor(request, sample_vendor_data, [old_po, recent_po])

        assert len(response.po_history) == 1
        assert response.po_history[0].po_number == "4500000002"

    def test_default_company_code(self):
        """ABAP: IV_BUKRS DEFAULT '1000'."""
        request = VendorLookupRequest(vendor_number="0000001000")
        assert request.company_code == "1000"

    def test_default_max_po_items(self):
        """ABAP: IV_MAX_POS DEFAULT 50."""
        request = VendorLookupRequest(vendor_number="0000001000")
        assert request.max_po_items == 50

    def test_max_po_items_boundary_of_one(self, sample_vendor_data, sample_po_data):
        """ABAP: UP TO 1 ROWS — only most recent PO returned."""
        request = VendorLookupRequest(
            vendor_number="0000001000",
            max_po_items=1,
        )
        response = lookup_vendor(request, sample_vendor_data, sample_po_data)
        assert len(response.po_history) == 1

    def test_vendor_data_with_minimal_fields(self):
        """Vendor record with only required fields — optional fields default."""
        minimal_data = {
            "vendor_number": "0000009999",
            "name1": "Minimal Vendor",
        }
        request = VendorLookupRequest(vendor_number="0000009999")
        response = lookup_vendor(request, minimal_data, [])

        assert response.vendor.vendor_number == "0000009999"
        assert response.vendor.name2 is None
        assert response.vendor.street is None
        assert response.vendor.email is None
        assert response.vendor.currency == "USD"
        assert response.vendor.is_blocked is False
        assert response.vendor.is_deleted is False

    def test_po_data_with_minimal_fields(self, sample_vendor_data):
        """PO rows with only required fields — optional fields default."""
        today = date.today()
        minimal_po = {
            "po_number": "4500009999",
            "po_item": "00010",
            "po_date": (today - timedelta(days=10)).isoformat(),
            "quantity": 5,
            "unit_of_measure": "EA",
            "net_price": 10.0,
        }
        request = VendorLookupRequest(vendor_number="0000001000")
        response = lookup_vendor(request, sample_vendor_data, [minimal_po])

        assert len(response.po_history) == 1
        item = response.po_history[0]
        assert item.material_number is None
        assert item.short_text is None
        assert item.purchase_requisition is None
        assert item.delivery_completed is False
        assert item.currency == "USD"

    def test_po_date_exactly_at_boundary(self, sample_vendor_data):
        """ABAP: WHERE h~bedat >= lv_date_from — boundary date is inclusive."""
        boundary_date = date.today() - timedelta(days=30)
        po_at_boundary = {
            "po_number": "4500000001",
            "po_item": "00010",
            "po_date": boundary_date.isoformat(),
            "quantity": 1,
            "unit_of_measure": "EA",
            "net_price": 1.0,
        }
        request = VendorLookupRequest(
            vendor_number="0000001000",
            date_from=boundary_date,
        )
        response = lookup_vendor(request, sample_vendor_data, [po_at_boundary])
        assert len(response.po_history) == 1

    def test_aggregates_computed_after_filtering(self, sample_vendor_data):
        """Aggregates reflect only the POs that pass the date/limit filters."""
        today = date.today()
        po_data = [
            {
                "po_number": "OLD", "po_item": "10",
                "po_date": (today - timedelta(days=400)).isoformat(),
                "quantity": 1000, "unit_of_measure": "EA",
                "net_price": 100.0, "delivery_completed": False,
            },
            {
                "po_number": "NEW", "po_item": "10",
                "po_date": (today - timedelta(days=10)).isoformat(),
                "quantity": 2, "unit_of_measure": "EA",
                "net_price": 5.0, "delivery_completed": False,
            },
        ]
        request = VendorLookupRequest(vendor_number="0000001000")
        response = lookup_vendor(request, sample_vendor_data, po_data)

        assert len(response.po_history) == 1
        assert response.vendor.total_po_value == Decimal("10.00")
        assert response.vendor.open_po_count == 1

    def test_return_message_contains_po_count(self, sample_vendor_data, sample_po_data):
        """ABAP: ev_return_msg includes the number of PO items returned."""
        request = VendorLookupRequest(vendor_number="0000001000")
        response = lookup_vendor(request, sample_vendor_data, sample_po_data)
        assert "3 PO items" in response.return_message

    def test_return_message_contains_vendor_number(self, sample_vendor_data):
        """ABAP: ev_return_msg = |Vendor { iv_lifnr } retrieved successfully|."""
        request = VendorLookupRequest(vendor_number="0000001000")
        response = lookup_vendor(request, sample_vendor_data, [])
        assert "0000001000" in response.return_message


# ---------------------------------------------------------------------------
# Exception classes — mirrors ABAP RAISE exceptions
# ---------------------------------------------------------------------------

class TestExceptions:

    def test_vendor_not_found_error_carries_vendor_number(self):
        """ABAP: RAISE vendor_not_found — exception carries the LIFNR."""
        err = VendorNotFoundError("0000005555")
        assert err.vendor_number == "0000005555"
        assert "0000005555" in str(err)

    def test_authorization_error_carries_company_code(self):
        """ABAP: RAISE authorization_failed — exception carries BUKRS."""
        err = AuthorizationError("2000")
        assert err.company_code == "2000"
        assert "2000" in str(err)
