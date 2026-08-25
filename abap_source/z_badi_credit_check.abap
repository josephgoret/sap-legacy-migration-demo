*&---------------------------------------------------------------------*
*& BAdI Implementation ZCL_IM_ORDER_CREDIT_CHECK
*&---------------------------------------------------------------------*
*& Custom credit limit check executed when a sales order is saved.
*& Implements BAdI ZBADI_ORDER_CREDIT (enhancement spot ZES_SD_ORDER),
*& method CHECK_CREDIT. Called from user exit USEREXIT_SAVE_DOCUMENT.
*&
*& Business rules (per Acme Retail finance policy FIN-2009-07):
*&   - Exposure = open receivables + special liability + open orders
*&                + open deliveries + the order currently being saved
*&   - Risk category drives the tolerance granted above the credit limit
*&     and the number of overdue days tolerated
*&   - Blocked customers and customers without a credit master record
*&     are always blocked
*&
*& Created: 2009-09-03  Author: ACME-DEV
*& Changed: 2018-11-22  Last transport: DEVK901042
*&---------------------------------------------------------------------*
CLASS zcl_im_order_credit_check DEFINITION PUBLIC FINAL CREATE PUBLIC.

  PUBLIC SECTION.
    INTERFACES zif_ex_badi_order_credit.

  PRIVATE SECTION.
*   Credit master data (KNKK) plus derived aggregates
    TYPES: BEGIN OF ty_credit_master,
             kunnr  TYPE knkk-kunnr,        " Customer number
             kkber  TYPE knkk-kkber,        " Credit control area
             klimk  TYPE knkk-klimk,        " Credit limit
             skfor  TYPE knkk-skfor,        " Open receivables
             ssobl  TYPE knkk-ssobl,        " Special liability
             ctlpc  TYPE knkk-ctlpc,        " Risk category
             crblb  TYPE knkk-crblb,        " Credit block flag
             waers  TYPE knkk-waers,        " Credit limit currency
           END OF ty_credit_master.

    TYPES: BEGIN OF ty_exposure,
             open_order_value    TYPE p LENGTH 15 DECIMALS 2,
             open_delivery_value TYPE p LENGTH 15 DECIMALS 2,
             overdue_amount      TYPE p LENGTH 15 DECIMALS 2,
             overdue_days        TYPE i,
           END OF ty_exposure.

    TYPES: BEGIN OF ty_check_result,
             status         TYPE c LENGTH 1,   " P=pass, W=warn, B=block
             reason_code    TYPE c LENGTH 20,
             message_type   TYPE c LENGTH 1,   " S / W / E
             message_text   TYPE string,
             total_exposure TYPE p LENGTH 15 DECIMALS 2,
             effective_limit TYPE p LENGTH 15 DECIMALS 2,
             utilization_pct TYPE p LENGTH 7 DECIMALS 2,
             delivery_block TYPE vbak-lifsk,
           END OF ty_check_result.

    METHODS get_limit_tolerance
      IMPORTING iv_ctlpc         TYPE knkk-ctlpc
      RETURNING VALUE(rv_pct)    TYPE p LENGTH 5 DECIMALS 2.

    METHODS get_overdue_tolerance
      IMPORTING iv_ctlpc         TYPE knkk-ctlpc
      RETURNING VALUE(rv_days)   TYPE i.

    METHODS calculate_exposure
      IMPORTING is_credit        TYPE ty_credit_master
                is_open          TYPE ty_exposure
                iv_order_value   TYPE p
      RETURNING VALUE(rv_total)  TYPE p LENGTH 15 DECIMALS 2.

ENDCLASS.


CLASS zcl_im_order_credit_check IMPLEMENTATION.

*----------------------------------------------------------------------*
* Tolerance granted above the credit limit, by risk category
*----------------------------------------------------------------------*
  METHOD get_limit_tolerance.
    CASE iv_ctlpc.
      WHEN '001'.        " Low risk — 10% tolerance
        rv_pct = '10.00'.
      WHEN '002'.        " Medium risk — 5% tolerance
        rv_pct = '5.00'.
      WHEN '003'.        " High risk — no tolerance
        rv_pct = '0.00'.
      WHEN OTHERS.       " Unknown category treated as high risk
        rv_pct = '0.00'.
    ENDCASE.
  ENDMETHOD.

*----------------------------------------------------------------------*
* Overdue days tolerated before the order is blocked, by risk category
*----------------------------------------------------------------------*
  METHOD get_overdue_tolerance.
    CASE iv_ctlpc.
      WHEN '001'.
        rv_days = 30.
      WHEN '002'.
        rv_days = 15.
      WHEN '003'.
        rv_days = 0.
      WHEN OTHERS.
        rv_days = 0.
    ENDCASE.
  ENDMETHOD.

*----------------------------------------------------------------------*
* Total credit exposure including the order being saved
*----------------------------------------------------------------------*
  METHOD calculate_exposure.
    rv_total = is_credit-skfor
             + is_credit-ssobl
             + is_open-open_order_value
             + is_open-open_delivery_value
             + iv_order_value.
  ENDMETHOD.

*----------------------------------------------------------------------*
* BAdI method — main credit check
*----------------------------------------------------------------------*
  METHOD zif_ex_badi_order_credit~check_credit.
*   IMPORTING iv_kunnr       TYPE kunnr
*             iv_kkber       TYPE kkber
*             iv_vkorg       TYPE vkorg
*             iv_order_value TYPE p
*   EXPORTING es_result      TYPE zs_credit_check_result

    DATA: ls_credit TYPE ty_credit_master,
          ls_open   TYPE ty_exposure,
          ls_result TYPE ty_check_result,
          lv_tol_pct  TYPE p LENGTH 5 DECIMALS 2,
          lv_tol_days TYPE i.

    CLEAR es_result.

*----------------------------------------------------------------------*
* Authorization check — sales organization display authority
*----------------------------------------------------------------------*
    AUTHORITY-CHECK OBJECT 'V_VBAK_VKO'
      ID 'VKORG' FIELD iv_vkorg
      ID 'ACTVT' FIELD '03'.

    IF sy-subrc <> 0.
      RAISE authorization_failed.
    ENDIF.

*----------------------------------------------------------------------*
* Read credit master data (KNKK)
*----------------------------------------------------------------------*
    SELECT SINGLE kunnr kkber klimk skfor ssobl ctlpc crblb waers
      INTO CORRESPONDING FIELDS OF ls_credit
      FROM knkk
      WHERE kunnr = iv_kunnr
        AND kkber = iv_kkber.

    IF sy-subrc <> 0.
*     No credit master record — order must not proceed
      ls_result-status       = 'B'.
      ls_result-reason_code  = 'NO_CREDIT_MASTER'.
      ls_result-message_type = 'E'.
      ls_result-message_text = |No credit master record for customer { iv_kunnr } in area { iv_kkber }|.
      ls_result-delivery_block = 'Z1'.
      es_result = ls_result.
      RETURN.
    ENDIF.

*----------------------------------------------------------------------*
* Central credit block set by finance
*----------------------------------------------------------------------*
    IF ls_credit-crblb = 'X'.
      ls_result-status       = 'B'.
      ls_result-reason_code  = 'CUSTOMER_BLOCKED'.
      ls_result-message_type = 'E'.
      ls_result-message_text = |Customer { iv_kunnr } is blocked for credit reasons|.
      ls_result-delivery_block = 'Z1'.
      es_result = ls_result.
      RETURN.
    ENDIF.

*----------------------------------------------------------------------*
* Open order and delivery values, overdue items
*----------------------------------------------------------------------*
    SELECT SUM( p~netwr ) INTO ls_open-open_order_value
      FROM vbak AS k
      INNER JOIN vbap AS p ON p~vbeln = k~vbeln
      WHERE k~kunnr = iv_kunnr
        AND k~vbtyp = 'C'          " Sales order
        AND k~lifsk = ' '.         " Not already blocked

    SELECT SUM( p~netwr ) INTO ls_open-open_delivery_value
      FROM likp AS l
      INNER JOIN lips AS p ON p~vbeln = l~vbeln
      WHERE l~kunnr = iv_kunnr
        AND l~wbstk <> 'C'.        " Goods issue not completed

    SELECT SUM( wrbtr ) INTO ls_open-overdue_amount
      FROM bsid
      WHERE kunnr = iv_kunnr
        AND augdt = '00000000'     " Not cleared
        AND zfbdt < sy-datum.

    SELECT MAX( sy-datum - zfbdt ) INTO ls_open-overdue_days
      FROM bsid
      WHERE kunnr = iv_kunnr
        AND augdt = '00000000'
        AND zfbdt < sy-datum.

*----------------------------------------------------------------------*
* Exposure and limit evaluation
*----------------------------------------------------------------------*
    ls_result-total_exposure = calculate_exposure(
                                 is_credit      = ls_credit
                                 is_open        = ls_open
                                 iv_order_value = iv_order_value ).

    IF ls_credit-klimk <= 0.
*     No limit maintained: low risk customers pass, everyone else blocks
      IF ls_credit-ctlpc = '001'.
        ls_result-status       = 'P'.
        ls_result-reason_code  = 'NO_LIMIT_CHECK'.
        ls_result-message_type = 'S'.
        ls_result-message_text = |No credit limit maintained for { iv_kunnr }; check skipped|.
      ELSE.
        ls_result-status       = 'B'.
        ls_result-reason_code  = 'ZERO_CREDIT_LIMIT'.
        ls_result-message_type = 'E'.
        ls_result-message_text = |Credit limit is zero for customer { iv_kunnr }|.
        ls_result-delivery_block = 'Z1'.
      ENDIF.
      es_result = ls_result.
      RETURN.
    ENDIF.

    lv_tol_pct = get_limit_tolerance( ls_credit-ctlpc ).

    ls_result-effective_limit = ls_credit-klimk * ( 1 + lv_tol_pct / 100 ).
    ls_result-utilization_pct = ls_result-total_exposure / ls_credit-klimk * 100.

    IF ls_result-total_exposure > ls_result-effective_limit.
      ls_result-status       = 'B'.
      ls_result-reason_code  = 'LIMIT_EXCEEDED'.
      ls_result-message_type = 'E'.
      ls_result-message_text = |Credit limit exceeded: exposure { ls_result-total_exposure } | &&
                               |above effective limit { ls_result-effective_limit }|.
      ls_result-delivery_block = 'Z1'.
    ELSEIF ls_result-utilization_pct >= 90.
      ls_result-status       = 'W'.
      ls_result-reason_code  = 'LIMIT_NEARLY_EXCEEDED'.
      ls_result-message_type = 'W'.
      ls_result-message_text = |Credit limit { ls_result-utilization_pct }% utilized for customer { iv_kunnr }|.
    ELSE.
      ls_result-status       = 'P'.
      ls_result-reason_code  = 'OK'.
      ls_result-message_type = 'S'.
      ls_result-message_text = |Credit check passed for customer { iv_kunnr }|.
    ENDIF.

*----------------------------------------------------------------------*
* Overdue items override a passing or warning result
*----------------------------------------------------------------------*
    IF ls_result-status <> 'B'.
      lv_tol_days = get_overdue_tolerance( ls_credit-ctlpc ).

      IF ls_open-overdue_amount > 0 AND ls_open-overdue_days > lv_tol_days.
        ls_result-status       = 'B'.
        ls_result-reason_code  = 'OVERDUE_ITEMS'.
        ls_result-message_type = 'E'.
        ls_result-message_text = |Overdue items { ls_open-overdue_amount } | &&
                                 |({ ls_open-overdue_days } days) exceed tolerance of { lv_tol_days } days|.
        ls_result-delivery_block = 'Z1'.
      ENDIF.
    ENDIF.

    es_result = ls_result.

  ENDMETHOD.

ENDCLASS.
