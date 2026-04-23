"""
Tests for the Vendor Lookup service.

Validates functional equivalence between the PeopleCode CI_VENDOR_LOOKUP
Component Interface and the migrated Python implementation.
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
    """Vendor master record — represents PS_VENDOR + PS_VENDOR_ADDR + PS_VNDR_BANK_ACCT."""
    return {
        "vendor_id": "V0001000",
        "name1": "Global Supply Partners Inc.",
        "name2": "Americas Division",
        "vendor_status": "A",
        "vendor_class": "GOODS",
        "address1": "456 Commerce Blvd",
        "address2": "Suite 200",
        "city": "Chicago",
        "state": "IL",
        "postal": "60601",
        "country": "USA",
        "phone": "+1-312-555-0100",
        "fax": "+1-312-555-0101",
        "email": "orders@globalsupply.example.com",
        "bank_code": "CHASE",
        "bank_account_type": "CHECKING",
        "beneficiary_name": "Global Supply Partners Inc.",
    }


@pytest.fixture()
def sample_po_data() -> list[dict]:
    """Purchase order items — represents PS_PO_HDR + PS_PO_LINE join."""
    today = date.today()
    return [
        {
            "po_id": "PO-2024-001",
            "line_number": 1,
            "po_date": (today - timedelta(days=30)).isoformat(),
            "item_id": "INV-001",
            "description": "Office Supplies - Standard",
            "quantity": 200,
            "unit_of_measure": "EA",
            "price": 12.50,
            "currency": "USD",
            "receive_status": "N",
            "cancel_status": "",
            "requisition_id": "REQ-2024-100",
        },
        {
            "po_id": "PO-2024-001",
            "line_number": 2,
            "po_date": (today - timedelta(days=30)).isoformat(),
            "item_id": "INV-002",
            "description": "Office Supplies - Premium",
            "quantity": 50,
            "unit_of_measure": "EA",
            "price": 35.00,
            "currency": "USD",
            "receive_status": "F",
            "cancel_status": "",
            "requisition_id": "REQ-2024-100",
        },
        {
            "po_id": "PO-2023-050",
            "line_number": 1,
            "po_date": (today - timedelta(days=90)).isoformat(),
            "item_id": "INV-003",
            "description": "Bulk Packaging Material",
            "quantity": 1000,
            "unit_of_measure": "KG",
            "price": 4.25,
            "currency": "USD",
            "receive_status": "F",
            "cancel_status": "",
        },
    ]


# ---------------------------------------------------------------------------
# calculate_po_aggregates — mirrors PeopleCode PO aggregation loop
# ---------------------------------------------------------------------------


class TestCalculatePOAggregates:

    def test_total_value_calculation(self):
        """PeopleCode: &totalPOValue = &totalPOValue + (&recPO.PRICE_PO.Value * &recPO.QTY_PO.Value)."""
        items = [
            PurchaseOrderItem(
                po_id="PO-001",
                line_number=1,
                po_date=date.today(),
                quantity=Decimal("200"),
                unit_of_measure="EA",
                price=Decimal("12.50"),
                receive_status="N",
            ),
            PurchaseOrderItem(
                po_id="PO-001",
                line_number=2,
                po_date=date.today(),
                quantity=Decimal("50"),
                unit_of_measure="EA",
                price=Decimal("35.00"),
                receive_status="F",
            ),
        ]

        total_value, open_count = calculate_po_aggregates(items)

        # 200 * 12.50 + 50 * 35.00 = 2500 + 1750 = 4250
        assert total_value == Decimal("4250.00")

    def test_open_po_count(self):
        """PeopleCode: If RECV_STATUS <> "F" And CANCEL_STATUS <> "X"."""
        items = [
            PurchaseOrderItem(
                po_id="PO-001",
                line_number=1,
                po_date=date.today(),
                quantity=Decimal("10"),
                unit_of_measure="EA",
                price=Decimal("5"),
                receive_status="N",  # Open
                cancel_status="",
            ),
            PurchaseOrderItem(
                po_id="PO-002",
                line_number=1,
                po_date=date.today(),
                quantity=Decimal("20"),
                unit_of_measure="EA",
                price=Decimal("10"),
                receive_status="F",  # Fully received
                cancel_status="",
            ),
            PurchaseOrderItem(
                po_id="PO-003",
                line_number=1,
                po_date=date.today(),
                quantity=Decimal("15"),
                unit_of_measure="EA",
                price=Decimal("8"),
                receive_status="N",
                cancel_status="X",  # Cancelled
            ),
        ]

        _, open_count = calculate_po_aggregates(items)
        assert open_count == 1

    def test_empty_po_list(self):
        total_value, open_count = calculate_po_aggregates([])
        assert total_value == Decimal("0")
        assert open_count == 0


# ---------------------------------------------------------------------------
# lookup_vendor — end-to-end Component Interface logic
# ---------------------------------------------------------------------------


class TestLookupVendor:

    def test_successful_lookup(self, sample_vendor_data, sample_po_data):
        """Matches PeopleCode: &CI.RETURN_CODE = 0, successful retrieval."""
        request = VendorLookupRequest(vendor_id="V0001000")
        response = lookup_vendor(request, sample_vendor_data, sample_po_data)

        assert response.return_code == 0
        assert response.vendor.vendor_id == "V0001000"
        assert response.vendor.name1 == "Global Supply Partners Inc."
        assert len(response.po_history) == 3
        assert response.vendor.total_po_value > 0
        assert "successfully" in response.return_message

    def test_vendor_not_found(self):
        """PeopleCode: If &rsVendor.ActiveRowCount = 0 -> Error()."""
        request = VendorLookupRequest(vendor_id="NONEXISTENT")

        with pytest.raises(VendorNotFoundError) as exc_info:
            lookup_vendor(request, None, [])

        assert "NONEXISTENT" in str(exc_info.value)

    def test_po_date_filtering(self, sample_vendor_data, sample_po_data):
        """PeopleCode: WHERE PH.PO_DT >= &dateFrom."""
        request = VendorLookupRequest(
            vendor_id="V0001000",
            date_from=date.today() - timedelta(days=7),
        )
        response = lookup_vendor(request, sample_vendor_data, sample_po_data)

        assert response.return_code == 0
        assert len(response.po_history) == 0

    def test_po_limit(self, sample_vendor_data, sample_po_data):
        """PeopleCode: If &poCount >= &maxPOItems Then Break."""
        request = VendorLookupRequest(
            vendor_id="V0001000",
            max_po_items=2,
        )
        response = lookup_vendor(request, sample_vendor_data, sample_po_data)

        assert len(response.po_history) <= 2

    def test_po_sorted_descending(self, sample_vendor_data, sample_po_data):
        """PeopleCode: ORDER BY PH.PO_DT DESC."""
        request = VendorLookupRequest(vendor_id="V0001000")
        response = lookup_vendor(request, sample_vendor_data, sample_po_data)

        dates = [item.po_date for item in response.po_history]
        assert dates == sorted(dates, reverse=True)

    def test_vendor_with_bank_info(self, sample_vendor_data):
        """Bank account fields populated from PS_VNDR_BANK_ACCT."""
        request = VendorLookupRequest(vendor_id="V0001000")
        response = lookup_vendor(request, sample_vendor_data, [])

        assert response.vendor.bank_code == "CHASE"
        assert response.vendor.beneficiary_name == "Global Supply Partners Inc."
        assert response.return_code == 0
