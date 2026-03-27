*&---------------------------------------------------------------------*
*& Function Module Z_IDOC_ORDER_SYNC
*&---------------------------------------------------------------------*
*& Processes inbound ORDERS05 IDocs to create or update sales orders.
*& Called by SAP IDoc framework during EDI processing.
*& Maps IDoc segments to BAPI_SALESORDER_CREATEFROMDAT2 parameters.
*&
*& Created: 2013-09-08  Author: ACME-DEV
*& Changed: 2021-04-22  Last transport: DEVK901388
*&---------------------------------------------------------------------*
FUNCTION z_idoc_order_sync.
*"----------------------------------------------------------------------
*"*"Local Interface:
*"  IMPORTING
*"     VALUE(INPUT_METHOD)  TYPE BDWFAP_PAR-INPUTMETHD
*"     VALUE(MASS_PROCESSING) TYPE BDWFAP_PAR-MASS_PROC
*"  EXPORTING
*"     VALUE(WORKFLOW_RESULT) TYPE BDWFAP_PAR-RESULT
*"     VALUE(APPLICATION_VARIABLE) TYPE BDWFAP_PAR-APPL_VAR
*"  TABLES
*"     IDOC_CONTRL STRUCTURE EDIDC
*"     IDOC_DATA   STRUCTURE EDIDD
*"     IDOC_STATUS STRUCTURE BDIDOCSTAT
*"     RETURN_VARIABLES STRUCTURE BDWFRETVAR
*"----------------------------------------------------------------------

* Type definitions for order mapping
  TYPES: BEGIN OF ty_order_header,
           doc_type    TYPE bsad-auart,      " Sales document type
           sales_org   TYPE vkorg,           " Sales organization
           distr_chan  TYPE vtweg,           " Distribution channel
           division    TYPE spart,           " Division
           sold_to     TYPE kunag,           " Sold-to party
           ship_to     TYPE kunwe,           " Ship-to party
           po_number   TYPE bstkd,           " Customer PO number
           po_date     TYPE bstdk,           " Customer PO date
           req_dlv_date TYPE vdatu,          " Requested delivery date
           price_date  TYPE prsdt,           " Pricing date
           currency    TYPE waerk,           " Document currency
           incoterms1  TYPE inco1,           " Incoterms part 1
           incoterms2  TYPE inco2,           " Incoterms part 2
         END OF ty_order_header.

  TYPES: BEGIN OF ty_order_item,
           itm_number  TYPE posnr,           " Item number
           material    TYPE matnr,           " Material number
           plant       TYPE werks_d,         " Plant
           quantity    TYPE kwmeng,          " Order quantity
           uom         TYPE vrkme,           " Unit of measure
           net_price   TYPE netpr,           " Net price
           cust_mat    TYPE kdmat,           " Customer material number
           item_categ  TYPE pstyv,           " Item category
         END OF ty_order_item,
         tt_order_items TYPE STANDARD TABLE OF ty_order_item WITH DEFAULT KEY.

  DATA: ls_header     TYPE ty_order_header,
        lt_items      TYPE tt_order_items,
        lv_vbeln      TYPE vbeln,
        lv_idoc_num   TYPE edi_docnum,
        ls_idoc_ctrl  TYPE edidc,
        ls_idoc_data  TYPE edidd,
        ls_status     TYPE bdidocstat,
        lv_segment    TYPE edilsegtyp.

* BAPI structures
  DATA: ls_order_header_in  TYPE bapisdhd1,
        ls_order_header_inx TYPE bapisdhd1x,
        lt_order_items_in   TYPE TABLE OF bapisditm,
        lt_order_items_inx  TYPE TABLE OF bapisditm,
        lt_order_partners   TYPE TABLE OF bapiparnr,
        lt_order_schedules  TYPE TABLE OF bapischdl,
        lt_order_conditions TYPE TABLE OF bapicond,
        lt_return           TYPE TABLE OF bapiret2.

  workflow_result = 0. " Initialize to success

*----------------------------------------------------------------------*
* Process each IDoc in the control table
*----------------------------------------------------------------------*
  LOOP AT idoc_contrl INTO ls_idoc_ctrl
    WHERE mestyp = 'ORDERS'
      AND status = '64'.           " IDoc ready to be transferred

    lv_idoc_num = ls_idoc_ctrl-docnum.
    CLEAR: ls_header, lt_items, ls_order_header_in, lt_order_items_in,
           lt_order_partners, lt_order_schedules, lt_return.

*----------------------------------------------------------------------*
*   Parse IDoc Segments
*----------------------------------------------------------------------*
    LOOP AT idoc_data INTO ls_idoc_data
      WHERE docnum = lv_idoc_num.

      lv_segment = ls_idoc_data-segnam.

      CASE lv_segment.

*       --- Order Header (E1EDK01) ---
        WHEN 'E1EDK01'.
          PERFORM parse_header_segment
            USING    ls_idoc_data-sdata
            CHANGING ls_header.

*       --- Header Date Segments (E1EDK03) ---
        WHEN 'E1EDK03'.
          PERFORM parse_date_segment
            USING    ls_idoc_data-sdata
            CHANGING ls_header.

*       --- Header Partner (E1EDKA1) ---
        WHEN 'E1EDKA1'.
          DATA: ls_partner TYPE bapiparnr.
          PERFORM parse_partner_segment
            USING    ls_idoc_data-sdata
            CHANGING ls_header
                     ls_partner.
          IF ls_partner IS NOT INITIAL.
            APPEND ls_partner TO lt_order_partners.
          ENDIF.

*       --- Order Item (E1EDP01) ---
        WHEN 'E1EDP01'.
          DATA: ls_item TYPE ty_order_item.
          PERFORM parse_item_segment
            USING    ls_idoc_data-sdata
            CHANGING ls_item.
          IF ls_item IS NOT INITIAL.
            APPEND ls_item TO lt_items.
          ENDIF.

*       --- Item Material Info (E1EDP19) ---
        WHEN 'E1EDP19'.
          IF lt_items IS NOT INITIAL.
            DATA(lv_last_idx) = lines( lt_items ).
            PERFORM parse_item_material_segment
              USING    ls_idoc_data-sdata
              CHANGING lt_items[ lv_last_idx ].
          ENDIF.

      ENDCASE.
    ENDLOOP.

*----------------------------------------------------------------------*
*   Validate Parsed Data
*----------------------------------------------------------------------*
    IF ls_header-sold_to IS INITIAL.
      PERFORM set_idoc_status
        USING    lv_idoc_num '51' 'E' 'Missing sold-to party in IDoc'
        CHANGING idoc_status.
      CONTINUE.
    ENDIF.

    IF lt_items IS INITIAL.
      PERFORM set_idoc_status
        USING    lv_idoc_num '51' 'E' 'No order items found in IDoc'
        CHANGING idoc_status.
      CONTINUE.
    ENDIF.

*----------------------------------------------------------------------*
*   Map to BAPI Structures
*----------------------------------------------------------------------*

    " Header mapping
    ls_order_header_in-doc_type   = ls_header-doc_type.
    IF ls_order_header_in-doc_type IS INITIAL.
      ls_order_header_in-doc_type = 'ZOR'.  " Default: standard order
    ENDIF.
    ls_order_header_in-sales_org  = ls_header-sales_org.
    ls_order_header_in-distr_chan = ls_header-distr_chan.
    ls_order_header_in-division   = ls_header-division.
    ls_order_header_in-purch_no   = ls_header-po_number.
    ls_order_header_in-purch_date = ls_header-po_date.
    ls_order_header_in-req_date_h = ls_header-req_dlv_date.
    ls_order_header_in-price_date = ls_header-price_date.
    ls_order_header_in-currency   = ls_header-currency.
    ls_order_header_in-incoterms1 = ls_header-incoterms1.
    ls_order_header_in-incoterms2 = ls_header-incoterms2.

    ls_order_header_inx-doc_type   = 'X'.
    ls_order_header_inx-sales_org  = 'X'.
    ls_order_header_inx-distr_chan = 'X'.
    ls_order_header_inx-division   = 'X'.
    ls_order_header_inx-purch_no   = 'X'.
    ls_order_header_inx-updateflag = 'I'.  " Insert

    " Item mapping
    LOOP AT lt_items INTO DATA(ls_itm).
      DATA: ls_bapi_item TYPE bapisditm,
            ls_schedule  TYPE bapischdl.

      ls_bapi_item-itm_number = ls_itm-itm_number.
      ls_bapi_item-material   = ls_itm-material.
      ls_bapi_item-plant      = ls_itm-plant.
      ls_bapi_item-target_qty = ls_itm-quantity.
      ls_bapi_item-target_qu  = ls_itm-uom.
      ls_bapi_item-cust_mat35 = ls_itm-cust_mat.
      ls_bapi_item-item_categ = ls_itm-item_categ.
      APPEND ls_bapi_item TO lt_order_items_in.

      " Schedule line
      ls_schedule-itm_number  = ls_itm-itm_number.
      ls_schedule-sched_line  = '0001'.
      ls_schedule-req_date    = ls_header-req_dlv_date.
      ls_schedule-req_qty     = ls_itm-quantity.
      APPEND ls_schedule TO lt_order_schedules.
    ENDLOOP.

*----------------------------------------------------------------------*
*   Create Sales Order via BAPI
*----------------------------------------------------------------------*
    CALL FUNCTION 'BAPI_SALESORDER_CREATEFROMDAT2'
      EXPORTING
        order_header_in  = ls_order_header_in
        order_header_inx = ls_order_header_inx
      IMPORTING
        salesdocument    = lv_vbeln
      TABLES
        return                = lt_return
        order_items_in        = lt_order_items_in
        order_partners        = lt_order_partners
        order_schedules_in    = lt_order_schedules
        order_conditions_in   = lt_order_conditions.

    " Check BAPI return for errors
    DATA(lv_has_error) = abap_false.
    LOOP AT lt_return INTO DATA(ls_ret) WHERE type CA 'EA'.
      lv_has_error = abap_true.
      EXIT.
    ENDLOOP.

    IF lv_has_error = abap_true.
      " Rollback
      CALL FUNCTION 'BAPI_TRANSACTION_ROLLBACK'.

      DATA(lv_err_msg) = REDUCE string(
        INIT msg = ||
        FOR wa IN lt_return WHERE ( type CA 'EA' )
        NEXT msg = |{ msg }{ wa-message }; | ).

      PERFORM set_idoc_status
        USING    lv_idoc_num '51' 'E' lv_err_msg
        CHANGING idoc_status.
    ELSE.
      " Commit
      CALL FUNCTION 'BAPI_TRANSACTION_COMMIT'
        EXPORTING wait = 'X'.

      PERFORM set_idoc_status
        USING    lv_idoc_num '53' 'S' |Sales order { lv_vbeln } created|
        CHANGING idoc_status.
    ENDIF.

  ENDLOOP.  " End IDoc loop

ENDFUNCTION.

*&---------------------------------------------------------------------*
*& Form PARSE_HEADER_SEGMENT
*&---------------------------------------------------------------------*
FORM parse_header_segment
  USING    iv_sdata TYPE edidd-sdata
  CHANGING cs_header TYPE ty_order_header.

  DATA: ls_e1edk01 TYPE e1edk01.
  ls_e1edk01 = iv_sdata.

  cs_header-doc_type  = ls_e1edk01-bsart.
  cs_header-currency  = ls_e1edk01-curcy.

ENDFORM.

*&---------------------------------------------------------------------*
*& Form PARSE_DATE_SEGMENT
*&---------------------------------------------------------------------*
FORM parse_date_segment
  USING    iv_sdata TYPE edidd-sdata
  CHANGING cs_header TYPE ty_order_header.

  DATA: ls_e1edk03 TYPE e1edk03.
  ls_e1edk03 = iv_sdata.

  CASE ls_e1edk03-iddat.
    WHEN '012'.  " Requested delivery date
      cs_header-req_dlv_date = ls_e1edk03-datum.
    WHEN '022'.  " Customer PO date
      cs_header-po_date = ls_e1edk03-datum.
    WHEN '026'.  " Pricing date
      cs_header-price_date = ls_e1edk03-datum.
  ENDCASE.

ENDFORM.

*&---------------------------------------------------------------------*
*& Form PARSE_PARTNER_SEGMENT
*&---------------------------------------------------------------------*
FORM parse_partner_segment
  USING    iv_sdata   TYPE edidd-sdata
  CHANGING cs_header  TYPE ty_order_header
           cs_partner TYPE bapiparnr.

  DATA: ls_e1edka1 TYPE e1edka1.
  ls_e1edka1 = iv_sdata.

  CLEAR cs_partner.

  CASE ls_e1edka1-parvw.
    WHEN 'AG'.  " Sold-to
      cs_header-sold_to = ls_e1edka1-partn.
      cs_partner-partn_role = 'AG'.
      cs_partner-partn_numb = ls_e1edka1-partn.
    WHEN 'WE'.  " Ship-to
      cs_header-ship_to = ls_e1edka1-partn.
      cs_partner-partn_role = 'WE'.
      cs_partner-partn_numb = ls_e1edka1-partn.
    WHEN 'RE'.  " Bill-to
      cs_partner-partn_role = 'RE'.
      cs_partner-partn_numb = ls_e1edka1-partn.
    WHEN 'RG'.  " Payer
      cs_partner-partn_role = 'RG'.
      cs_partner-partn_numb = ls_e1edka1-partn.
  ENDCASE.

ENDFORM.

*&---------------------------------------------------------------------*
*& Form PARSE_ITEM_SEGMENT
*&---------------------------------------------------------------------*
FORM parse_item_segment
  USING    iv_sdata TYPE edidd-sdata
  CHANGING cs_item  TYPE ty_order_item.

  DATA: ls_e1edp01 TYPE e1edp01.
  ls_e1edp01 = iv_sdata.

  CLEAR cs_item.
  cs_item-itm_number = ls_e1edp01-posex.
  cs_item-quantity   = ls_e1edp01-menge.
  cs_item-uom        = ls_e1edp01-menee.
  cs_item-net_price  = ls_e1edp01-vprei.
  cs_item-item_categ = ls_e1edp01-pstyv.

ENDFORM.

*&---------------------------------------------------------------------*
*& Form PARSE_ITEM_MATERIAL_SEGMENT
*&---------------------------------------------------------------------*
FORM parse_item_material_segment
  USING    iv_sdata TYPE edidd-sdata
  CHANGING cs_item  TYPE ty_order_item.

  DATA: ls_e1edp19 TYPE e1edp19.
  ls_e1edp19 = iv_sdata.

  CASE ls_e1edp19-qualf.
    WHEN '002'.  " Vendor material number / SAP material
      cs_item-material = ls_e1edp19-idtnr.
    WHEN '003'.  " Customer material number
      cs_item-cust_mat = ls_e1edp19-idtnr.
  ENDCASE.

ENDFORM.

*&---------------------------------------------------------------------*
*& Form SET_IDOC_STATUS
*&---------------------------------------------------------------------*
FORM set_idoc_status
  USING    iv_docnum TYPE edi_docnum
           iv_status TYPE edi_status
           iv_msgty  TYPE symsgty
           iv_msgv1  TYPE string
  CHANGING ct_status TYPE bdidocstat_tab.

  DATA: ls_status TYPE bdidocstat.

  ls_status-docnum = iv_docnum.
  ls_status-status = iv_status.
  ls_status-msgty  = iv_msgty.
  ls_status-msgv1  = iv_msgv1(50).    " Truncate to field length
  IF strlen( iv_msgv1 ) > 50.
    ls_status-msgv2 = iv_msgv1+50(50).
  ENDIF.
  APPEND ls_status TO ct_status.

ENDFORM.
