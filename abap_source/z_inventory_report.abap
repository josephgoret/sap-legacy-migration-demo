*&---------------------------------------------------------------------*
*& Report Z_INVENTORY_REPORT
*&---------------------------------------------------------------------*
*& Custom ALV report for warehouse inventory status.
*& Displays material stock levels across plants and storage locations
*& with traffic-light indicators for reorder thresholds.
*&
*& Created: 2009-03-15  Author: ACME-DEV
*& Changed: 2018-11-02  Last transport: DEVK900412
*&---------------------------------------------------------------------*
REPORT z_inventory_report.

*----------------------------------------------------------------------*
* Type Definitions
*----------------------------------------------------------------------*
TYPES: BEGIN OF ty_inventory,
         matnr        TYPE mara-matnr,        " Material number
         maktx        TYPE makt-maktx,        " Material description
         mtart        TYPE mara-mtart,        " Material type
         matkl        TYPE mara-matkl,        " Material group
         werks        TYPE marc-werks,        " Plant
         lgort        TYPE mard-lgort,        " Storage location
         labst        TYPE mard-labst,        " Unrestricted stock
         insme        TYPE mard-insme,        " Quality inspection stock
         speme        TYPE mard-speme,        " Blocked stock
         total_stock  TYPE mard-labst,        " Total stock
         minbe        TYPE marc-minbe,        " Reorder point
         mabst        TYPE marc-mabst,        " Maximum stock level
         stock_status TYPE c LENGTH 1,        " Traffic light: 1=red 2=yellow 3=green
         stock_pct    TYPE p DECIMALS 2,      " Stock level percentage
         last_receipt TYPE sy-datum,           " Last goods receipt date
         currency     TYPE waers,             " Currency
         stock_value  TYPE p DECIMALS 2,      " Stock value
       END OF ty_inventory.

TYPES: tt_inventory TYPE STANDARD TABLE OF ty_inventory WITH DEFAULT KEY.

*----------------------------------------------------------------------*
* Selection Screen
*----------------------------------------------------------------------*
SELECTION-SCREEN BEGIN OF BLOCK b01 WITH FRAME TITLE TEXT-001.
  SELECT-OPTIONS: s_werks FOR marc-werks,         " Plant
                  s_lgort FOR mard-lgort,         " Storage location
                  s_matkl FOR mara-matkl,         " Material group
                  s_mtart FOR mara-mtart.         " Material type
  PARAMETERS:     p_stale TYPE i DEFAULT 90.      " Days since last receipt
SELECTION-SCREEN END OF BLOCK b01.

SELECTION-SCREEN BEGIN OF BLOCK b02 WITH FRAME TITLE TEXT-002.
  PARAMETERS: p_red    AS CHECKBOX DEFAULT 'X',   " Show critical (red)
              p_yellow AS CHECKBOX DEFAULT 'X',   " Show warning (yellow)
              p_green  AS CHECKBOX DEFAULT ' '.   " Show healthy (green)
SELECTION-SCREEN END OF BLOCK b02.

*----------------------------------------------------------------------*
* Data Declarations
*----------------------------------------------------------------------*
DATA: gt_inventory TYPE tt_inventory,
      go_alv       TYPE REF TO cl_salv_table,
      go_columns   TYPE REF TO cl_salv_columns_table,
      go_column    TYPE REF TO cl_salv_column_table,
      go_functions TYPE REF TO cl_salv_functions_list,
      go_display   TYPE REF TO cl_salv_display_settings,
      go_sorts     TYPE REF TO cl_salv_sorts.

*----------------------------------------------------------------------*
* Start of Selection
*----------------------------------------------------------------------*
START-OF-SELECTION.

  PERFORM fetch_inventory_data.
  PERFORM calculate_stock_status.
  PERFORM filter_by_status.
  PERFORM display_alv.

*&---------------------------------------------------------------------*
*& Form FETCH_INVENTORY_DATA
*&---------------------------------------------------------------------*
FORM fetch_inventory_data.

  SELECT m~matnr
         t~maktx
         m~mtart
         m~matkl
         c~werks
         d~lgort
         d~labst
         d~insme
         d~speme
         c~minbe
         c~mabst
    INTO CORRESPONDING FIELDS OF TABLE gt_inventory
    FROM mara AS m
    INNER JOIN makt AS t ON t~matnr = m~matnr AND t~spras = sy-langu
    INNER JOIN marc AS c ON c~matnr = m~matnr
    INNER JOIN mard AS d ON d~matnr = m~matnr
                        AND d~werks = c~werks
    WHERE c~werks IN s_werks
      AND d~lgort IN s_lgort
      AND m~matkl IN s_matkl
      AND m~mtart IN s_mtart
      AND m~lvorm = ' '.    " Exclude flagged-for-deletion materials

  IF sy-subrc <> 0.
    MESSAGE 'No materials found for the given selection criteria.' TYPE 'S' DISPLAY LIKE 'W'.
    LEAVE LIST-PROCESSING.
  ENDIF.

  " Fetch last goods receipt date from material document headers
  DATA: lt_matnr TYPE RANGE OF matnr.
  LOOP AT gt_inventory ASSIGNING FIELD-SYMBOL(<fs_inv>).
    APPEND VALUE #( sign = 'I' option = 'EQ' low = <fs_inv>-matnr ) TO lt_matnr.
  ENDLOOP.
  SORT lt_matnr BY low.
  DELETE ADJACENT DUPLICATES FROM lt_matnr COMPARING low.

  " Get last receipt dates from MSEG (material document items)
  DATA: BEGIN OF ls_receipt,
          matnr TYPE matnr,
          werks TYPE werks_d,
          budat TYPE budat,
        END OF ls_receipt,
        lt_receipts LIKE STANDARD TABLE OF ls_receipt.

  SELECT g~matnr g~werks MAX( k~budat ) AS budat
    INTO TABLE lt_receipts
    FROM mseg AS g
    INNER JOIN mkpf AS k ON k~mblnr = g~mblnr AND k~mjahr = g~mjahr
    WHERE g~matnr IN lt_matnr
      AND g~bwart = '101'     " Goods receipt
    GROUP BY g~matnr g~werks.

  SORT lt_receipts BY matnr werks.

  LOOP AT gt_inventory ASSIGNING <fs_inv>.
    <fs_inv>-total_stock = <fs_inv>-labst + <fs_inv>-insme + <fs_inv>-speme.

    READ TABLE lt_receipts INTO ls_receipt
      WITH KEY matnr = <fs_inv>-matnr
               werks = <fs_inv>-werks
      BINARY SEARCH.
    IF sy-subrc = 0.
      <fs_inv>-last_receipt = ls_receipt-budat.
    ENDIF.
  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*& Form CALCULATE_STOCK_STATUS
*&---------------------------------------------------------------------*
FORM calculate_stock_status.

  DATA: lv_today TYPE sy-datum.
  lv_today = sy-datum.

  LOOP AT gt_inventory ASSIGNING FIELD-SYMBOL(<fs_inv>).
    " Calculate stock percentage relative to reorder point
    IF <fs_inv>-minbe > 0.
      <fs_inv>-stock_pct = ( <fs_inv>-labst / <fs_inv>-minbe ) * 100.
    ELSE.
      <fs_inv>-stock_pct = 100. " No reorder point = assume healthy
    ENDIF.

    " Determine traffic light status
    IF <fs_inv>-labst <= 0.
      <fs_inv>-stock_status = '1'. " Red: zero stock
    ELSEIF <fs_inv>-labst < <fs_inv>-minbe.
      <fs_inv>-stock_status = '1'. " Red: below reorder point
    ELSEIF <fs_inv>-labst < ( <fs_inv>-minbe * '1.5' ).
      <fs_inv>-stock_status = '2'. " Yellow: approaching reorder point
    ELSE.
      <fs_inv>-stock_status = '3'. " Green: healthy stock level
    ENDIF.

    " Override to red if no receipt in p_stale days
    IF <fs_inv>-last_receipt IS NOT INITIAL.
      DATA(lv_age) = lv_today - <fs_inv>-last_receipt.
      IF lv_age > p_stale AND <fs_inv>-stock_status = '3'.
        <fs_inv>-stock_status = '2'. " Downgrade: stale stock
      ENDIF.
    ENDIF.

    " Calculate stock value (simplified — would use MBEW in production)
    <fs_inv>-stock_value = <fs_inv>-total_stock * 10. " Placeholder unit cost
    <fs_inv>-currency = 'USD'.
  ENDLOOP.

ENDFORM.

*&---------------------------------------------------------------------*
*& Form FILTER_BY_STATUS
*&---------------------------------------------------------------------*
FORM filter_by_status.

  DATA: lt_filtered TYPE tt_inventory.

  LOOP AT gt_inventory INTO DATA(ls_inv).
    CASE ls_inv-stock_status.
      WHEN '1'. IF p_red   = 'X'. APPEND ls_inv TO lt_filtered. ENDIF.
      WHEN '2'. IF p_yellow = 'X'. APPEND ls_inv TO lt_filtered. ENDIF.
      WHEN '3'. IF p_green  = 'X'. APPEND ls_inv TO lt_filtered. ENDIF.
    ENDCASE.
  ENDLOOP.

  gt_inventory = lt_filtered.

  IF gt_inventory IS INITIAL.
    MESSAGE 'No materials match the selected status filters.' TYPE 'S' DISPLAY LIKE 'W'.
    LEAVE LIST-PROCESSING.
  ENDIF.

ENDFORM.

*&---------------------------------------------------------------------*
*& Form DISPLAY_ALV
*&---------------------------------------------------------------------*
FORM display_alv.

  TRY.
      cl_salv_table=>factory(
        IMPORTING r_salv_table = go_alv
        CHANGING  t_table      = gt_inventory ).

      " Enable ALV functions (sort, filter, export)
      go_functions = go_alv->get_functions( ).
      go_functions->set_all( abap_true ).

      " Configure columns
      go_columns = go_alv->get_columns( ).
      go_columns->set_optimize( abap_true ).

      go_column ?= go_columns->get_column( 'MATNR' ).
      go_column->set_long_text( 'Material' ).

      go_column ?= go_columns->get_column( 'MAKTX' ).
      go_column->set_long_text( 'Description' ).

      go_column ?= go_columns->get_column( 'WERKS' ).
      go_column->set_long_text( 'Plant' ).

      go_column ?= go_columns->get_column( 'LGORT' ).
      go_column->set_long_text( 'Stor.Loc' ).

      go_column ?= go_columns->get_column( 'LABST' ).
      go_column->set_long_text( 'Available Stock' ).

      go_column ?= go_columns->get_column( 'TOTAL_STOCK' ).
      go_column->set_long_text( 'Total Stock' ).

      go_column ?= go_columns->get_column( 'MINBE' ).
      go_column->set_long_text( 'Reorder Point' ).

      go_column ?= go_columns->get_column( 'STOCK_STATUS' ).
      go_column->set_long_text( 'Status' ).

      go_column ?= go_columns->get_column( 'STOCK_PCT' ).
      go_column->set_long_text( 'Stock %' ).

      go_column ?= go_columns->get_column( 'LAST_RECEIPT' ).
      go_column->set_long_text( 'Last Receipt' ).

      go_column ?= go_columns->get_column( 'STOCK_VALUE' ).
      go_column->set_long_text( 'Stock Value' ).

      " Set up sorting
      go_sorts = go_alv->get_sorts( ).
      go_sorts->add_sort( columnname = 'STOCK_STATUS' position = 1 sequence = if_salv_c_sort=>sort_up ).
      go_sorts->add_sort( columnname = 'WERKS'        position = 2 sequence = if_salv_c_sort=>sort_up ).

      " Display settings
      go_display = go_alv->get_display_settings( ).
      go_display->set_striped_pattern( abap_true ).
      go_display->set_list_header( 'Warehouse Inventory Status Report' ).

      go_alv->display( ).

    CATCH cx_salv_msg cx_salv_not_found cx_salv_data_error INTO DATA(lx_error).
      MESSAGE lx_error->get_text( ) TYPE 'E'.
  ENDTRY.

ENDFORM.
