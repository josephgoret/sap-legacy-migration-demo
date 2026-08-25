# ABAP to Python Migration Assessment

Assessment date: 2026-08-25

## Scope and decision rule

This assessment compares the three ABAP objects with their Python targets using the
playbook's rule that migration should preserve functional behavior rather than improve it
(`migration-playbook.md:103-112`). It also checks the pre-migration requirements
(`migration-playbook.md:29-38`), Step 6 validation criteria
(`migration-playbook.md:129-136`), and the quality checklist
(`migration-playbook.md:288-300`).

Deviation classifications:

- **(a) Acceptable interface-layer translation:** the representation changes because the
  target interface is different, while the business behavior can remain equivalent.
- **(b) Added feature or optimization:** behavior was added or constrained without an ABAP
  equivalent. This conflicts with the playbook's functional-equivalence-first rule.
- **(c) Behavioral risk requiring sign-off:** the target omits, changes, or assumes behavior
  that can affect results, errors, authorization, transactions, or downstream consumers.

**Overall finding:** none of the three targets currently meets the playbook's 1:1 validation
standard. The interface translations are directionally reasonable, but each object also
contains unapproved added behavior and material gaps in source selection, error handling, or
side effects. The current test baseline cannot run.

## Test baseline

The requested baseline commands were run from the repository root:

```text
python -m pip install -r requirements.txt
pytest tests/ -v
```

Dependency installation succeeded. The test run used Python 3.10.12, pytest 8.4.2, and
Pydantic 2.13.4. Collection stopped with:

```text
ImportError: cannot import name 'UTC' from 'datetime'
```

The failing import is at `python_target/inventory_report/service.py:15`; `datetime.UTC` is
not available in Python 3.10. Pytest reported 24 collected tests and one collection error,
so no tests executed. The repository contains 41 test functions: 17 inventory, 9 vendor,
and 15 order-sync tests. The baseline therefore does **not** satisfy the playbook's
"all tests pass" checks (`migration-playbook.md:131`, `migration-playbook.md:292`).

## 1. Inventory Report

Sources:

- ABAP: `abap_source/z_inventory_report.abap`
- Python: `python_target/inventory_report/models.py`,
  `python_target/inventory_report/service.py`
- Tests: `tests/test_inventory_report.py`

### Pre-Migration Checklist

| Checklist item | Status | Repository evidence |
|---|---|---|
| Source ABAP exported and accessible | Satisfied | The complete report, type, selection screen, four FORMs, SQL, messages, and ALV setup are present in `abap_source/z_inventory_report.abap:1-282`. |
| Business owner confirmed object is still in use | Not evidenced | The README describes a fictional demo and migration pattern (`README.md:1-16`), but contains no owner, usage confirmation, or retirement decision. |
| Target architecture defined | Partial | The stated target is FastAPI plus JSON and a data-warehouse equivalent (`README.md:54-64`; `python_target/inventory_report/service.py:4-12`). No endpoint, query adapter, database model, deployment configuration, or FastAPI dependency exists in the repository. |
| Data dictionary dependencies mapped | Satisfied for source reads; target mapping incomplete | MARA, MAKT, MARC, MARD, MSEG, and MKPF fields and joins are explicit in `abap_source/z_inventory_report.abap:81-145`; the Python model records the source fields in `python_target/inventory_report/models.py:57-86`. The target warehouse schema and query are not present. |
| Test data available | Satisfied | Test rows cover stock, reorder points, dates, filters, and empty data in `tests/test_inventory_report.py:36-273`. |
| Acceptance criteria defined | Partial | Threshold, percentage, status-filter, sort, summary, and empty-input tests exist (`tests/test_inventory_report.py:29-273`). They do not validate source-table filtering, goods-receipt aggregation, ABAP message paths, ALV errors, selection-option semantics, or the fixed stock-value calculation. The suite currently cannot be collected. |

### Confirmed like-for-like behavior

- The `ty_inventory` business fields map to `InventoryItem`
  (`abap_source/z_inventory_report.abap:16-36`;
  `python_target/inventory_report/models.py:57-86`).
- Total stock remains `LABST + INSME + SPEME`
  (`abap_source/z_inventory_report.abap:135-136`;
  `python_target/inventory_report/service.py:129-134`).
- Percentage and traffic-light thresholds match, including the strict `1.5x` boundary and
  stale-stock downgrade from green to yellow
  (`abap_source/z_inventory_report.abap:157-182`;
  `python_target/inventory_report/service.py:28-73`).
- The three status checkboxes retain their ABAP defaults and inclusion logic
  (`abap_source/z_inventory_report.abap:49-53`, `abap_source/z_inventory_report.abap:194-206`;
  `python_target/inventory_report/models.py:48-54`,
  `python_target/inventory_report/service.py:76-88`).
- Output items are sorted by status and then plant, matching the ALV configuration
  (`abap_source/z_inventory_report.abap:266-269`;
  `python_target/inventory_report/service.py:177-183`).

### Non-Like-for-Like Elements

| ABAP element | Python element | Deviation type | Risk / notes |
|---|---|---|---|
| SAP selection options support include/exclude rows, ranges, and operators for plant, storage location, material group, and material type (`abap_source/z_inventory_report.abap:41-46`). | `InventoryFilters` uses plain `list[str]` values (`python_target/inventory_report/models.py:30-42`), and `generate_inventory_report` does not apply those four filters (`python_target/inventory_report/service.py:112-175`). | **(c)** | The service assumes an upstream query already applied equivalent filtering. That contract and SAP range semantics are not implemented or tested, so the same request can return a different population. |
| `p_stale` is an unconstrained ABAP integer with default 90 (`abap_source/z_inventory_report.abap:46`). | `stale_days` rejects values below 1 (`python_target/inventory_report/models.py:43-47`). | **(b)** | This is new input validation. Zero or negative values that ABAP accepts are rejected before business logic runs. |
| `stock_status` is a one-character value (`1`, `2`, `3`), packed values have SAP-defined scale, and an initial DATS value is blank (`abap_source/z_inventory_report.abap:16-34`). | Status is a text enum (`critical`, `warning`, `healthy`); quantities use unconstrained `Decimal`; blank dates become `None` (`python_target/inventory_report/models.py:16-27`, `python_target/inventory_report/models.py:57-86`). | **(a)** | These are reasonable JSON/Python representations, but consumers must use an explicit mapping and agree on rounding, scale, and blank-date serialization. |
| `FORM fetch_inventory_data` executes MARA/MAKT/MARC/MARD joins, uses `sy-langu`, and excludes deleted materials (`abap_source/z_inventory_report.abap:79-107`). | No `fetch_inventory_data` function or query exists. `generate_inventory_report` accepts prebuilt dictionaries (`python_target/inventory_report/service.py:112-134`). | **(c)** | The target does not enforce join cardinality, language selection, plant/storage relationships, or `MARA-LVORM = ' '`. Step 6's one-function-per-FORM criterion is also unmet. |
| The ABAP SELECT populates a statically typed internal table, so all subsequent rows have the declared fields and SAP types (`abap_source/z_inventory_report.abap:16-36`, `abap_source/z_inventory_report.abap:81-102`). | `raw_data` is an unvalidated `list[dict]`; missing keys, invalid decimals, or invalid date strings can raise uncaught conversion, `KeyError`, or Pydantic errors (`python_target/inventory_report/service.py:112-171`). | **(c)** | The target introduces malformed-input paths with no defined API error mapping. A typed warehouse-row model or adapter contract is needed. |
| A failed initial SELECT produces a warning-style SAP message and stops list processing (`abap_source/z_inventory_report.abap:104-107`). | Empty input returns a normal response with zero items (`python_target/inventory_report/service.py:174-193`; `tests/test_inventory_report.py:267-273`). | **(c)** | "No data" changed from an explicit user-visible warning and early termination to a successful empty payload. The test codifies the changed behavior rather than ABAP-equivalent error behavior. |
| Last receipt is calculated from movement type 101 using `MAX(MKPF-BUDAT)` grouped by material and plant, then found with a binary search (`abap_source/z_inventory_report.abap:109-145`). | Each row supplies `last_receipt_date`; no MSEG/MKPF query, movement filter, grouping, or plant-level lookup exists (`python_target/inventory_report/service.py:136-145`). | **(c)** | Stale status is only equivalent if the upstream warehouse query reproduces the ABAP calculation exactly. No adapter or test proves that assumption. |
| `FORM calculate_stock_status` performs percentage, status, stale-date, value, and currency calculations in one pass (`abap_source/z_inventory_report.abap:152-189`). | The logic is split among `calculate_stock_status`, `calculate_stock_percentage`, and `generate_inventory_report` (`python_target/inventory_report/service.py:28-73`, `python_target/inventory_report/service.py:112-172`). | **(a)** | Decomposition is acceptable if outputs remain identical. Traceability is weaker because one ABAP FORM no longer has one corresponding Python function as required by `migration-playbook.md:105-108`. |
| Stock value is always `total_stock * 10` and currency is always `USD` (`abap_source/z_inventory_report.abap:184-186`). | `unit_cost` and `currency` can be supplied per row, with 10 and USD only as defaults (`python_target/inventory_report/service.py:149-170`). | **(b)** | Variable valuation and currency are new behavior. The inventory test deliberately uses costs 25, 50, and 15 (`tests/test_inventory_report.py:193-233`), so the target no longer reproduces the ABAP report's values. |
| An empty result after status filtering shows "No materials match the selected status filters." and exits (`abap_source/z_inventory_report.abap:208-211`). | `filter_by_status` returns an empty list, and the report returns success with `total_items = 0` (`python_target/inventory_report/service.py:76-88`, `python_target/inventory_report/service.py:174-193`). | **(c)** | The message and early-exit path are missing. `tests/test_inventory_report.py:247-265` expects the non-equivalent empty success response. |
| `FORM display_alv` creates an interactive ALV with named columns, built-in sort/filter/export, a title, striping, and optimized widths (`abap_source/z_inventory_report.abap:218-276`). | `InventoryReportResponse` returns JSON items (`python_target/inventory_report/models.py:89-96`). | **(a)** | ALV-to-JSON is the playbook's intended interface translation (`migration-playbook.md:71`). A frontend must own the dropped presentation and interaction features. |
| SALV creation and column errors are caught and raised as a type-E SAP message (`abap_source/z_inventory_report.abap:220-280`). | There is no display adapter or corresponding exception path. | **(c)** | The target has no equivalent failure contract for response rendering or schema/column errors. |
| The ALV output is the filtered row set only (`abap_source/z_inventory_report.abap:218-276`). | The response adds `generated_at`, `filters_applied`, `total_items`, and an aggregated summary (`python_target/inventory_report/models.py:89-107`; `python_target/inventory_report/service.py:91-109`, `python_target/inventory_report/service.py:185-193`). | **(b)** | The summary is explicitly described as added value, including in `README.md:64`. It violates the rule against improving output during the equivalence phase and needs separate approval. |
| No stale-material aggregate exists in the ALV. | `InventoryReportSummary.stale_materials` is added but never incremented (`python_target/inventory_report/models.py:99-107`; `python_target/inventory_report/service.py:91-109`). | **(c)** | The API exposes a field that always reports zero, even when stale items are downgraded. This is both non-equivalent and misleading. |
| The ABAP report runs in its SAP-supported runtime. | Importing the Python service requires `datetime.UTC` (`python_target/inventory_report/service.py:15`, `python_target/inventory_report/service.py:188`). | **(c)** | The repository's current Python 3.10 baseline cannot import the module, so none of the inventory behavior is executable in the stated environment. |

## 2. Vendor Lookup

Sources:

- ABAP: `abap_source/z_rfc_vendor_lookup.abap`
- Python: `python_target/vendor_lookup/models.py`,
  `python_target/vendor_lookup/service.py`
- Tests: `tests/test_vendor_lookup.py`

### Pre-Migration Checklist

| Checklist item | Status | Repository evidence |
|---|---|---|
| Source ABAP exported and accessible | Satisfied | The RFC interface, types, authority check, three master-data reads, PO query, aggregation, exceptions, and outputs are present in `abap_source/z_rfc_vendor_lookup.abap:1-163`. |
| Business owner confirmed object is still in use | Not evidenced | The source comment names external callers (`abap_source/z_rfc_vendor_lookup.abap:4-6`), but the repository has no current owner or usage confirmation. |
| Target architecture defined | Partial | The target is described as REST/FastAPI plus a warehouse or ORM (`README.md:68-76`; `python_target/vendor_lookup/service.py:4-12`). No HTTP route, middleware, query implementation, error mapper, database schema, or deployment configuration exists. |
| Data dictionary dependencies mapped | Satisfied for source reads; target mapping incomplete | LFA1, LFB1, ADR6, EKKO, and EKPO fields and joins are explicit (`abap_source/z_rfc_vendor_lookup.abap:29-65`, `abap_source/z_rfc_vendor_lookup.abap:90-139`) and reflected in the Pydantic models (`python_target/vendor_lookup/models.py:15-77`). The target query contract is not defined. |
| Test data available | Satisfied | Vendor and PO fixtures cover joined master data, dates, values, delivery completion, and missing optional values (`tests/test_vendor_lookup.py:29-96`). |
| Acceptance criteria defined | Partial | Tests cover aggregates, success, not-found, date filtering, limit, descending sort, and a blocked vendor (`tests/test_vendor_lookup.py:99-229`). They omit authorization, return-code behavior for errors, company-code isolation, deletion filters, default-email selection, and source-query equivalence. |

### Confirmed like-for-like behavior

- The fields in `ty_vendor_detail` and `ty_po_history` have direct Pydantic counterparts
  (`abap_source/z_rfc_vendor_lookup.abap:29-65`;
  `python_target/vendor_lookup/models.py:15-77`).
- The default date remains 365 days before the current date
  (`abap_source/z_rfc_vendor_lookup.abap:121-125`;
  `python_target/vendor_lookup/service.py:107-108`).
- Date filtering, descending date order, maximum item count, total value, and open-item count
  use the same formulas once the input rows are equivalent
  (`abap_source/z_rfc_vendor_lookup.abap:127-153`;
  `python_target/vendor_lookup/service.py:107-142`).
- The success code and success-message shape are preserved
  (`abap_source/z_rfc_vendor_lookup.abap:158-161`;
  `python_target/vendor_lookup/service.py:144-151`).

### Non-Like-for-Like Elements

| ABAP element | Python element | Deviation type | Risk / notes |
|---|---|---|---|
| RFC IMPORTING/EXPORTING parameters and declared exceptions form the external contract (`abap_source/z_rfc_vendor_lookup.abap:13-27`). | Pydantic request/response models and Python exceptions form the intended REST contract (`python_target/vendor_lookup/models.py:80-102`; `python_target/vendor_lookup/service.py:27-40`). | **(a)** | RFC-to-REST is an expected interface translation. The repository still lacks the endpoint and HTTP exception mapper needed to make the mapping concrete. |
| ABAP character flags use initial or `X`, packed totals have fixed scale, and missing character fields remain initial (`abap_source/z_rfc_vendor_lookup.abap:29-65`). | Flags are booleans, missing fields are often `None`, currency defaults to USD, and numbers use `Decimal` without declared scale (`python_target/vendor_lookup/models.py:15-77`). | **(a)** | The representation is reasonable for JSON, but conversion rules for blank versus null, currency defaults, and decimal rounding need an agreed interface contract. |
| `IV_MAX_POS` is an unconstrained integer with default 50 (`abap_source/z_rfc_vendor_lookup.abap:15-18`). | `max_po_items` must be between 1 and 500 (`python_target/vendor_lookup/models.py:87-89`). | **(b)** | The upper bound and rejection of zero or negative values are new validation behavior not present in the ABAP object. |
| `AUTHORITY-CHECK F_LFA1_BUK` checks company code and display activity before any read; failure sets code 2/message and raises (`abap_source/z_rfc_vendor_lookup.abap:74-85`). | `AuthorizationError` exists, but `lookup_vendor` never raises it and no middleware exists in the repository (`python_target/vendor_lookup/service.py:7-12`, `python_target/vendor_lookup/service.py:35-40`, `python_target/vendor_lookup/service.py:63-152`). | **(c)** | Authorization is deferred in prose, not implemented. Calling the service function bypasses the ABAP security gate entirely. The imported exception is not tested (`tests/test_vendor_lookup.py:17-22`). |
| LFA1 is selected by `IV_LIFNR`; LFB1 is selected by vendor and `IV_BUKRS`; ADR6 selects the default address (`abap_source/z_rfc_vendor_lookup.abap:87-116`). | A prejoined `vendor_data` dictionary is accepted without checking vendor number, company code, or default-email selection (`python_target/vendor_lookup/service.py:63-105`). | **(c)** | The function can return data for a different vendor or company code if the caller supplies mismatched data. Equivalence depends on an upstream query that is absent and untested. |
| Missing LFA1 data sets return code 1 and message, then raises `VENDOR_NOT_FOUND` (`abap_source/z_rfc_vendor_lookup.abap:97-101`). | Missing data raises `VendorNotFoundError` only (`python_target/vendor_lookup/service.py:82-84`). | **(c)** | No `VendorLookupResponse` with code 1 is produced. Downstream behavior depends on an HTTP mapper that is not present. |
| A missing LFB1 or ADR6 row leaves the selected fields initial; no extra defaults are assigned (`abap_source/z_rfc_vendor_lookup.abap:103-116`). | Missing combined fields become `None`, while missing currency becomes `USD` (`python_target/vendor_lookup/service.py:86-105`). | **(c)** | Defaulting currency can invent data where ABAP returns an initial value. Blank versus null also changes serialized output. |
| The EKKO/EKPO query enforces vendor, company code, header not-deleted, item not-deleted, and date conditions in the database (`abap_source/z_rfc_vendor_lookup.abap:127-139`). | `lookup_vendor` filters only by date; it trusts `po_data` for all other predicates (`python_target/vendor_lookup/service.py:107-133`). | **(c)** | Deleted PO items, another vendor's POs, or another company code's POs can enter history and aggregates. No test covers these source predicates. |
| Database fields arrive through typed SELECT targets (`abap_source/z_rfc_vendor_lookup.abap:90-139`). | `vendor_data` and `po_data` are unvalidated dictionaries until individual Pydantic models are constructed (`python_target/vendor_lookup/service.py:63-133`). | **(c)** | Missing required keys, invalid dates, or invalid numeric values raise exceptions outside the documented not-found and authorization contract. |
| SQL applies `ORDER BY BEDAT DESCENDING UP TO IV_MAX_POS ROWS` (`abap_source/z_rfc_vendor_lookup.abap:127-139`). | Python sorts all supplied rows and slices the list (`python_target/vendor_lookup/service.py:135-137`). | **(a)** | The result is equivalent for a correctly filtered finite input. Tie ordering is still unspecified, and moving the limit out of the database can materially change performance. |
| SAP packed totals have length 15 and two decimals (`abap_source/z_rfc_vendor_lookup.abap:48`, `abap_source/z_rfc_vendor_lookup.abap:142-146`). | Python uses arbitrary-precision `Decimal` and does not quantize to two decimals (`python_target/vendor_lookup/models.py:48-50`; `python_target/vendor_lookup/service.py:43-60`). | **(c)** | Values with more than two fractional digits can differ from SAP assignment and rounding behavior. |
| Error outputs define code 1 for not found and 2 for authorization failure (`abap_source/z_rfc_vendor_lookup.abap:20-26`, `abap_source/z_rfc_vendor_lookup.abap:81-100`). | `VendorLookupResponse` documents all three codes, but `lookup_vendor` only returns code 0 (`python_target/vendor_lookup/models.py:96-102`; `python_target/vendor_lookup/service.py:144-151`). | **(c)** | The response model suggests a contract the service does not implement. Error-code consumers cannot receive the ABAP-equivalent payload. |
| The RFC has explicit `SY-SUBRC` branches for authorization and vendor-not-found (`abap_source/z_rfc_vendor_lookup.abap:81-100`). | Only the not-found branch has an executable equivalent; no general query/error path exists (`python_target/vendor_lookup/service.py:63-152`). | **(c)** | Database/warehouse failures, authorization failures, and malformed upstream data do not have defined ABAP-equivalent responses. |

## 3. Order Sync

Sources:

- ABAP: `abap_source/z_idoc_order_sync.abap`
- Python: `python_target/order_sync/models.py`,
  `python_target/order_sync/service.py`
- Tests: `tests/test_order_sync.py`

### Pre-Migration Checklist

| Checklist item | Status | Repository evidence |
|---|---|---|
| Source ABAP exported and accessible | Satisfied | The function interface, control/data/status tables, two local types, five parsing FORMs, validation, BAPI mapping, transaction handling, and status FORM are present in `abap_source/z_idoc_order_sync.abap:1-385`. |
| Business owner confirmed object is still in use | Not evidenced | The source comment says the SAP IDoc framework calls it (`abap_source/z_idoc_order_sync.abap:4-6`), but no current owner, volume, partner, or usage confirmation is recorded. |
| Target architecture defined | Partial | The intended target is a queue-driven service and target-system API (`README.md:78-88`; `python_target/order_sync/service.py:4-16`). No queue consumer, message schema version, target API client, transaction manager, retry/dead-letter policy, or deployment configuration exists. |
| Data dictionary dependencies mapped | Satisfied for source structures; target mapping incomplete | EDIDC, EDIDD, BDIDOCSTAT, ORDERS05 segment structures, BAPI structures, and transaction BAPIs are explicit in `abap_source/z_idoc_order_sync.abap:13-73`, `abap_source/z_idoc_order_sync.abap:91-252`, and `abap_source/z_idoc_order_sync.abap:258-385`. The target API payload and persistence model are unspecified. |
| Test data available | Satisfied | Fixtures provide structured messages and all five segment types (`tests/test_order_sync.py:34-145`). |
| Acceptance criteria defined | Partial | Tests cover selected validation, parsing, a simulated success, validation failure, and mixed batches (`tests/test_order_sync.py:148-294`). They omit control-record filtering, ABAP interface outputs, BAPI payloads and errors, commit/rollback, status field formatting, all added validations, target API failures, and actual queue deserialization. |

### Confirmed like-for-like behavior

- The fields in `ty_order_header` and `ty_order_item` have Python model counterparts
  (`abap_source/z_idoc_order_sync.abap:27-54`;
  `python_target/order_sync/models.py:41-98`).
- The E1EDK03 qualifiers 012, 022, and 026 map to the same three dates
  (`abap_source/z_idoc_order_sync.abap:274-292`;
  `python_target/order_sync/service.py:125-135`).
- AG, WE, RE, and RG partner roles map to the same partner codes; sold-to and ship-to also
  populate header fields (`abap_source/z_idoc_order_sync.abap:294-324`;
  `python_target/order_sync/service.py:137-152`).
- E1EDP01 and E1EDP19 retain the item, quantity, unit, price, category, SAP material, and
  customer-material mappings (`abap_source/z_idoc_order_sync.abap:326-362`;
  `python_target/order_sync/service.py:154-172`).
- Missing sold-to and no-items conditions still produce a failed result, although the error
  ordering and output contract differ
  (`abap_source/z_idoc_order_sync.abap:143-158`;
  `python_target/order_sync/service.py:51-89`, `python_target/order_sync/service.py:194-206`).

### Non-Like-for-Like Elements

| ABAP element | Python element | Deviation type | Risk / notes |
|---|---|---|---|
| The function receives `INPUT_METHOD`, `MASS_PROCESSING`, `IDOC_CONTRL`, `IDOC_DATA`, `IDOC_STATUS`, and `RETURN_VARIABLES`, and exports `WORKFLOW_RESULT` and `APPLICATION_VARIABLE` (`abap_source/z_idoc_order_sync.abap:13-25`). | The target receives `InboundOrderMessage` objects and returns `OrderSyncBatchResult` (`python_target/order_sync/models.py:101-135`). Input method, mass-processing mode, workflow result, application variable, and return variables have no equivalents. | **(c)** | The queue contract drops SAP framework control and workflow outputs. Sign-off is needed that no caller or workflow relies on them. |
| `workflow_result` is initialized to success (`abap_source/z_idoc_order_sync.abap:75`). | No workflow-result field is produced. | **(c)** | A downstream workflow cannot observe the ABAP output contract. |
| The outer loop processes only control records with `MESTYP = 'ORDERS'` and status 64 (`abap_source/z_idoc_order_sync.abap:77-84`). | Every message passed to `process_order_batch` is processed; `message_type` is not checked and there is no processing-status field (`python_target/order_sync/models.py:101-115`; `python_target/order_sync/service.py:242-264`). | **(c)** | Non-ORDERS or not-ready messages can be processed. The existing test only supplies ORDERS and does not verify rejection (`tests/test_order_sync.py:74-81`). |
| IDoc data rows are grouped to each control record by DOCNUM (`abap_source/z_idoc_order_sync.abap:84-94`). | Each message carries one already assembled `OrderHeader` (`python_target/order_sync/models.py:101-115`). | **(a)** | Grouping at ingestion is a valid queue-layer translation if the producer guarantees one complete, correctly correlated order per message. |
| Fixed EDIDD segment payloads are copied into E1EDK01/E1EDK03/E1EDKA1/E1EDP01/E1EDP19 structures (`abap_source/z_idoc_order_sync.abap:258-362`). | The main contract uses structured JSON/Pydantic data; `parse_idoc_to_order` accepts dictionaries as a demonstration helper (`python_target/order_sync/service.py:92-174`). | **(a)** | IDoc-segment-to-JSON is the intended interface translation. The production deserialization path and schema version are not implemented. |
| E1EDK01 parsing sets only document type and currency (`abap_source/z_idoc_order_sync.abap:261-271`). | The helper also reads sales organization, distribution channel, and division from the E1EDK01 dictionary (`python_target/order_sync/service.py:118-123`). | **(b)** | These extra mappings are not in the ABAP FORM and may not correspond to actual ORDERS05 E1EDK01 fields. They also supply values required by later Python validation. |
| An initial document type is defaulted to `ZOR` only during BAPI header mapping; currency remains whatever was parsed, including initial (`abap_source/z_idoc_order_sync.abap:164-178`). | `OrderHeader` defaults document type to `ZOR` and currency to `USD`, and the parsing helper applies the same defaults during parsing (`python_target/order_sync/models.py:70-90`; `python_target/order_sync/service.py:118-120`). | **(c)** | The USD default invents a currency not present in ABAP. Moving the document-type default earlier can also affect validation or intermediate consumers. |
| E1EDP01 parsing copies POSEX, MENGE, MENEE, VPREI, and PSTYV; plant remains initial because the FORM never sets it (`abap_source/z_idoc_order_sync.abap:329-343`). | The helper supplies defaults for item number, unit, and price and additionally reads `PLANT` (`python_target/order_sync/service.py:154-162`). | **(b)** | The target accepts and creates values that the ABAP parser would leave initial. Default item `000010`, unit `EA`, zero price, and plant mapping all need separate approval. |
| The ABAP validation stage checks only missing sold-to, then missing items, stopping at the first failure (`abap_source/z_idoc_order_sync.abap:143-158`). | Python also requires sales organization, distribution channel, division, positive quantity, and either SAP or customer material, and accumulates all errors (`python_target/order_sync/service.py:51-89`). | **(b)** | Five additional validation rules reject orders that ABAP would pass to the BAPI. Accumulating errors also changes which messages are returned when more than one condition fails. |
| Validation messages are exactly "Missing sold-to party in IDoc" or "No order items found in IDoc" and are written as IDoc status 51/E (`abap_source/z_idoc_order_sync.abap:146-157`). | Messages are "Missing sold-to party (AG partner)" and "No order items found", returned in a list with status `failed` (`python_target/order_sync/service.py:62-66`, `python_target/order_sync/service.py:202-206`). | **(c)** | Text, code, message type, field layout, and first-error behavior differ. Existing tests check substrings rather than the ABAP output contract (`tests/test_order_sync.py:158-168`). |
| Segment parsing keeps header sold-to/ship-to fields and the BAPI partner table synchronized from the same E1EDKA1 row (`abap_source/z_idoc_order_sync.abap:297-324`). | Direct `InboundOrderMessage` input can provide `sold_to_party`, `ship_to_party`, and `partners` independently (`python_target/order_sync/models.py:62-115`). | **(c)** | Contradictory header and partner values are accepted. Validation checks only the header sold-to value, and no target mapping reconciles the duplicate representations. |
| Unsupported segments, partner roles, and material qualifiers are ignored by the ABAP CASE statements (`abap_source/z_idoc_order_sync.abap:96-140`, `abap_source/z_idoc_order_sync.abap:307-322`, `abap_source/z_idoc_order_sync.abap:355-360`). | The parsing helper also ignores them, but direct JSON construction rejects unsupported partner roles through `PartnerRole` validation (`python_target/order_sync/models.py:25-38`; `python_target/order_sync/service.py:115-172`). | **(c)** | The outcome depends on whether a message uses the helper or arrives already deserialized. The production boundary is not defined. |
| IDoc segment values are assigned into SAP-typed structures before business validation (`abap_source/z_idoc_order_sync.abap:91-141`, `abap_source/z_idoc_order_sync.abap:258-362`). | Pydantic can reject malformed message, date, enum, or decimal fields before `process_single_order`, so no `OrderSyncResult` or failed status is produced (`python_target/order_sync/models.py:34-115`; `python_target/order_sync/service.py:177-240`). | **(c)** | Deserialization failures need an explicit queue error, retry, and status policy to replace the IDoc framework's failure handling. |
| `OrderValidationError` has no ABAP counterpart beyond status handling. | The exception is defined but never raised or caught (`python_target/order_sync/service.py:39-48`). | **(b)** | This is unused added API surface and can mislead callers about the actual error contract. |
| Header mapping explicitly sets BAPISDHD1 and BAPISDHD1X fields, including insert flags (`abap_source/z_idoc_order_sync.abap:160-185`). | The target passes an `OrderHeader` to a stub; no target payload mapping exists (`python_target/order_sync/service.py:177-239`, `python_target/order_sync/service.py:267-277`). | **(c)** | There is no evidence that document type, organization fields, PO fields, dates, currency, or incoterms would reach the target system with equivalent semantics. |
| Item mapping builds BAPISDITM records and BAPISCHDL schedule lines with requested date and quantity (`abap_source/z_idoc_order_sync.abap:187-207`). | No item, schedule-line, or partner payload mapping is implemented (`python_target/order_sync/service.py:208-277`). | **(c)** | Schedule quantities/dates and BAPI partner semantics can be lost. The target API contract is only a comment. |
| The BAPI call uses header, item, partner, schedule, condition, and return tables and returns a real VBELN (`abap_source/z_idoc_order_sync.abap:209-223`). | `_create_order_in_target_system` ignores the order and returns the first ten decimal digits of a UUID integer (`python_target/order_sync/service.py:267-277`). | **(c)** | The demo always simulates success and produces no real order. It cannot establish functional equivalence for the central side effect. |
| BAPI return rows of type E or A trigger rollback; all such messages are concatenated (`abap_source/z_idoc_order_sync.abap:225-243`). | Any Python exception triggers a failed result containing only `str(exc)` (`python_target/order_sync/service.py:228-239`). | **(c)** | Structured target errors, warning/success handling, multiple errors, and SAP E/A severity semantics are not mapped. The stub currently has no failure path. |
| Success calls `BAPI_TRANSACTION_COMMIT` with `WAIT = 'X'`; failure calls rollback (`abap_source/z_idoc_order_sync.abap:232-251`). | Commit and rollback appear only in comments; no transaction manager or API compensation exists (`python_target/order_sync/service.py:184-190`, `python_target/order_sync/service.py:208-239`). | **(c)** | Atomicity and durability are unimplemented. A target API failure after a partial write could behave differently from the SAP logical unit of work. |
| `set_idoc_status` writes DOCNUM, numeric status 51/53, message type E/S, and at most two 50-character message fields (`abap_source/z_idoc_order_sync.abap:364-385`). | `OrderSyncResult` uses `message_id`, `created`/`failed`, a separate order number, and an unbounded error string list (`python_target/order_sync/models.py:118-126`). | **(a)** | A richer result object is a reasonable event/API representation, but an explicit mapping is required for consumers that depend on 51/53 or SAP message fields. |
| Success status includes `Sales order <VBELN> created` (`abap_source/z_idoc_order_sync.abap:249-251`). | Success returns status and order number without the message (`python_target/order_sync/service.py:221-226`). | **(c)** | Consumers expecting the ABAP status text will not receive it. |
| The IDoc status table contains one status record per processed IDoc; no aggregate counters are returned (`abap_source/z_idoc_order_sync.abap:241-254`). | `OrderSyncBatchResult` adds total, successful, and failed counts (`python_target/order_sync/models.py:129-135`; `python_target/order_sync/service.py:256-264`). | **(b)** | Batch summaries are an added feature. They should be introduced after the equivalence phase or explicitly approved. |
| The source has only status outcomes represented by 51 and 53 in this object (`abap_source/z_idoc_order_sync.abap:146-157`, `abap_source/z_idoc_order_sync.abap:241-251`). | `OrderStatus` adds an unused `validated` state (`python_target/order_sync/models.py:17-22`). | **(b)** | The extra state has no source behavior and expands the public target contract without a migration requirement. |
| ABAP DATS values are assigned directly from the fixed segment field (`abap_source/z_idoc_order_sync.abap:276-290`). | The helper requires Python ISO date parsing, and tests provide `YYYY-MM-DD` strings (`python_target/order_sync/service.py:125-135`; `tests/test_order_sync.py:96-105`). | **(c)** | The source and target wire formats differ. A normalization boundary is required before this helper can consume exported segment values safely. |
| The ABAP function logs outcomes through IDoc status records only. | Python adds application logging for validation, success, and exceptions (`python_target/order_sync/service.py:194-239`). | **(a)** | Added observability is appropriate for the target runtime and does not need to change business results. |

## Cross-Object Validation Against Step 6

| Step 6 criterion | Assessment |
|---|---|
| All tests pass | **Not satisfied.** Collection fails on Python 3.10 at `python_target/inventory_report/service.py:15`; no test executes. |
| Every ABAP FORM/method has a corresponding Python function | **Not satisfied.** Inventory has no `fetch_inventory_data` or `display_alv` function. Order parsing FORMs are collapsed into one helper, and `set_idoc_status` has no direct function. Vendor is a function module rather than FORM-based code and has one main function. |
| Every ABAP TYPE has a corresponding Pydantic model | **Mostly satisfied.** Main business structures map to models. SAP control/status, BAPI, schedule, condition, return, and workflow structures in order sync do not have 1:1 target models because the intended API contracts are not implemented. |
| Business logic matches 1:1 | **Not satisfied.** Inventory adds summary output and variable valuation; vendor omits executable authorization and source predicates; order sync adds validation and substitutes a UUID stub for the BAPI. |
| Error handling covers all SY-SUBRC / MESSAGE paths | **Not satisfied.** Inventory warning and SALV error paths are missing; vendor authorization and error-code outputs are incomplete; order status, BAPI errors, and transaction failures are not reproduced. |
| Comments reference original ABAP | **Partially satisfied.** Models, functions, and tests name source objects and constructs, but references usually identify a FORM or concept rather than exact source lines. Several comments claim replacement behavior that is not implemented, especially middleware, database queries, target API calls, and transactions. |

## Cross-Object Quality Checklist

| Quality criterion | Assessment |
|---|---|
| Unit tests pass | **No.** Baseline collection fails. |
| PEP 8, type hints, docstrings | **Generally yes by inspection**, but no configured lint or type-check command exists. |
| No ABAP-isms in Python | **Yes in implementation style.** Source names remain in traceability comments and field descriptions as intended. |
| Pydantic validates input/output | **Partial.** Models validate local structures, but some constraints add behavior, some SAP precision/format constraints are absent, and no HTTP/queue boundary is present. |
| Clear, actionable errors | **Partial.** Local messages are readable, but several ABAP error contracts are missing and two exception classes are unused or unexercised. |
| Logging captures key business events | **Order sync only.** Inventory and vendor lookup have no logging. |
| Migration comments reference original ABAP | **Partial.** Object and FORM names appear throughout, but exact line references are uncommon and some comments overstate unimplemented integrations. |
| No hardcoded values that should be configurable | **Not satisfied.** USD, ZOR, item `000010`, unit `EA`, the inventory unit cost 10, and synthetic order-number behavior are hardcoded in target logic (`python_target/inventory_report/service.py:149-170`; `python_target/order_sync/models.py:70-90`; `python_target/order_sync/service.py:118-162`, `python_target/order_sync/service.py:267-277`). Some mirror source defaults, while others are new. |
| Performance acceptable for expected volume | **Not evidenced.** No volume targets or benchmarks exist. Vendor sorting/limiting is in memory, and inventory/order integrations are not implemented. |

## Required Sign-Off Before Claiming Functional Equivalence

1. **Inventory:** remove or separately approve the summary and variable valuation; define the
   warehouse query contract; decide how empty-result and ALV-error paths map to API responses;
   fix the supported Python runtime mismatch.
2. **Vendor:** implement and test authorization; define the target query predicates and
   company-code isolation; decide whether error responses use exceptions/HTTP statuses,
   return-code bodies, or both.
3. **Order sync:** approve or remove the added validations and defaults; define the queue
   envelope and control-record filtering; implement target payload mapping, real order
   creation, transaction behavior, and error/status mapping.
4. **All objects:** run the full 41-test suite in the supported runtime, then add equivalence
   tests for every missing source predicate, message path, status mapping, and side effect
   identified above.
