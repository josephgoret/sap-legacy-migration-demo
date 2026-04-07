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


# ---------------------------------------------------------------------------
# Request defaults — mirrors ABAP IMPORTING parameter defaults
# ---------------------------------------------------------------------------


class TestRequestDefaults:
    """Verify VendorLookupRequest defaults match ABAP IMPORTING defaults."""

    def test_company_code_default(self):
        """ABAP: VALUE(IV_BUKRS) TYPE BUKRS DEFAULT '1000'."""
        request = VendorLookupRequest(vendor_number="0000001000")
        assert request.company_code == "1000"

    def test_max_po_items_default(self):
        """ABAP: VALUE(IV_MAX_POS) TYPE I DEFAULT 50."""
        request = VendorLookupRequest(vendor_number="0000001000")
        assert request.max_po_items == 50

    def test_date_from_default_is_none(self):
        """ABAP: VALUE(IV_DATE_FROM) TYPE SY-DATUM OPTIONAL → None triggers 365-day default."""
        request = VendorLookupRequest(vendor_number="0000001000")
        assert request.date_from is None


# ---------------------------------------------------------------------------
# Exception classes — mirrors ABAP EXCEPTIONS
# ---------------------------------------------------------------------------


class TestExceptions:
    """Verify exception semantics match ABAP RAISE exceptions."""

    def test_vendor_not_found_error_message(self):
        """ABAP: ev_return_msg = |Vendor { iv_lifnr } not found|."""
        err = VendorNotFoundError("0000005555")
        assert err.vendor_number == "0000005555"
        assert str(err) == "Vendor 0000005555 not found"

    def test_authorization_error_message(self):
        """ABAP: ev_return_msg = |Authorization failed for company code { iv_bukrs }|."""
        err = AuthorizationError("2000")
        assert err.company_code == "2000"
        assert str(err) == "Authorization failed for company code 2000"


# ---------------------------------------------------------------------------
# Vendor field mapping — mirrors ABAP SELECT from LFA1 + LFB1 + ADR6
# ---------------------------------------------------------------------------


class TestVendorFieldMapping:
    """Every LFA1/LFB1/ADR6 field must propagate through lookup_vendor."""

    def test_all_vendor_fields_mapped(self, sample_vendor_data):
        """Verify all ty_vendor_detail fields from ABAP are present in output."""
        request = VendorLookupRequest(vendor_number="0000001000")
        response = lookup_vendor(request, sample_vendor_data, [])
        v = response.vendor

        # LFA1 fields
        assert v.vendor_number == "0000001000"    # LIFNR
        assert v.name1 == "Acme Supplies Inc."     # NAME1
        assert v.name2 == "Eastern Division"       # NAME2
        assert v.street == "123 Industrial Pkwy"   # STRAS
        assert v.city == "Springfield"             # ORT01
        assert v.region == "IL"                    # REGIO
        assert v.postal_code == "62701"            # PSTLZ
        assert v.country == "US"                   # LAND1
        assert v.phone == "+1-217-555-0100"        # TELF1
        assert v.fax == "+1-217-555-0101"          # TELFX
        assert v.account_group == "LIEF"           # KTOKK
        assert v.is_blocked is False               # SPERR
        assert v.is_deleted is False               # LOEVM

        # LFB1 fields (company code data)
        assert v.payment_terms == "ZB30"           # ZTERM
        assert v.recon_account == "160000"         # AKONT
        assert v.currency == "USD"                 # WAERS

        # ADR6 field
        assert v.email == "orders@acme-supplies.example.com"  # SMTP_ADDR

    def test_minimal_vendor_data(self):
        """Vendor with only required fields — optional fields default to None/defaults."""
        minimal = {"vendor_number": "0000009999", "name1": "Minimal Corp"}
        request = VendorLookupRequest(vendor_number="0000009999")
        response = lookup_vendor(request, minimal, [])
        v = response.vendor

        assert v.vendor_number == "0000009999"
        assert v.name1 == "Minimal Corp"
        assert v.name2 is None
        assert v.street is None
        assert v.city is None
        assert v.region is None
        assert v.postal_code is None
        assert v.country is None
        assert v.phone is None
        assert v.fax is None
        assert v.email is None
        assert v.account_group is None
        assert v.payment_terms is None
        assert v.recon_account is None
        assert v.currency == "USD"  # Default
        assert v.is_blocked is False
        assert v.is_deleted is False

    def test_deleted_vendor_still_returned(self, sample_vendor_data):
        """ABAP: loevm (deletion flag) is informational — vendor still returned."""
        sample_vendor_data["is_deleted"] = True
        request = VendorLookupRequest(vendor_number="0000001000")
        response = lookup_vendor(request, sample_vendor_data, [])

        assert response.vendor.is_deleted is True
        assert response.return_code == 0


# ---------------------------------------------------------------------------
# PO item field mapping — mirrors ABAP SELECT from EKKO + EKPO
# ---------------------------------------------------------------------------


class TestPOItemFieldMapping:
    """Verify every ty_po_history field maps to PurchaseOrderItem."""

    def test_all_po_fields_mapped(self, sample_vendor_data):
        """All EKKO/EKPO fields from ABAP must propagate to response."""
        today = date.today()
        po_data = [
            {
                "po_number": "4500009999",
                "po_item": "00050",
                "po_date": (today - timedelta(days=5)).isoformat(),
                "material_number": "MAT-XYZ",
                "short_text": "Test Material",
                "quantity": 200,
                "unit_of_measure": "KG",
                "net_price": 15.75,
                "currency": "EUR",
                "delivery_completed": False,
                "purchase_requisition": "2000005678",
            },
        ]
        request = VendorLookupRequest(vendor_number="0000001000")
        response = lookup_vendor(request, sample_vendor_data, po_data)

        assert len(response.po_history) == 1
        item = response.po_history[0]
        assert item.po_number == "4500009999"           # EBELN
        assert item.po_item == "00050"                  # EBELP
        assert item.po_date == today - timedelta(days=5) # BEDAT
        assert item.material_number == "MAT-XYZ"        # MATNR
        assert item.short_text == "Test Material"        # TXZ01
        assert item.quantity == Decimal("200")           # MENGE
        assert item.unit_of_measure == "KG"              # MEINS
        assert item.net_price == Decimal("15.75")        # NETPR
        assert item.currency == "EUR"                    # WAERS
        assert item.delivery_completed is False          # ELIKZ
        assert item.purchase_requisition == "2000005678" # BANFN

    def test_po_date_as_date_object(self, sample_vendor_data):
        """Service handles po_date passed as date object (not only string)."""
        today = date.today()
        po_data = [
            {
                "po_number": "4500000001",
                "po_item": "00010",
                "po_date": today - timedelta(days=10),  # date object, not string
                "quantity": 1,
                "unit_of_measure": "EA",
                "net_price": 10.00,
            },
        ]
        request = VendorLookupRequest(vendor_number="0000001000")
        response = lookup_vendor(request, sample_vendor_data, po_data)

        assert len(response.po_history) == 1
        assert response.po_history[0].po_date == today - timedelta(days=10)

    def test_po_optional_fields_default(self, sample_vendor_data):
        """PO item with only required fields — optional fields get defaults."""
        today = date.today()
        po_data = [
            {
                "po_number": "4500000002",
                "po_item": "00010",
                "po_date": (today - timedelta(days=1)).isoformat(),
                "quantity": 5,
                "unit_of_measure": "EA",
                "net_price": 20.00,
            },
        ]
        request = VendorLookupRequest(vendor_number="0000001000")
        response = lookup_vendor(request, sample_vendor_data, po_data)

        item = response.po_history[0]
        assert item.material_number is None
        assert item.short_text is None
        assert item.currency == "USD"  # Default
        assert item.delivery_completed is False  # Default
        assert item.purchase_requisition is None


# ---------------------------------------------------------------------------
# Date filtering — mirrors ABAP WHERE h~bedat >= lv_date_from
# ---------------------------------------------------------------------------


class TestDateFiltering:
    """Boundary and default date filtering matching ABAP logic."""

    def test_date_from_boundary_inclusive(self, sample_vendor_data):
        """ABAP: WHERE h~bedat >= lv_date_from — boundary date is included."""
        boundary_date = date.today() - timedelta(days=30)
        po_data = [
            {
                "po_number": "4500000010",
                "po_item": "00010",
                "po_date": boundary_date.isoformat(),
                "quantity": 10,
                "unit_of_measure": "EA",
                "net_price": 5.00,
            },
        ]
        request = VendorLookupRequest(
            vendor_number="0000001000",
            date_from=boundary_date,
        )
        response = lookup_vendor(request, sample_vendor_data, po_data)

        # PO date == date_from should be included (>=)
        assert len(response.po_history) == 1

    def test_date_from_boundary_exclusive(self, sample_vendor_data):
        """PO one day before date_from is excluded."""
        boundary_date = date.today() - timedelta(days=30)
        po_data = [
            {
                "po_number": "4500000011",
                "po_item": "00010",
                "po_date": (boundary_date - timedelta(days=1)).isoformat(),
                "quantity": 10,
                "unit_of_measure": "EA",
                "net_price": 5.00,
            },
        ]
        request = VendorLookupRequest(
            vendor_number="0000001000",
            date_from=boundary_date,
        )
        response = lookup_vendor(request, sample_vendor_data, po_data)

        assert len(response.po_history) == 0

    def test_default_date_from_is_365_days(self, sample_vendor_data):
        """ABAP: IF iv_date_from IS INITIAL. lv_date_from = sy-datum - 365."""
        today = date.today()
        po_data = [
            {
                "po_number": "PO-RECENT",
                "po_item": "00010",
                "po_date": (today - timedelta(days=364)).isoformat(),
                "quantity": 1,
                "unit_of_measure": "EA",
                "net_price": 1.00,
            },
            {
                "po_number": "PO-OLD",
                "po_item": "00010",
                "po_date": (today - timedelta(days=366)).isoformat(),
                "quantity": 1,
                "unit_of_measure": "EA",
                "net_price": 1.00,
            },
        ]
        # date_from=None → default 365-day window
        request = VendorLookupRequest(vendor_number="0000001000")
        response = lookup_vendor(request, sample_vendor_data, po_data)

        po_numbers = [item.po_number for item in response.po_history]
        assert "PO-RECENT" in po_numbers
        assert "PO-OLD" not in po_numbers


# ---------------------------------------------------------------------------
# Sorting and limiting — mirrors ABAP ORDER BY / UP TO
# ---------------------------------------------------------------------------


class TestSortingAndLimiting:
    """Verify sort order and limit match ABAP: ORDER BY h~bedat DESCENDING UP TO iv_max_pos ROWS."""

    def test_limit_keeps_most_recent(self, sample_vendor_data):
        """After sorting descending, limit retains the most recent POs."""
        today = date.today()
        po_data = [
            {
                "po_number": f"PO-{i}",
                "po_item": "00010",
                "po_date": (today - timedelta(days=i * 10)).isoformat(),
                "quantity": 1,
                "unit_of_measure": "EA",
                "net_price": 10.00,
            }
            for i in range(5)
        ]
        request = VendorLookupRequest(
            vendor_number="0000001000",
            max_po_items=3,
        )
        response = lookup_vendor(request, sample_vendor_data, po_data)

        assert len(response.po_history) == 3
        # Most recent 3 should be PO-0, PO-1, PO-2 (days 0, 10, 20 ago)
        returned_numbers = [item.po_number for item in response.po_history]
        assert returned_numbers == ["PO-0", "PO-1", "PO-2"]

    def test_limit_larger_than_available(self, sample_vendor_data):
        """max_po_items > actual PO count returns all available POs."""
        today = date.today()
        po_data = [
            {
                "po_number": "ONLY-ONE",
                "po_item": "00010",
                "po_date": (today - timedelta(days=1)).isoformat(),
                "quantity": 1,
                "unit_of_measure": "EA",
                "net_price": 10.00,
            },
        ]
        request = VendorLookupRequest(
            vendor_number="0000001000",
            max_po_items=100,
        )
        response = lookup_vendor(request, sample_vendor_data, po_data)

        assert len(response.po_history) == 1

    def test_unsorted_input_gets_sorted(self, sample_vendor_data):
        """Input PO data in random order is sorted descending by date."""
        today = date.today()
        po_data = [
            {
                "po_number": "PO-OLD",
                "po_item": "00010",
                "po_date": (today - timedelta(days=100)).isoformat(),
                "quantity": 1,
                "unit_of_measure": "EA",
                "net_price": 1.00,
            },
            {
                "po_number": "PO-NEW",
                "po_item": "00010",
                "po_date": (today - timedelta(days=1)).isoformat(),
                "quantity": 1,
                "unit_of_measure": "EA",
                "net_price": 1.00,
            },
            {
                "po_number": "PO-MID",
                "po_item": "00010",
                "po_date": (today - timedelta(days=50)).isoformat(),
                "quantity": 1,
                "unit_of_measure": "EA",
                "net_price": 1.00,
            },
        ]
        request = VendorLookupRequest(vendor_number="0000001000")
        response = lookup_vendor(request, sample_vendor_data, po_data)

        numbers = [item.po_number for item in response.po_history]
        assert numbers == ["PO-NEW", "PO-MID", "PO-OLD"]


# ---------------------------------------------------------------------------
# Aggregate calculation — mirrors ABAP LOOP AT lt_po_hist aggregation
# ---------------------------------------------------------------------------


class TestAggregatesInContext:
    """Verify aggregates computed on filtered+limited PO set, not raw input."""

    def test_aggregates_match_exact_values(self, sample_vendor_data, sample_po_data):
        """Exact aggregate values for the sample data set.

        ABAP: lv_total = SUM(netpr * menge) over returned POs.
        Sample: (100*25.50) + (50*42.00) + (500*8.75) = 2550 + 2100 + 4375 = 9025.
        Open POs: only first item (delivery_completed=False).
        """
        request = VendorLookupRequest(vendor_number="0000001000")
        response = lookup_vendor(request, sample_vendor_data, sample_po_data)

        assert response.vendor.total_po_value == Decimal("9025.00")
        assert response.vendor.open_po_count == 1

    def test_aggregates_on_limited_set(self, sample_vendor_data):
        """Aggregates are calculated AFTER limit is applied (matches ABAP UP TO)."""
        today = date.today()
        po_data = [
            {
                "po_number": "PO-RECENT",
                "po_item": "00010",
                "po_date": (today - timedelta(days=1)).isoformat(),
                "quantity": 10,
                "unit_of_measure": "EA",
                "net_price": 100.00,
                "delivery_completed": False,
            },
            {
                "po_number": "PO-OLDER",
                "po_item": "00010",
                "po_date": (today - timedelta(days=60)).isoformat(),
                "quantity": 5,
                "unit_of_measure": "EA",
                "net_price": 50.00,
                "delivery_completed": False,
            },
        ]
        request = VendorLookupRequest(
            vendor_number="0000001000",
            max_po_items=1,  # Only keep most recent
        )
        response = lookup_vendor(request, sample_vendor_data, po_data)

        # Only PO-RECENT: 10 * 100 = 1000
        assert response.vendor.total_po_value == Decimal("1000")
        assert response.vendor.open_po_count == 1

    def test_all_po_items_open(self):
        """All items have delivery_completed=False → open_count equals total items."""
        items = [
            PurchaseOrderItem(
                po_number=f"PO-{i}",
                po_item="00010",
                po_date=date.today(),
                quantity=Decimal("1"),
                unit_of_measure="EA",
                net_price=Decimal("10"),
                delivery_completed=False,
            )
            for i in range(5)
        ]
        _, open_count = calculate_po_aggregates(items)
        assert open_count == 5

    def test_all_po_items_delivered(self):
        """All items delivered → open_count is zero."""
        items = [
            PurchaseOrderItem(
                po_number=f"PO-{i}",
                po_item="00010",
                po_date=date.today(),
                quantity=Decimal("1"),
                unit_of_measure="EA",
                net_price=Decimal("10"),
                delivery_completed=True,
            )
            for i in range(3)
        ]
        _, open_count = calculate_po_aggregates(items)
        assert open_count == 0

    def test_zero_quantity_po(self):
        """PO with zero quantity contributes 0 to total value."""
        items = [
            PurchaseOrderItem(
                po_number="PO-ZERO",
                po_item="00010",
                po_date=date.today(),
                quantity=Decimal("0"),
                unit_of_measure="EA",
                net_price=Decimal("99.99"),
                delivery_completed=False,
            ),
        ]
        total_value, _ = calculate_po_aggregates(items)
        assert total_value == Decimal("0")

    def test_zero_price_po(self):
        """PO with zero net price contributes 0 to total value."""
        items = [
            PurchaseOrderItem(
                po_number="PO-FREE",
                po_item="00010",
                po_date=date.today(),
                quantity=Decimal("100"),
                unit_of_measure="EA",
                net_price=Decimal("0"),
                delivery_completed=False,
            ),
        ]
        total_value, _ = calculate_po_aggregates(items)
        assert total_value == Decimal("0")


# ---------------------------------------------------------------------------
# Return message — mirrors ABAP ev_return_msg format
# ---------------------------------------------------------------------------


class TestReturnMessage:
    """Verify return message matches ABAP format."""

    def test_success_message_format(self, sample_vendor_data, sample_po_data):
        """ABAP: |Vendor { iv_lifnr } retrieved successfully. { lines( lt_po_hist ) } PO items returned.|"""
        request = VendorLookupRequest(vendor_number="0000001000")
        response = lookup_vendor(request, sample_vendor_data, sample_po_data)

        assert response.return_message == (
            "Vendor 0000001000 retrieved successfully. 3 PO items returned."
        )

    def test_success_message_with_zero_pos(self, sample_vendor_data):
        """Return message correctly reports 0 PO items when none match."""
        request = VendorLookupRequest(
            vendor_number="0000001000",
            date_from=date.today(),  # No POs today
        )
        response = lookup_vendor(request, sample_vendor_data, [])

        assert response.return_message == (
            "Vendor 0000001000 retrieved successfully. 0 PO items returned."
        )

    def test_success_return_code_is_zero(self, sample_vendor_data):
        """ABAP: ev_return_code = 0 for successful lookup."""
        request = VendorLookupRequest(vendor_number="0000001000")
        response = lookup_vendor(request, sample_vendor_data, [])

        assert response.return_code == 0


# ---------------------------------------------------------------------------
# End-to-end integration — full ABAP function module equivalence
# ---------------------------------------------------------------------------


class TestEndToEndEquivalence:
    """Full round-trip tests matching the complete ABAP function module behavior."""

    def test_full_lookup_with_mixed_po_statuses(self, sample_vendor_data):
        """Complete lookup with mixed open/closed POs — validates all outputs."""
        today = date.today()
        po_data = [
            {
                "po_number": "4500010001",
                "po_item": "00010",
                "po_date": (today - timedelta(days=10)).isoformat(),
                "material_number": "MAT-A",
                "short_text": "Alpha Widget",
                "quantity": 50,
                "unit_of_measure": "EA",
                "net_price": 20.00,
                "currency": "USD",
                "delivery_completed": False,
            },
            {
                "po_number": "4500010001",
                "po_item": "00020",
                "po_date": (today - timedelta(days=10)).isoformat(),
                "material_number": "MAT-B",
                "short_text": "Beta Widget",
                "quantity": 100,
                "unit_of_measure": "EA",
                "net_price": 15.00,
                "currency": "USD",
                "delivery_completed": True,
            },
            {
                "po_number": "4500010002",
                "po_item": "00010",
                "po_date": (today - timedelta(days=5)).isoformat(),
                "material_number": "MAT-C",
                "short_text": "Gamma Widget",
                "quantity": 25,
                "unit_of_measure": "EA",
                "net_price": 40.00,
                "currency": "USD",
                "delivery_completed": False,
            },
        ]
        request = VendorLookupRequest(vendor_number="0000001000")
        response = lookup_vendor(request, sample_vendor_data, po_data)

        # Return code
        assert response.return_code == 0

        # PO count
        assert len(response.po_history) == 3

        # Sort order (most recent first)
        assert response.po_history[0].po_number == "4500010002"

        # Aggregates: (50*20) + (100*15) + (25*40) = 1000 + 1500 + 1000 = 3500
        assert response.vendor.total_po_value == Decimal("3500")
        # 2 open items
        assert response.vendor.open_po_count == 2

        # Return message
        assert response.return_message == (
            "Vendor 0000001000 retrieved successfully. 3 PO items returned."
        )

    def test_vendor_with_no_purchase_history(self, sample_vendor_data):
        """New vendor with no POs — aggregates should be zero."""
        request = VendorLookupRequest(vendor_number="0000001000")
        response = lookup_vendor(request, sample_vendor_data, [])

        assert response.return_code == 0
        assert len(response.po_history) == 0
        assert response.vendor.total_po_value == Decimal("0")
        assert response.vendor.open_po_count == 0
        assert "0 PO items returned" in response.return_message

    def test_custom_company_code(self, sample_vendor_data):
        """Non-default company code passes through correctly."""
        request = VendorLookupRequest(
            vendor_number="0000001000",
            company_code="2000",
        )
        response = lookup_vendor(request, sample_vendor_data, [])

        # Company code is a request parameter; service should still succeed
        assert response.return_code == 0

    def test_single_po_item(self, sample_vendor_data):
        """Single PO item — verify aggregates with one item."""
        today = date.today()
        po_data = [
            {
                "po_number": "4500099999",
                "po_item": "00010",
                "po_date": (today - timedelta(days=1)).isoformat(),
                "quantity": 75,
                "unit_of_measure": "EA",
                "net_price": 12.00,
                "delivery_completed": False,
            },
        ]
        request = VendorLookupRequest(vendor_number="0000001000")
        response = lookup_vendor(request, sample_vendor_data, po_data)

        assert response.vendor.total_po_value == Decimal("900")  # 75 * 12
        assert response.vendor.open_po_count == 1
        assert len(response.po_history) == 1
