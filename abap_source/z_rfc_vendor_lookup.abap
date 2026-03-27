*&---------------------------------------------------------------------*
*& Function Module Z_RFC_VENDOR_LOOKUP
*&---------------------------------------------------------------------*
*& RFC-enabled function module for vendor master data lookup.
*& Returns vendor details and recent purchase order history.
*& Called by external procurement portal and EDI middleware.
*&
*& Created: 2011-06-20  Author: ACME-DEV
*& Changed: 2020-01-14  Last transport: DEVK901055
*&---------------------------------------------------------------------*
FUNCTION z_rfc_vendor_lookup.
*"----------------------------------------------------------------------
*"*"Local Interface:
*"  IMPORTING
*"     VALUE(IV_LIFNR)      TYPE LIFNR                " Vendor number
*"     VALUE(IV_BUKRS)      TYPE BUKRS DEFAULT '1000'  " Company code
*"     VALUE(IV_MAX_POS)    TYPE I DEFAULT 50           " Max PO items
*"     VALUE(IV_DATE_FROM)  TYPE SY-DATUM OPTIONAL     " PO date range start
*"  EXPORTING
*"     VALUE(ES_VENDOR)     TYPE ZS_VENDOR_DETAIL      " Vendor detail structure
*"     VALUE(ET_PO_HISTORY) TYPE ZTT_PO_HISTORY        " PO history table
*"     VALUE(EV_RETURN_CODE) TYPE I                    " 0=OK, 1=not found, 2=error
*"     VALUE(EV_RETURN_MSG)  TYPE STRING               " Return message
*"  EXCEPTIONS
*"     VENDOR_NOT_FOUND
*"     AUTHORIZATION_FAILED
*"----------------------------------------------------------------------

* Type definitions (normally in data dictionary)
  TYPES: BEGIN OF ty_vendor_detail,
           lifnr     TYPE lfa1-lifnr,       " Vendor number
           name1     TYPE lfa1-name1,        " Name 1
           name2     TYPE lfa1-name2,        " Name 2
           stras     TYPE lfa1-stras,        " Street
           ort01     TYPE lfa1-ort01,        " City
           regio     TYPE lfa1-regio,        " Region
           pstlz     TYPE lfa1-pstlz,        " Postal code
           land1     TYPE lfa1-land1,        " Country
           telf1     TYPE lfa1-telf1,        " Phone
           telfx     TYPE lfa1-telfx,        " Fax
           smtp_addr TYPE adr6-smtp_addr,    " Email
           ktokk     TYPE lfa1-ktokk,        " Account group
           zterm     TYPE lfb1-zterm,        " Payment terms
           akont     TYPE lfb1-akont,        " Reconciliation account
           waers     TYPE lfb1-waers,        " Currency
           sperr     TYPE lfa1-sperr,        " Central block
           loevm     TYPE lfa1-loevm,        " Deletion flag
           total_po_value TYPE p LENGTH 15 DECIMALS 2,
           open_po_count  TYPE i,
         END OF ty_vendor_detail.

  TYPES: BEGIN OF ty_po_history,
           ebeln     TYPE ekko-ebeln,        " PO number
           ebelp     TYPE ekpo-ebelp,        " PO item
           bedat     TYPE ekko-bedat,        " PO date
           matnr     TYPE ekpo-matnr,        " Material number
           txz01     TYPE ekpo-txz01,        " Short text
           menge     TYPE ekpo-menge,        " Quantity
           meins     TYPE ekpo-meins,        " Unit of measure
           netpr     TYPE ekpo-netpr,        " Net price
           waers     TYPE ekko-waers,        " Currency
           elikz     TYPE ekpo-elikz,        " Delivery completed
           banfn     TYPE ekpo-banfn,        " Purchase requisition
         END OF ty_po_history,
         tt_po_history TYPE STANDARD TABLE OF ty_po_history WITH DEFAULT KEY.

  DATA: ls_vendor  TYPE ty_vendor_detail,
        lt_po_hist TYPE tt_po_history,
        lv_date_from TYPE sy-datum.

* Initialize
  CLEAR: es_vendor, et_po_history, ev_return_code, ev_return_msg.

*----------------------------------------------------------------------*
* Authorization Check
*----------------------------------------------------------------------*
  AUTHORITY-CHECK OBJECT 'F_LFA1_BUK'
    ID 'BUKRS' FIELD iv_bukrs
    ID 'ACTVT' FIELD '03'.    " Display activity

  IF sy-subrc <> 0.
    ev_return_code = 2.
    ev_return_msg = |Authorization failed for company code { iv_bukrs }|.
    RAISE authorization_failed.
  ENDIF.

*----------------------------------------------------------------------*
* Fetch Vendor Master Data
*----------------------------------------------------------------------*
  SELECT SINGLE a~lifnr a~name1 a~name2
                a~stras a~ort01 a~regio a~pstlz a~land1
                a~telf1 a~telfx a~ktokk a~sperr a~loevm
    INTO CORRESPONDING FIELDS OF ls_vendor
    FROM lfa1 AS a
    WHERE a~lifnr = iv_lifnr.

  IF sy-subrc <> 0.
    ev_return_code = 1.
    ev_return_msg = |Vendor { iv_lifnr } not found|.
    RAISE vendor_not_found.
  ENDIF.

* Company code data
  SELECT SINGLE zterm akont waers
    INTO CORRESPONDING FIELDS OF ls_vendor
    FROM lfb1
    WHERE lifnr = iv_lifnr
      AND bukrs = iv_bukrs.

* Email address
  SELECT SINGLE b~smtp_addr
    INTO ls_vendor-smtp_addr
    FROM lfa1 AS a
    INNER JOIN adr6 AS b ON b~addrnumber = a~adrnr
                        AND b~flgdefault = 'X'
    WHERE a~lifnr = iv_lifnr.

*----------------------------------------------------------------------*
* Fetch Purchase Order History
*----------------------------------------------------------------------*
  IF iv_date_from IS INITIAL.
    lv_date_from = sy-datum - 365.  " Default: last 12 months
  ELSE.
    lv_date_from = iv_date_from.
  ENDIF.

  SELECT h~ebeln p~ebelp h~bedat
         p~matnr p~txz01 p~menge p~meins
         p~netpr h~waers p~elikz p~banfn
    INTO TABLE lt_po_hist
    FROM ekko AS h
    INNER JOIN ekpo AS p ON p~ebeln = h~ebeln
    WHERE h~lifnr = iv_lifnr
      AND h~bukrs = iv_bukrs
      AND h~bedat >= lv_date_from
      AND h~loekz = ' '          " Not deleted
      AND p~loekz = ' '          " Item not deleted
    ORDER BY h~bedat DESCENDING
    UP TO iv_max_pos ROWS.

* Calculate aggregates
  DATA: lv_total TYPE p LENGTH 15 DECIMALS 2,
        lv_open  TYPE i.

  LOOP AT lt_po_hist INTO DATA(ls_po).
    lv_total = lv_total + ( ls_po-netpr * ls_po-menge ).
    IF ls_po-elikz = ' '.
      lv_open = lv_open + 1.
    ENDIF.
  ENDLOOP.

  ls_vendor-total_po_value = lv_total.
  ls_vendor-open_po_count  = lv_open.

*----------------------------------------------------------------------*
* Return Results
*----------------------------------------------------------------------*
  es_vendor     = ls_vendor.
  et_po_history = lt_po_hist.
  ev_return_code = 0.
  ev_return_msg = |Vendor { iv_lifnr } retrieved successfully. { lines( lt_po_hist ) } PO items returned.|.

ENDFUNCTION.
