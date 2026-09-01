"""
Extended tests for the Vendor Lookup service.

Covers gaps in the original test suite:
- AuthorizationError exception (never tested)
- VendorNotFoundError attributes
- lookup_vendor with minimal data, date objects, default date_from
- calculate_po_aggregates edge cases
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
# Exception classes
# ---------------------------------------------------------------------------

class TestVendorNotFoundError:

    def test_message_contains_vendor_number(self):
        err = VendorNotFoundError("0000001234")
        assert "0000001234" in str(err)

    def test_vendor_number_attribute(self):
        err = VendorNotFoundError("V-999")
        assert err.vendor_number == "V-999"

    def test_is_exception(self):
        assert issubclass(VendorNotFoundError, Exception)


class TestAuthorizationError:

    def test_message_contains_company_code(self):
        err = AuthorizationError("2000")
        assert "2000" in str(err)

    def test_company_code_attribute(self):
        err = AuthorizationError("3000")
        assert err.company_code == "3000"

    def test_is_exception(self):
        assert issubclass(AuthorizationError, Exception)

    def test_raise_and_catch(self):
        with pytest.raises(AuthorizationError) as exc_info:
            raise AuthorizationError("4000")
        assert exc_info.value.company_code == "4000"


# ---------------------------------------------------------------------------
# calculate_po_aggregates — additional edge cases
# ---------------------------------------------------------------------------

class TestCalculatePOAggregatesExtended:

    def test_all_items_open(self):
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
        # 10*5 + 20*10 = 250
        assert total_value == Decimal("250")

    def test_all_items_closed(self):
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
        total_value, open_count = calculate_po_aggregates(items)
        assert open_count == 0
        assert total_value == Decimal("250")

    def test_single_item(self):
        items = [
            PurchaseOrderItem(
                po_number="PO1", po_item="10", po_date=date.today(),
                quantity=Decimal("7"), unit_of_measure="KG",
                net_price=Decimal("12.50"), delivery_completed=False,
            ),
        ]
        total_value, open_count = calculate_po_aggregates(items)
        assert total_value == Decimal("87.50")
        assert open_count == 1

    def test_zero_price_items(self):
        items = [
            PurchaseOrderItem(
                po_number="PO1", po_item="10", po_date=date.today(),
                quantity=Decimal("100"), unit_of_measure="EA",
                net_price=Decimal("0"), delivery_completed=False,
            ),
        ]
        total_value, open_count = calculate_po_aggregates(items)
        assert total_value == Decimal("0")
        assert open_count == 1


# ---------------------------------------------------------------------------
# lookup_vendor — additional coverage
# ---------------------------------------------------------------------------

class TestLookupVendorExtended:

    @pytest.fixture()
    def minimal_vendor_data(self) -> dict:
        """Vendor with only the required field."""
        return {"vendor_number": "0000009999"}

    def test_minimal_vendor_data(self, minimal_vendor_data):
        """Vendor with only required fields; optional fields get defaults."""
        request = VendorLookupRequest(vendor_number="0000009999")
        response = lookup_vendor(request, minimal_vendor_data, [])

        assert response.return_code == 0
        assert response.vendor.vendor_number == "0000009999"
        assert response.vendor.name1 == ""
        assert response.vendor.name2 is None
        assert response.vendor.currency == "USD"
        assert response.vendor.is_blocked is False
        assert response.vendor.is_deleted is False

    def test_po_date_as_date_object(self):
        """PO data with po_date as a date object (not string)."""
        vendor_data = {"vendor_number": "V-001", "name1": "Test"}
        po_data = [
            {
                "po_number": "PO1",
                "po_item": "10",
                "po_date": date.today() - timedelta(days=5),
                "quantity": 10,
                "unit_of_measure": "EA",
                "net_price": 100,
            },
        ]
        request = VendorLookupRequest(vendor_number="V-001")
        response = lookup_vendor(request, vendor_data, po_data)
        assert len(response.po_history) == 1

    def test_default_date_from_is_one_year(self):
        """When date_from is None, POs older than 365 days are excluded."""
        vendor_data = {"vendor_number": "V-001", "name1": "Test"}
        old_date = (date.today() - timedelta(days=400)).isoformat()
        recent_date = (date.today() - timedelta(days=30)).isoformat()
        po_data = [
            {
                "po_number": "OLD-PO",
                "po_item": "10",
                "po_date": old_date,
                "quantity": 10,
                "unit_of_measure": "EA",
                "net_price": 50,
            },
            {
                "po_number": "NEW-PO",
                "po_item": "10",
                "po_date": recent_date,
                "quantity": 20,
                "unit_of_measure": "EA",
                "net_price": 75,
            },
        ]
        request = VendorLookupRequest(vendor_number="V-001")
        response = lookup_vendor(request, vendor_data, po_data)

        assert len(response.po_history) == 1
        assert response.po_history[0].po_number == "NEW-PO"

    def test_aggregates_on_vendor_after_lookup(self):
        """Verify total_po_value and open_po_count on the vendor detail."""
        vendor_data = {"vendor_number": "V-001", "name1": "Test"}
        today = date.today()
        po_data = [
            {
                "po_number": "PO1",
                "po_item": "10",
                "po_date": (today - timedelta(days=10)).isoformat(),
                "quantity": 10,
                "unit_of_measure": "EA",
                "net_price": 25,
                "delivery_completed": False,
            },
            {
                "po_number": "PO2",
                "po_item": "10",
                "po_date": (today - timedelta(days=20)).isoformat(),
                "quantity": 5,
                "unit_of_measure": "EA",
                "net_price": 40,
                "delivery_completed": True,
            },
        ]
        request = VendorLookupRequest(vendor_number="V-001")
        response = lookup_vendor(request, vendor_data, po_data)

        # 10*25 + 5*40 = 450
        assert response.vendor.total_po_value == Decimal("450")
        assert response.vendor.open_po_count == 1

    def test_return_message_format(self):
        vendor_data = {"vendor_number": "V-001", "name1": "Test"}
        request = VendorLookupRequest(vendor_number="V-001")
        response = lookup_vendor(request, vendor_data, [])

        assert "V-001" in response.return_message
        assert "0 PO items" in response.return_message

    def test_po_limit_applies_after_sort(self):
        """max_po_items limits after descending date sort → most recent kept."""
        vendor_data = {"vendor_number": "V-001", "name1": "Test"}
        today = date.today()
        po_data = [
            {
                "po_number": f"PO-{i}",
                "po_item": "10",
                "po_date": (today - timedelta(days=i * 30)).isoformat(),
                "quantity": 1,
                "unit_of_measure": "EA",
                "net_price": 10,
            }
            for i in range(5)
        ]
        request = VendorLookupRequest(vendor_number="V-001", max_po_items=2)
        response = lookup_vendor(request, vendor_data, po_data)

        assert len(response.po_history) == 2
        # Most recent dates should be kept
        assert response.po_history[0].po_date >= response.po_history[1].po_date

    def test_vendor_not_found_error_raised(self):
        request = VendorLookupRequest(vendor_number="NONEXIST")
        with pytest.raises(VendorNotFoundError) as exc_info:
            lookup_vendor(request, None, [])
        assert exc_info.value.vendor_number == "NONEXIST"

    def test_deleted_vendor_still_returned(self):
        vendor_data = {
            "vendor_number": "V-DEL",
            "name1": "Deleted Vendor",
            "is_deleted": True,
        }
        request = VendorLookupRequest(vendor_number="V-DEL")
        response = lookup_vendor(request, vendor_data, [])
        assert response.vendor.is_deleted is True
        assert response.return_code == 0


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestVendorModels:

    def test_vendor_lookup_request_defaults(self):
        req = VendorLookupRequest(vendor_number="V-001")
        assert req.company_code == "1000"
        assert req.max_po_items == 50
        assert req.date_from is None

    def test_vendor_detail_defaults(self):
        vendor = VendorDetail(vendor_number="V-001", name1="Test")
        assert vendor.currency == "USD"
        assert vendor.is_blocked is False
        assert vendor.is_deleted is False
        assert vendor.total_po_value == Decimal("0")
        assert vendor.open_po_count == 0

    def test_purchase_order_item_defaults(self):
        item = PurchaseOrderItem(
            po_number="PO1",
            po_item="10",
            po_date=date.today(),
            quantity=Decimal("1"),
            unit_of_measure="EA",
            net_price=Decimal("10"),
        )
        assert item.currency == "USD"
        assert item.delivery_completed is False
        assert item.material_number is None
        assert item.short_text is None
        assert item.purchase_requisition is None
