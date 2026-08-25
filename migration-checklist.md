# SAP ABAP → Python Migration Checklist

> **Purpose**: Working checklist for a single ABAP object, consolidated from
> [`migration-playbook.md`](migration-playbook.md) and [`README.md`](README.md).
> Copy this file per object and tick items as you go.

---

## Phase 0: Pre-Migration

Before starting migration of any ABAP object:

- [ ] Source ABAP code is exported and accessible
- [ ] Business owner has confirmed the object is still in use
- [ ] Target architecture is defined (API framework, database, deployment)
- [ ] Data dictionary dependencies are mapped (which SAP tables are read/written)
- [ ] Test data is available (sample inputs and expected outputs)
- [ ] Acceptance criteria defined (functional equivalence tests)

---

## Phase 1: Analyze the ABAP Source

Read the ABAP program and document each of these in a structured format **before** writing any Python code:

- [ ] **Input parameters**: selection screen fields, function module imports, IDoc segments
- [ ] **Data sources**: SAP tables accessed (MARA, EKKO, VBAK, etc.) and their joins
- [ ] **Business logic**: calculations, validations, status determinations, conditional flows
- [ ] **Output format**: ALV grid, RFC exports, IDoc status, file output
- [ ] **Dependencies**: called function modules, BAPIs, includes, macros
- [ ] **Error handling**: SY-SUBRC checks, exception handling, message types

---

## Phase 2: Design & Data Models

Map each ABAP component to its Python equivalent, then build the models.

**Design**

- [ ] Selection screen → API query parameters / request body
- [ ] TYPE definitions → Pydantic `BaseModel`s
- [ ] INTERNAL TABLEs → `list[Model]`
- [ ] FIELD-SYMBOLs → loop variables / list comprehensions
- [ ] `SELECT ... INTO TABLE` → SQL query → DataFrame or ORM query
- [ ] AUTHORITY-CHECK → JWT / API key middleware
- [ ] SY-SUBRC checks → exception handling / if-else
- [ ] `MESSAGE TYPE 'E'` → `HTTPException` / raise
- [ ] ALV display → JSON response
- [ ] RFC interface → REST/GraphQL endpoint
- [ ] IDoc processing → message queue consumer
- [ ] BAPI call → target system API call
- [ ] `COMMIT WORK` / `ROLLBACK WORK` → database transaction commit / rollback

**Data models**

- [ ] One model per ABAP structure/table type
- [ ] `Field` descriptions map to the SAP field names (MATNR, MAKTX, LABST, …)
- [ ] Python-native types used (`Decimal` for quantities/amounts, `date` for DATS)
- [ ] Docstrings reference the source ABAP type name

---

## Phase 3: Implement Business Logic

**Functional equivalence only — do NOT improve/optimize here.** Anything that changes behaviour, output shape beyond the interface mapping, or performance characteristics belongs in [Phase 7](#when-to-improve-functionality).

- [ ] Each ABAP `FORM` or method → one Python function
- [ ] Function names preserved (converted to snake_case)
- [ ] Comments map back to the ABAP logic for traceability
- [ ] Control flow structure kept the same where possible
- [ ] No "improvements" to the business logic — equivalence, not optimization

---

## Phase 4: Equivalence Tests

For each migrated function, write tests that verify:

- [ ] **Happy path**: same input → same output as ABAP
- [ ] **Edge cases**: empty tables, zero values, null/initial fields
- [ ] **Boundary conditions**: threshold values (e.g. stock = reorder point exactly)
- [ ] **Error cases**: invalid input → same error behaviour as ABAP
- [ ] Test names follow `test_<function_name>_<scenario>()` with a docstring referencing the original ABAP logic

---

## Phase 5: Validate & Review

- [ ] All tests pass
- [ ] Every ABAP FORM/method has a corresponding Python function
- [ ] Every ABAP TYPE has a corresponding Pydantic model
- [ ] Business logic matches 1:1 (no accidental "improvements")
- [ ] Error handling covers all ABAP SY-SUBRC / MESSAGE paths
- [ ] Comments reference original ABAP code for traceability

---

## Phase 6: Quality Gate (Definition of Done)

Before marking any migrated object as complete:

- [ ] All unit tests pass
- [ ] Code follows project style guide (PEP 8, type hints, docstrings)
- [ ] No ABAP-isms in Python (e.g. SY-SUBRC patterns, INITIAL checks)
- [ ] Pydantic models validate input/output correctly
- [ ] Error messages are clear and actionable
- [ ] Logging captures key business events
- [ ] Migration comments reference original ABAP line/form names
- [ ] No hardcoded values that should be configurable
- [ ] Performance is acceptable for expected data volumes

---

## When to improve functionality

The playbook is explicit about this ([`migration-playbook.md`](migration-playbook.md), Step 4): do **not** improve the business logic while migrating. The goal is functional equivalence; optimizations come in a separate phase **after** the migration is validated. Phases 0–6 above therefore contain no improvement work at all.

### Phase 7: Post-Validation Improvements

Opens only once Phase 5 and Phase 6 are signed off for the object. This is the window for:

- [ ] Performance tuning (query optimization, caching, batching, indexing)
- [ ] Refactoring (splitting oversized functions, removing translated-in duplication, tightening types)
- [ ] Feature additions (new aggregations, new filters, new endpoints)
- [ ] Re-running the Phase 4 equivalence tests to confirm which behaviour changes are intentional, and updating them deliberately when they are

### Known deviation in this demo

The inventory report migration ([`README.md`](README.md), "The Four Migrations") added **an aggregated summary the original ABAP report didn't have**. That is a functional improvement made during migration, and it contradicts strict equivalence — by the rule above it belongs in Phase 7. In a real migration this would need to be a deliberate, recorded decision (business owner sign-off, and equivalence tests that state the summary is an intentional addition) rather than something that slips in while translating.

### Interface modernization vs. functional improvement

The Step 2 mapping table forces some constructs to change shape because the target platform has no equivalent. Those are **equivalence-preserving** and belong in the migration phases, not Phase 7:

| Equivalence-preserving (Phases 2–3) | True improvement (Phase 7) |
|---|---|
| AUTHORITY-CHECK → auth middleware / typed exception | Adding new roles or finer-grained permissions |
| `COMMIT WORK` / `ROLLBACK WORK` → DB transactions | Changing the transaction boundaries or retry behaviour |
| ALV grid → JSON response | Adding fields or aggregates the ALV never produced |
| RFC / IDoc interface → REST endpoint / queue consumer | Adding new operations or payload semantics |
| `MESSAGE TYPE 'E'` → `HTTPException` | Rewording or restructuring the error contract |

Rule of thumb: if the same inputs still produce the same business outcomes and only the delivery mechanism changed, it is modernization. If a caller can observe a new or different result, it is an improvement — defer it to Phase 7.
