# Pre-Migration Prerequisites Checklist

Expands the **Pre-Migration Checklist** in [migration-playbook.md](migration-playbook.md) with scope
confirmation and per-object analysis prerequisites. Work through this before writing any Python for
an ABAP object.

---

## 1. Source & ownership

- [ ] Source ABAP code is exported and accessible
- [ ] Business owner has confirmed the object is still in use

## 2. Target definition

- [ ] Target architecture is defined (API framework, database, deployment)

## 3. Dependencies & data

- [ ] Data dictionary dependencies are mapped (which SAP tables are read/written)
- [ ] Test data is available (sample inputs and expected outputs)

## 4. Acceptance

- [ ] Acceptance criteria defined (functional equivalence tests)

## 5. Scope confirmation (in vs. out)

Confirm the object falls into code-based migration scope — ALV reports, RFC function modules, IDoc
processing functions, BAdI implementations, SAPscript/Smart Forms — and is not one of the
out-of-scope items that need SAP functional consultants:

- [ ] Not IMG configuration / customizing
- [ ] Not pricing procedures, output determination, workflow rules, or authorization role design

## 6. Analysis inputs gathered (per object)

Document these from the ABAP source before writing Python:

- [ ] Input parameters (selection screen fields, function module imports, IDoc segments)
- [ ] Data sources (SAP tables accessed and their joins)
- [ ] Business logic (calculations, validations, status determinations, conditional flows)
- [ ] Output format (ALV grid, RFC exports, IDoc status, file output)
- [ ] Dependencies (called function modules, BAPIs, includes, macros)
- [ ] Error handling (SY-SUBRC checks, exception handling, message types)
