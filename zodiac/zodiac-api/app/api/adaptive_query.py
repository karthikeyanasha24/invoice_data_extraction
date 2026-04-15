"""
Universal Adaptive Query API — answers ANY question about ALL 121 database tables.

POST /api/query/adaptive
Body: { question, tableHint?, contextData?, overrideSql? }

Architecture:
  - Reads tables_columns.csv (121 tables, 9,352 columns) at startup, cached forever
  - Generates a full schema context with data types (text/numeric/date/etc.)
  - Sends complete schema + rich system prompt to GPT-4o
  - Auto-retries up to 3x with exact PostgreSQL error fed back for self-correction
  - Applies all SQL sanitizers (SAP text→numeric cast, HAVING alias fix, :: cast conversion)
  - Fallback to orchestrator if all retries fail
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..database import get_db
from ..config.config import OPENAI_API_KEY, USE_SAP_DB_FOR_AI
from ..database import get_sap_session

logger = logging.getLogger("zodiac-api.adaptive_query")
router = APIRouter(tags=["adaptive-query"])

# ─── Paths ────────────────────────────────────────────────────────────────────
_CSV_PATH    = Path(__file__).resolve().parent.parent.parent / "tables_columns.csv"
_SCHEMA_JSON = Path(__file__).resolve().parent.parent.parent / "schema_full.json"


# ─── Schema loader (process-lifetime cache) ───────────────────────────────────

@lru_cache(maxsize=1)
def _load_schema() -> Dict[str, List[Dict[str, str]]]:
    """
    Returns { table_name: [ {col, type}, ... ] }.
    Prefers schema_full.json if present (pre-generated), otherwise reads CSV.
    """
    if _SCHEMA_JSON.exists():
        with open(_SCHEMA_JSON, encoding="utf-8") as f:
            return json.load(f)

    tables: Dict[str, List[Dict[str, str]]] = {}
    with open(_CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tbl = (row.get("table") or "").strip()
            col = (row.get("column") or "").strip()
            dt  = (row.get("data_type") or "text").strip().lower()
            if tbl and col:
                tables.setdefault(tbl, []).append({"col": col, "type": dt})
    return tables


def _table_cols(tbl: str) -> List[str]:
    return [c["col"] for c in _load_schema().get(tbl, [])]


def _col_type(tbl: str, col: str) -> str:
    for c in _load_schema().get(tbl, []):
        if c["col"] == col:
            return c["type"]
    return "text"


# ─── Numeric TEXT columns that need CAST in aggregate functions ───────────────
# These are columns the CSV says are TEXT but represent numeric values.
# Any SUM/AVG/MIN/MAX on these needs: CAST(NULLIF(TRIM(CAST(x AS TEXT)),'') AS NUMERIC)

_NUMERIC_TEXT_COLS: frozenset = frozenset({
    # Finance / GL
    "hsl","ksl","msl","wsl","hsl0","ksl0","msl0","wsl0",
    "dmbtr","wrbtr","dmbe2","hwbe2","pswbt","pswsl","pyamt",
    # Billing / Sales
    "netwr","mwsbp","wavwr","stawn","kwert","kbetr","kwert_k","kaqty",
    "kzwi1","kzwi2","kzwi3","kzwi4","kzwi5","kzwi6",
    "fkimg","fklmg","kwmeng","zmeng","amtbl","valtg",
    # Purchasing / Invoice
    "rmwwr","rmwsk","netpr","brtwr","zwert","gnetwr","dpamt",
    "wwert","otb_value","otb_res_value","otb_spec_value",
    # Quantities
    "menge","ktmng","abmng","lmein","cnfm_qty","fsh_salloc_qty","fsh_ralloc_qty",
    # Material weight/volume
    "brgew","ntgew","volum","sumbd","kcbrgew","kcntgew","kcvolum",
    # Costing
    "gpreis","fpreis","dpreis","preis1","preis2","preis3","preis4","preis5",
    "opreis","tpreis","wertb","wertn","summ1","summ2","summ3",
    "me_summ1","summ1_kpf","summ2_kpf","summ3_kpf",
    # Material valuation
    "stprs","verpr","salk3","absalk3","lbkum","eiprice",
    # Stock
    "labst","insme","einme",
    # CO amounts
    "wkg001","wkg002","wkg003","wkg004","wkg005",
    "wkg006","wkg007","wkg008","wkg009","wkg010","wkg011","wkg012",
    # Misc
    "naucost","nopcost","bmenge","retamt_fc","diff_amount","customs_val",
    "ocs_count","sumziffr",
})


# ─── Business context for every table ─────────────────────────────────────────

_TABLE_CONTEXT: Dict[str, str] = {
    # SAP Sales & Billing
    "VBRK":   "Billing document HEADER. One row = one invoice. vbeln=doc#, kunag=customer(payer), fkdat=billing date(YYYYMMDD), waerk=currency, netwr=net total(TEXT→CAST), fkart=doc type, vkorg=sales org, fktyp=billing category",
    "vbrp":   "Billing document ITEMS (stored lowercase). Many rows per invoice. vbeln=billing doc (links VBRK.vbeln), posnr=item#, matnr=material, arktx=description, netwr=item net value(TEXT→CAST), fkimg=billed qty(TEXT→CAST), fklmg=qty in sales UOM(TEXT→CAST), mwsbp=tax(TEXT→CAST), vgbel=ref sales order, vgpos=ref sales item",
    "VBAK":   "Sales order HEADER. vbeln=SO#, audat=order date(YYYYMMDD), kunnr=customer, netwr=SO net value(TEXT→CAST), vkorg=sales org, vtweg=distribution channel, auart=order type, erdat=created date",
    "VBAP":   "Sales order ITEMS. vbeln=SO#, posnr=item#, matnr=material, arktx=description, kwmeng=confirmed order qty(TEXT→CAST), zmeng=target qty(TEXT→CAST), netwr=item value(TEXT→CAST), werks=plant, vgbel=ref doc",
    "VBEP":   "Sales order schedule lines. vbeln=SO#, posnr=item#, etenr=schedule line#, edatu=delivery date(YYYYMMDD), wmeng=confirmed qty",
    "VBFA":   "Document flow (traceability). vbelv=source doc, vbeln=target doc, vbtyp_n=target doc type (C=order, J=billing, L=delivery), posnv=source item, posnn=target item",
    "KONV":   "Pricing conditions. knumv=condition record#, kposn=item#, kschl=condition type (PR00=price, MWST=tax), kwert=condition value(TEXT→CAST), kbetr=rate(TEXT→CAST)",
    # SAP Delivery & Logistics
    "LIKP":   "Delivery HEADER. vbeln=delivery#, lfart=delivery type, lfdat=planned delivery date(YYYYMMDD), kunnr=customer, lifsk=delivery block, waerk=currency, netwr=total weight",
    "LIPS":   "Delivery ITEMS. vbeln=delivery#, posnr=item#, matnr=material, arktx=description, lfimg=delivery qty, vgbel=ref sales order, vgpos=ref SO item, werks=plant, lgort=storage location",
    "LSEG":   "Delivery segments (picking). vbeln=delivery#, posnr=item#, menge=picked qty",
    # SAP Purchasing
    "EKKO":   "Purchase order HEADER. ebeln=PO#, lifnr=vendor, bedat=PO creation date(YYYYMMDD), ekgrp=purch group, ekorg=purch org, waers=currency, loekz=deletion flag(''=active), kdatb=contract start, kdate=contract end, gwldt=GR deadline",
    "EKPO":   "Purchase order ITEMS. ebeln=PO#, ebelp=item#, matnr=material, txz01=description, menge=ordered qty(TEXT→CAST), meins=UOM, netpr=net price(TEXT→CAST), netwr=net value(TEXT→CAST), brtwr=gross value(TEXT→CAST), werks=plant, lgort=storage loc, agdat=expected delivery date(YYYYMMDD TEXT), elikz=delivery complete flag('X'=done), loekz=deletion flag, matkl=material group, infnr=info record#",
    "EBAN":   "Purchase requisition. banfn=req#, bnfpo=item#, matnr=material, menge=qty(TEXT→CAST), bsart=req type, afnam=requestor, badat=req date(YYYYMMDD), werks=plant",
    "EINA":   "Purchasing info record (general). infnr=info record#, matnr=material, lifnr=vendor",
    "EINE":   "Purchasing info record (org data). infnr=info record#, ekorg=purch org, netpr=net price(TEXT→CAST), peinh=price unit, waers=currency",
    "RBKP":   "Invoice receipt HEADER (MM-IV). belnr=doc#, gjahr=fiscal year, lifnr=vendor, budat=posting date(YYYYMMDD), rmwwr=gross amount(TEXT→CAST), rmwsk=tax amount(TEXT→CAST), waers=currency, bstat=status",
    "RSEG":   "Invoice receipt ITEMS. belnr=doc#, gjahr=fiscal year, buzei=item#, ebeln=PO#, ebelp=PO item#, matnr=material, menge=invoiced qty(TEXT→CAST), wrbtr=amount(TEXT→CAST), lbkum=stock qty(TEXT→CAST)",
    "RESB":   "Reservation / dependent requirements. matnr=material, werks=plant, menge=required qty, gpreis=planned price(TEXT→CAST)",
    # SAP Finance / Accounting
    "BKPF":   "Accounting document HEADER. belnr=doc#, bukrs=company code, gjahr=fiscal year, blart=doc type (SA=GL, KR=vendor invoice, DR=customer), budat=posting date(YYYYMMDD), bldat=doc date(YYYYMMDD), cpudt=entry date(YYYYMMDD), cputm=entry time, waers=currency, stblg=reversal doc#(''or'0000000000'=not reversed), stjah=reversal fiscal year, bktxt=header text, xstov=void flag",
    "BSEG":   "Accounting document SEGMENT (line items). belnr=doc#, bukrs=company, gjahr=fiscal year, buzei=line#, hkont=GL account, kunnr=customer#, lifnr=vendor#, dmbtr=local currency amount(TEXT→CAST), wrbtr=doc currency amount(TEXT→CAST), shkzg='S'=debit/'H'=credit, mwskz=tax code, kostl=cost center, prctr=profit center, menge=quantity(TEXT→CAST), meins=UOM, zuonr=assignment, sgtxt=line text, budat=posting date",
    "BSAD":   "Customer cleared items (open item accounting). belnr=doc#, kunnr=customer, dmbtr=cleared amount(TEXT→CAST), wrbtr=doc currency amount(TEXT→CAST), shkzg=D/C, budat=clearing date(YYYYMMDD), augdt=clearing date",
    "FAGLFLEXA": "General ledger ACTUAL line items (new GL). prctr=profit center, rbukrs=company code, racct=GL account, docnr=doc#, ryear=fiscal year, poper=period('001'-'012'), hsl=local amount(TEXT→CAST), ksl=2nd currency amount(TEXT→CAST), msl=quantity(TEXT→CAST), rtcur=currency, rclnt=client",
    "DFKKOP":  "FI-CA document item (contract accounts). faedn=due date(YYYYMMDD), betrw=amount, waers=currency",
    "T016T":   "Credit control area texts. kkber=credit control area, spras=language, name=description",
    # SAP Controlling
    "COEP":   "CO document line items (actual). kokrs=controlling area, belnr=doc#, buzei=item#, objnr=cost object, kstar=cost element, kostl=cost center, lstar=activity type, wkg001-wkg012=period amounts (need CAST if TEXT)",
    "COSP":   "Cost totals external postings. kokrs=controlling area, objnr=cost object, kstar=cost element, gjahr=fiscal year",
    "COSS":   "Cost totals internal postings. kokrs=controlling area, objnr, kstar, gjahr",
    "CEPC":   "Profit center master. prctr=profit center ID, kokrs=controlling area, name1=name, abtei=department, verak=manager, datbi=valid to(YYYYMMDD), datab=valid from",
    "CSKS":   "Cost center master. kostl=cost center ID, kokrs=controlling area, datbi=valid to, datab=valid from, ktext=description",
    "CSKT":   "Cost center texts. kostl=cost center, spras=language, ktext=name",
    "CRHD":   "Work center / resource header. arbid=resource ID, werks=plant, arbpl=work center, verwe=usage",
    "AUFK":   "Order master data. aufnr=order#, auart=order type, bukrs=company, werks=plant, erdat=created date",
    "AFKO":   "Production order header. aufnr=order#, plnbez=routing, stlnr=BOM, gstrs=scheduled start, gltrs=scheduled finish",
    "AFPO":   "Production order item. aufnr=order#, posnr=item#, matnr=material, plmng=planned qty, wemng=goods receipt qty",
    # SAP Costing
    "CKHS":   "Costing run header. kalnr=cost estimate#, menge=lot size(TEXT→CAST)",
    "CKIS":   "Cost estimate items. kalnr=cost estimate#, kkzma=item type, wertn=total value(TEXT→CAST), menge=qty(TEXT→CAST), gpreis=unit price(TEXT→CAST)",
    "CKIT":   "Costing item detail. kalnr, kkzma, matnr, kostl",
    "KEKO":   "Product costing header. kalnr=cost estimate#, matnr=material, werks=plant, lhkos=lot size, kadat=cost estimate date",
    "KEPH":   "Cost components. kalnr=cost estimate#, kkzma=cost component split",
    "CKMLCR": "Material ledger: currency and quantity. bwkey=valuation area, matnr=material, stprs=standard price(TEXT→CAST), salk3=total stock value(TEXT→CAST)",
    "CKMLHD": "Material ledger header. bwkey, matnr, bwtar, poper=period, bdatj=fiscal year",
    "CKMLPP": "Material ledger period data. bwkey, matnr, poper, lbkum=stock qty(TEXT→CAST)",
    "CKMLPR": "Material ledger prices. bwkey, matnr, poper, eiprice=entry price(TEXT→CAST)",
    "TCKH1":  "Cost element hierarchy. kokrs=controlling area, hierachie=hierarchy name",
    "TCKH2":  "Cost element hierarchy nodes. kokrs, hierachie, kstar=cost element",
    # CO-PA
    "CE1BGIS":"CO-PA actuals BGIS. prctr=profit center, kndnr=customer, artnr=product, ww001-ww080=value fields",
    "CE1IDEA":"CO-PA actuals IDEA. prctr, kndnr, artnr, ww001-ww080=value fields",
    "CE1INT1":"CO-PA actuals INT1. prctr, kndnr, artnr, value fields",
    "CE1PR22":"CO-PA actuals PR22. prctr, kndnr, artnr, value fields",
    "CE1R300":"CO-PA actuals R300. value fields per profit center and product",
    "CE1S_AL":"CO-PA actuals S_AL. value fields",
    "CE1S_CP":"CO-PA actuals S_CP. value fields",
    "CE1S_GO":"CO-PA actuals S_GO. value fields",
    "CE2BGIS":"CO-PA plan BGIS. same structure as CE1BGIS but plan data",
    "CE2IDEA":"CO-PA plan IDEA. plan value fields",
    "CE2S_AL":"CO-PA plan S_AL.",
    "CE2S_CP":"CO-PA plan S_CP.",
    "CS2S_GO":"CO-PA segment S_GO.",
    # SAP Master Data
    "KNA1":   "Customer master GENERAL. kunnr=customer ID, name1=name, name2=name2, land1=country code, regio=region, ort01=city, pstlz=postal code, ktokd=account group, sperr=order block flag, telf1=phone",
    "KNVV":   "Customer master SALES DATA. kunnr=customer, vkorg=sales org, vtweg=dist channel, spart=division, kdgrp=customer group, zterm=payment terms, vkbur=sales office, vkgrp=sales group",
    "KNVP":   "Customer partner functions. kunnr, vkorg, vtweg, spart, parvw=partner function (AG=sold-to, WE=ship-to, RE=bill-to, RG=payer)",
    "KNBK":   "Customer bank data. kunnr=customer, banks=bank country, bankl=bank key, bankn=bank account",
    "LFA1":   "Vendor master GENERAL. lifnr=vendor ID, name1=name, land1=country, regio=region, ort01=city, sperr=purchase block, loevm=deletion flag",
    "LFB1":   "Vendor master COMPANY CODE. lifnr=vendor, bukrs=company, zterm=payment terms, akont=reconciliation account",
    "LFM1":   "Vendor master PURCHASING ORG. lifnr=vendor, ekorg=purch org, waers=currency, zterm=payment terms",
    "MARA":   "Material master GENERAL. matnr=material ID, mtart=material type (FERT=finished,ROH=raw,HALB=semi), matkl=material group, meins=base UOM, brgew=gross weight(TEXT→CAST), ntgew=net weight(TEXT→CAST), volum=volume(TEXT→CAST), normt=industry standard, bismt=old material#, spart=division",
    "MAKT":   "Material DESCRIPTIONS. matnr=material ID, spras=language, maktx=description text",
    "MARC":   "Material PLANT DATA. matnr=material, werks=plant, beskz=procurement type (E=in-house, F=external), eisbe=safety stock, minbe=reorder point, mtvfp=checking rule, mmsta=plant status",
    "MARD":   "Material STORAGE LOCATION STOCK. matnr=material, werks=plant, lgort=storage location, labst=unrestricted stock(TEXT→CAST), insme=quality inspection stock(TEXT→CAST), einme=restricted-use stock(TEXT→CAST)",
    "MARM":   "Material UNITS OF MEASURE. matnr=material, meinh=alt UOM, umren=numerator, umrez=denominator, brgew=gross weight(TEXT→CAST), volum=volume(TEXT→CAST)",
    "MBEW":   "Material VALUATION. matnr=material, bwkey=valuation area, bwtar=valuation type, lbkum=total stock(TEXT→CAST), salk3=total stock value(TEXT→CAST), stprs=standard price(TEXT→CAST), verpr=moving avg price(TEXT→CAST), vprsv='S'=standard/'V'=moving avg",
    "MBEWH":  "Material valuation HISTORY. same as MBEW with period data",
    "MCHB":   "Batch STOCKS. matnr=material, werks=plant, lgort=storage loc, charg=batch, clabs=unrestricted stock",
    "MEAN":   "International article numbers (EAN/barcode). matnr=material, meinh=UOM, ean11=EAN code",
    "MKPF":   "Material document HEADER. mblnr=doc#, mjahr=year, bldat=doc date, budat=posting date",
    "MLAN":   "Tax classification for material. matnr=material, aland=departure country, taxkm=tax category",
    "MSLB":   "Special stocks at vendor. matnr=material, lifnr=vendor, werks=plant",
    "MVKE":   "Material SALES DATA. matnr=material, vkorg=sales org, vtweg=dist channel, dpppp=material pricing group, kondm=price group",
    "STKO":   "BOM HEADER. stlnr=BOM#, stlal=alternative, matnr=material, werks=plant, stlan=BOM usage",
    "STPO":   "BOM ITEMS. stlnr=BOM#, stlal=alternative, posnr=item#, idnrk=component material, menge=qty(TEXT→CAST), meins=UOM",
    "CABN":   "Characteristic definition. atinn=internal char#, atnam=char name, atfor=data type, atmlt=char length",
    "AUSP":   "Characteristic values. objek=object#, atinn=char#, atwrt=value, atflv=numeric from, atflb=numeric to",
    "KLAH":   "Class header. klart=class type, class=class name, spras=language",
    # Zodiac App Tables
    "invoice_business_data": "V1 invoice processing records. tracking_id=tracking ID, customer_name, customer_country, supplier_name, supplier_id, failure_reason, current_stage (pending/processing/completed/failed), total_amount NUMERIC, tax_amount NUMERIC, currency, invoice_number, industry, industry_confidence NUMERIC, invoice_date DATE, uploaded_at TIMESTAMP",
    "invoice_v2_business_data": "V2 extracted invoice data. validated_invoice_id FK, customer_name, customer_country, supplier_name, total_amount NUMERIC, tax_amount NUMERIC, currency, invoice_date DATE, fiscal_year INT, fiscal_quarter INT, season TEXT, industry TEXT, industry_confidence NUMERIC, user_id",
    "invoice_v2_documents": "V2 uploaded invoice documents. id UUID, filename, source, validation_status ('pending'/'valid'/'invalid'/'corrected'), uploaded_at TIMESTAMP, uploaded_by",
    "invoice_v2_validated": "V2 validation results. document_id FK→invoice_v2_documents.id, status ('valid'/'invalid'/'corrected'), validation_errors JSONB, missing_fields JSONB, correction_applied BOOL, validated_at TIMESTAMP",
    "v2_invoice_documents": "V2 document tracking. tracking_id, user_id, filename, xml_path, validation_status, uploaded_at TIMESTAMP, deleted_at",
    "v2_validated_invoices": "V2 validated invoice output. document_id FK, status, validation_errors JSONB, validation_notes, correction_applied BOOL, correction_cache_id, validated_at TIMESTAMP",
    "converted_invoices": "Conversion results. validated_invoice_id FK, customer_id, target_format (UBL/EDIFACT/X12/PEPPOL), conversion_status ('pending'/'success'/'failed'), conversion_notes TEXT, converted_at TIMESTAMP, validation_overridden BOOL",
    "zodiac_invoice_failed_edi": "Failed EDI invoice processing. tracking_id, user_id, invoice_number, uploaded_at, xml_validation_pass BOOL, xml_convert_message TEXT, edi_convert_pass BOOL, edi_convert_message TEXT, processing_steps_error TEXT, processing_steps JSONB, request_type, target_file_format",
    "zodiac_invoice_success_edi": "Successful EDI invoices. tracking_id, user_id, invoice_number, uploaded_at, xml_validation_pass BOOL, edi_convert_pass BOOL, external_status TEXT, external_message TEXT, processing_steps JSONB, target_file_format",
    "sat_documents": "SAT/CFDI documents (Mexico tax). id, user_id, portal_ref_id, cfdi_uuid, doc_type, supplier_rfc, supplier_name, receiver_rfc, receiver_name, serie, folio, fecha DATE, subtotal NUMERIC, total NUMERIC, moneda=currency, tipo_cambio NUMERIC, forma_pago, metodo_pago, related_cfdi_uuid, status",
    "sat_simple_merged": "SAT documents merged for SAP posting. vendor_rfc, vendor_name, fiscal_year INT, fiscal_period INT, document_count INT, total_amount NUMERIC, currency, sent_to_sap BOOL, sap_document_number, sent_to_sap_at TIMESTAMP",
    "sat_canonical_merged": "Canonical SAT merges with GL accounts. company_code, vendor_rfc, vendor_name, total_invoices INT, total_credits INT, net_amount NUMERIC, currency, sap_gl_account, status, sap_document_number, sent_to_sap_at TIMESTAMP",
    "sat_duplicate_checks": "UUID/folio duplicate detection. cfdi_uuid, sat_document_id, user_id, supplier_id, document_type, first_received_at TIMESTAMP",
    "sat_processing_logs": "SAT processing event log. sat_document_id, user_id, action, status, message, created_at TIMESTAMP",
    "sat_sap_account_mapping": "SAT product code → SAP GL account. clave_prod_serv, sap_gl_account, description, is_active BOOL, is_default BOOL",
    "sat_supplier_account_mapping": "Supplier RFC → SAP GL account. supplier_rfc, sap_gl_account, is_active BOOL, is_default BOOL, company_code, fiscal_year, currency, opening_balance NUMERIC, credit_amount NUMERIC, debit_amount NUMERIC, closing_balance NUMERIC",
    "sat_company_mappings": "Company code mappings. company_code, company_name, rfc, is_active BOOL",
    "customers": "Registered customer accounts. customer_id TEXT, format TEXT, api_address TEXT, validation_rules JSONB, created_at TIMESTAMP",
    "supplier_tokens": "Supplier API authentication tokens. supplier_rfc, supplier_name, is_active BOOL, expires_at TIMESTAMP, last_used_at TIMESTAMP, created_at TIMESTAMP, created_by, notes TEXT",
    "customer_tokens": "Customer API authentication tokens. customer_id, is_active BOOL, expires_at TIMESTAMP, last_used_at TIMESTAMP",
    "customer_receiver_rfc": "Customer → RFC mappings for SAT delivery. customer_id, receiver_rfc",
    "customer_delivery_settings": "Customer EDI delivery configuration. customer_id, settings JSONB",
    "customer_certificates": "Customer digital certificates. customer_id, certificate_data, expiry_date, is_active BOOL",
    "certificate_renewal_requests": "Certificate renewal tracking. customer_id, requested_at, status",
    "certificate_revocation_list": "Revoked certificates log. serial_number, revoked_at, reason",
    "user_customers": "User ↔ customer access mapping. user_id, customer_id",
    "zodiac_users": "Zodiac user accounts. email, name, role, is_active BOOL, created_at",
    "zodiac_customers": "Zodiac customer records. customer_id, name, country, validation_rules JSONB",
    "ai_query_memory": "Approved Q→SQL pairs for reuse. question_pattern, sql_query TEXT, source ('chatgpt'/'user'/'assistant_sql'), use_count INT, approved_by_user_id, created_at",
    "ai_analysis_memory": "AI conversation memory per user. user_id, last_user_query, last_sql, last_rows_json JSONB, last_reply, updated_at",
    "ai_chat_threads": "AI chat conversation threads. thread_id TEXT, user_id, title, turn_count INT, last_active_at TIMESTAMP",
    "ai_chat_turns": "Individual AI conversation turns. thread_id, turn_index INT, role ('user'/'assistant'), content TEXT, sql_executed TEXT, result_rows JSONB, key_metrics JSONB, warnings TEXT, charts JSONB",
    "ai_learned_patterns": "AI learned query patterns. pattern TEXT, sql TEXT, success_count INT",
    "ai_query_embeddings": "AI query vector embeddings. question TEXT, embedding JSONB",
    "ai_training_data": "AI training examples. question TEXT, sql TEXT, result_summary TEXT",
    "correction_cache": "V1 correction rules cache. field_name, original_value, corrected_value, confidence NUMERIC",
    "invoice_v2_correction_cache": "V2 correction rules cache. field_name, original_value, corrected_value TEXT, applied_count INT",
    "v2_correction_cache": "V2 correction cache. field_name, field_value TEXT, corrected_value TEXT, customer_id",
    "sat_sap_account_mapping": "SAT product codes to SAP GL accounts. clave_prod_serv, sap_gl_account, code_group, description, is_active BOOL",
}


def _build_schema_prompt() -> str:
    """
    Build a complete schema prompt for GPT — all 121 tables with all their columns and types.
    Shows which columns need CAST for numeric aggregates.
    """
    schema = _load_schema()
    lines: List[str] = []

    sap_tables = sorted(t for t in schema if t and t[0].isupper())
    app_tables = sorted(t for t in schema if t and (t[0].islower() or t[0].isdigit()))

    lines.append("=== FULL DATABASE SCHEMA (121 TABLES) ===\n")
    lines.append("── APP TABLES (Zodiac app data, lowercase, no quoting needed) ──")

    for tbl in app_tables:
        cols = schema[tbl]
        ctx = _TABLE_CONTEXT.get(tbl, "")
        col_parts = []
        for c in cols:
            dt = c["type"]
            marker = ""
            if dt in ("numeric", "double precision", "integer", "bigint"):
                marker = "ℕ"  # native numeric
            elif dt in ("timestamp with time zone", "timestamp without time zone"):
                marker = "📅"
            elif dt == "date":
                marker = "📅"
            elif dt == "boolean":
                marker = "🔘"
            elif dt in ("jsonb", "json"):
                marker = "📋"
            elif dt == "uuid":
                marker = "🔑"
            col_parts.append(f"{c['col']}{marker}" if marker else c["col"])
        col_str = ", ".join(col_parts[:60]) + ("..." if len(cols) > 60 else "")
        ctx_str = f"  # {ctx}" if ctx else ""
        lines.append(f"  {tbl} [{len(cols)} cols]: {col_str}{ctx_str}")

    lines.append("\n── SAP TABLES (ERP data, MUST double-quote: \"TABLE\".\"col\") ──")

    for tbl in sap_tables:
        cols = schema[tbl]
        ctx = _TABLE_CONTEXT.get(tbl, "")
        col_parts = []
        for c in cols:
            name, dt = c["col"], c["type"]
            if name in _NUMERIC_TEXT_COLS and dt == "text":
                col_parts.append(f"{name}*")  # * = needs CAST
            elif dt in ("numeric", "double precision", "integer", "bigint"):
                col_parts.append(f"{name}ℕ")
            else:
                col_parts.append(name)
        col_str = ", ".join(col_parts[:60]) + ("..." if len(cols) > 60 else "")
        ctx_str = f"  # {ctx}" if ctx else ""
        lines.append(f"  {tbl} [{len(cols)} cols]: {col_str}{ctx_str}")

    lines.append("\n(* = TEXT column that needs CAST(NULLIF(TRIM(CAST(col AS TEXT)),'') AS NUMERIC) in SUM/AVG/MIN/MAX)")
    lines.append("(ℕ = native numeric, 📅 = date/timestamp, 🔘 = boolean, 📋 = JSONB, 🔑 = UUID)")

    return "\n".join(lines)


# ─── Universal system prompt ───────────────────────────────────────────────────

_SYSTEM_PROMPT_CORE = """You are an expert PostgreSQL analyst for a Zodiac invoice processing + SAP ERP system.
You have access to ALL 121 database tables. Generate accurate, executable SQL for any question.

══════════════════════════════════════════════════════
SECTION 1: CRITICAL POSTGRESQL RULES
══════════════════════════════════════════════════════

1. SAP TABLE QUOTING (mandatory):
   FROM "VBRK" AS k   -- uppercase SAP tables MUST be double-quoted
   FROM "vbrp" AS p   -- vbrp is SAP billing items stored lowercase, still needs quotes
   FROM invoice_v2_business_data  -- lowercase app tables: NO quotes

2. SAP NUMERIC COLUMNS (stored as TEXT — ALWAYS CAST in SUM/AVG/MIN/MAX):
   SUM(CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)), '') AS NUMERIC))
   Columns marked * in schema need this cast. NEVER use bare SUM(col) on TEXT columns.

3. SAP DATE COLUMNS (stored as TEXT 'YYYYMMDD' — NEVER cast to DATE):
   Year filter:    SUBSTRING(TRIM(k."fkdat"), 1, 4) = '2001'
   Month filter:   SUBSTRING(TRIM(b."budat"), 1, 6) = '202401'
   Overdue check:  TRIM(p."agdat") < TO_CHAR(CURRENT_DATE, 'YYYYMMDD')
   Last 30 days:   TRIM(b."budat") >= TO_CHAR(CURRENT_DATE - INTERVAL '30 days', 'YYYYMMDD')
   Always: TRIM() before comparing, check TRIM(col) != '' to exclude empty dates

4. HAVING CLAUSE: NEVER use SELECT aliases in HAVING — repeat the full expression:
   WRONG:  HAVING total_amount > 0
   RIGHT:  HAVING SUM(CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)),'') AS NUMERIC)) > 0

5. APP TABLE DATES (real PostgreSQL date/timestamp types — use normally):
   WHERE uploaded_at >= NOW() - INTERVAL '30 days'
   WHERE invoice_date >= CURRENT_DATE - INTERVAL '90 days'

══════════════════════════════════════════════════════
SECTION 2: KEY TABLE RELATIONSHIPS (JOINS)
══════════════════════════════════════════════════════

Sales & Billing:
  "VBRK" → "vbrp":  k.vbeln = p.vbeln  (billing header → billing items)
  "vbrp" → "VBAK":  p.vgbel = a.vbeln  (billing item → sales order header)
  "vbrp" → "VBAP":  p.vgbel = a.vbeln AND p.vgpos = a.posnr  (billing item → SO item)
  "VBAK" → "VBAP":  a.vbeln = p.vbeln  (sales order header → items)
  "VBAK" → "KNA1":  a.kunnr = c.kunnr  (sales order → customer)
  "VBRK" → "KNA1":  k.kunag = c.kunnr  (billing header → customer, kunag=payer)
  "VBFA": vbelv=source doc, vbeln=target doc (document flow)

Delivery:
  "LIKP" → "LIPS":  d.vbeln = i.vbeln  (delivery header → items)
  "LIPS" → "VBAP":  i.vgbel = a.vbeln AND i.vgpos = a.posnr  (delivery → SO item)

Purchasing:
  "EKKO" → "EKPO":  k.ebeln = p.ebeln  (PO header → items)
  "EKKO" → "LFA1":  k.lifnr = v.lifnr  (PO → vendor)
  "RBKP" → "RSEG":  r.belnr = s.belnr AND r.gjahr = s.gjahr  (invoice receipt header → items)
  "RSEG" → "EKPO":  s.ebeln = p.ebeln AND s.ebelp = p.ebelp  (invoice item → PO item)

Finance:
  "BKPF" → "BSEG":  b.belnr = s.belnr AND b.bukrs = s.bukrs AND b.gjahr = s.gjahr
  "BSEG" → "KNA1":  s.kunnr = c.kunnr  (only customer postings)
  "BSEG" → "LFA1":  s.lifnr = v.lifnr  (only vendor postings)
  "FAGLFLEXA" → "CEPC":  f.prctr = c.prctr  (GL → profit center master)
  "FAGLFLEXA" → "CSKS":  f.racct = s.kostl  (GL → cost center via GL account)

Material:
  "MARA" → "MAKT":  m.matnr = t.matnr AND t.spras = 'E'  (material → English description)
  "MARA" → "MARC":  m.matnr = c.matnr  (general → plant data)
  "MARC" → "MARD":  c.matnr = d.matnr AND c.werks = d.werks  (plant data → stock)
  "MARA" → "MBEW":  m.matnr = v.matnr  (material → valuation)

══════════════════════════════════════════════════════
SECTION 3: BUSINESS RULES & KEYWORD MAPPING
══════════════════════════════════════════════════════

INVOICE COUNT (Andy's issue: count invoices NOT line items):
  ✓ GROUP BY "VBRK".vbeln  (one row per invoice document)
  ✗ GROUP BY "vbrp".vbeln, "vbrp".posnr  (this counts line items, not invoices)
  Multiple line items per invoice is NORMAL — always aggregate at header level for invoice counts

CUSTOMER NUMBERS:
  "VBRK".kunag = payer/customer (use this for customer billing analysis)
  "VBAK".kunnr = sold-to customer
  Join to "KNA1".kunnr for customer name

STATUS / FLAG FIELDS (TEXT, not BOOLEAN in SAP):
  EKPO.elikz = 'X' means delivery complete ('' = still open)
  EKPO.loekz = 'L' means deleted ('' = active)
  EKKO.loekz = 'L' means PO deleted
  BKPF.stblg = '' or '0000000000' means NOT reversed

OVERDUE PURCHASE ORDERS:
  Use EKPO.agdat = expected delivery date (TEXT 'YYYYMMDD')
  WHERE TRIM(p."agdat") < TO_CHAR(CURRENT_DATE, 'YYYYMMDD')
    AND TRIM(COALESCE(p."elikz",'')) = ''   -- not fully delivered
    AND TRIM(COALESCE(p."loekz",'')) = ''   -- not deleted
    AND TRIM(COALESCE(k."loekz",'')) = ''   -- PO not deleted

REVERSED DOCUMENTS:
  WHERE TRIM(COALESCE(b."stblg",'')) NOT IN ('','0000000000')  -- IS reversed
  WHERE TRIM(COALESCE(b."stblg",'')) IN ('','0000000000')      -- NOT reversed

SAT DOCUMENTS NOT YET SENT TO SAP:
  FROM sat_simple_merged WHERE sent_to_sap = false

KEYWORD → TABLES MAPPING:
  "invoice" (without SAP/VBRK context) → invoice_v2_business_data, invoice_business_data
  "invoice app" / "app invoice" → invoice_v2_business_data
  "billed" / "billing" / "billing doc" → "VBRK", "vbrp"
  "sales order" → "VBAK", "VBAP"
  "delivery" / "shipment" → "LIKP", "LIPS"
  "purchase order" / "PO" → "EKKO", "EKPO"
  "requisition" → "EBAN"
  "vendor" → "LFA1", "LFB1", "LFM1"
  "customer master" → "KNA1", "KNVV"
  "material master" / "material stock" → "MARA", "MARC", "MARD", "MAKT"
  "GL" / "general ledger" → "FAGLFLEXA", "BSEG", "BKPF"
  "profit center" → "FAGLFLEXA", "CEPC"
  "cost center" → "COEP", "CSKS"
  "pricing" / "conditions" → "KONV"
  "tax" → "BSEG".mwskz, "VBRK"/"vbrp".mwsbp, "RBKP".rmwsk
  "reversal" / "reversed" → "BKPF".stblg, "BKPF".stjah
  "document flow" / "trace order to invoice" → "VBFA"
  "invoice receipt" / "MM-IV" → "RBKP", "RSEG"
  "conversion" → converted_invoices
  "validation" → invoice_v2_validated, v2_validated_invoices
  "failed" / "failure" → zodiac_invoice_failed_edi, invoice_business_data.failure_reason
  "SAT" / "CFDI" / "RFC" → sat_documents, sat_simple_merged, sat_canonical_merged
  "duplicate" → sat_duplicate_checks
  "supplier token" / "API token" / "expired token" → supplier_tokens
  "AI query" / "chat history" → ai_chat_turns, ai_query_memory

══════════════════════════════════════════════════════
SECTION 4: PROVEN READY-TO-USE SQL PATTERNS
══════════════════════════════════════════════════════

-- Top customers by billed amount (INVOICE LEVEL, not item level) for a specific year:
SELECT k."vbeln" AS invoice_doc, k."kunag" AS customer_id, c."name1" AS customer_name,
       k."waerk" AS currency, k."fkdat" AS billing_date,
       SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)),'') AS NUMERIC)) AS total_billed,
       COUNT(DISTINCT k."vbeln") AS invoice_count
FROM "VBRK" k
JOIN "vbrp" p ON k."vbeln" = p."vbeln"
LEFT JOIN "KNA1" c ON k."kunag" = c."kunnr"
WHERE SUBSTRING(TRIM(k."fkdat"),1,4) = '2001'
GROUP BY k."vbeln", k."kunag", c."name1", k."waerk", k."fkdat"
ORDER BY total_billed DESC LIMIT 20;

-- Overdue purchase orders:
SELECT k."ebeln" AS po_number, k."lifnr" AS vendor_id, l."name1" AS vendor_name,
       p."ebelp" AS item, p."matnr" AS material, p."txz01" AS description,
       CAST(NULLIF(TRIM(CAST(p."menge" AS TEXT)),'') AS NUMERIC) AS ordered_qty,
       p."meins" AS uom, p."agdat" AS expected_delivery, p."werks" AS plant
FROM "EKKO" k
JOIN "EKPO" p ON k."ebeln" = p."ebeln"
LEFT JOIN "LFA1" l ON k."lifnr" = l."lifnr"
WHERE TRIM(COALESCE(p."agdat",'')) > '19000101'
  AND TRIM(p."agdat") < TO_CHAR(CURRENT_DATE, 'YYYYMMDD')
  AND TRIM(COALESCE(p."elikz",'')) = ''
  AND TRIM(COALESCE(p."loekz",'')) = ''
  AND TRIM(COALESCE(k."loekz",'')) = ''
ORDER BY p."agdat" ASC LIMIT 100;

-- Potential document reversals:
SELECT b."belnr", b."bukrs", b."gjahr", b."budat", b."blart",
       b."stblg" AS reversal_doc, b."stjah" AS reversal_year, b."waers",
       b."bktxt" AS header_text
FROM "BKPF" b
WHERE TRIM(COALESCE(b."stblg",'')) NOT IN ('','0000000000')
ORDER BY b."budat" DESC LIMIT 100;

-- Compare ordered vs billed quantity at item level:
SELECT p."vbeln" AS billing_doc, p."posnr" AS billing_item,
       p."matnr" AS material,
       CAST(NULLIF(TRIM(CAST(p."fkimg" AS TEXT)),'') AS NUMERIC) AS billed_qty,
       CAST(NULLIF(TRIM(CAST(a."kwmeng" AS TEXT)),'') AS NUMERIC) AS so_ordered_qty,
       p."meins" AS uom
FROM "vbrp" p
LEFT JOIN "VBAP" a ON p."vgbel" = a."vbeln" AND p."vgpos" = a."posnr"
ORDER BY p."vbeln", p."posnr" LIMIT 100;

-- Average invoice amounts by currency (Zodiac app tables):
SELECT currency,
       AVG(total_amount) AS avg_total_amount,
       AVG(tax_amount) AS avg_tax_amount,
       COUNT(*) AS invoice_count
FROM invoice_v2_business_data
WHERE currency IS NOT NULL AND currency <> ''
GROUP BY currency
ORDER BY avg_total_amount DESC;

-- Profit center GL cost (with proper TEXT cast for hsl):
SELECT f."prctr" AS profit_center, c."name1" AS pc_name,
       f."rtcur" AS currency,
       SUM(CAST(NULLIF(TRIM(CAST(f."hsl" AS TEXT)),'') AS NUMERIC)) AS total_amount
FROM "FAGLFLEXA" f
LEFT JOIN "CEPC" c ON f."prctr" = c."prctr"
WHERE TRIM(COALESCE(f."prctr",'')) <> ''
GROUP BY f."prctr", c."name1", f."rtcur"
HAVING SUM(CAST(NULLIF(TRIM(CAST(f."hsl" AS TEXT)),'') AS NUMERIC)) > 0
ORDER BY total_amount DESC LIMIT 20;

-- SAT documents not sent to SAP:
SELECT id, vendor_rfc, vendor_name, fiscal_year, fiscal_period,
       document_count, total_amount, currency, created_at
FROM sat_simple_merged
WHERE sent_to_sap = false
ORDER BY created_at DESC LIMIT 100;

══════════════════════════════════════════════════════
OUTPUT RULE: Return ONLY the SQL inside a ```sql block. NOTHING ELSE.
══════════════════════════════════════════════════════
"""


def _get_openai_key() -> str:
    k = (os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_AI_KEY") or OPENAI_API_KEY or "").strip()
    if not k:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Set OPEN_AI_KEY (or OPENAI_API_KEY) on the server")
    return k


def _extract_sql(text: str) -> Optional[str]:
    m = re.search(r"```sql\s*([\s\S]+?)\s*```", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"(SELECT[\s\S]+?)(;|$)", text, re.IGNORECASE)
    if m:
        return (m.group(1) + ";").strip()
    return None


def _execute_sql(db: Session, sql: str, question: str = "") -> List[Dict[str, Any]]:
    """Apply all sanitizers then execute. Raises on failure (caller handles retry)."""
    from ..services.sql_generation_sanitizers import (
        sanitize_generated_sap_sql,
        prepare_sql_for_sqlalchemy_text_execution,
    )
    sanitized = sanitize_generated_sap_sql(sql, question or None)
    safe = prepare_sql_for_sqlalchemy_text_execution(sanitized)
    try:
        db.rollback()
    except Exception:
        pass
    result = db.execute(text(safe))
    rows = result.fetchall()
    keys = list(result.keys())

    import datetime, decimal
    out: List[Dict[str, Any]] = []
    for row in rows:
        d: Dict[str, Any] = {}
        for k, v in zip(keys, row):
            if isinstance(v, (datetime.date, datetime.datetime)):
                d[k] = v.isoformat()
            elif isinstance(v, decimal.Decimal):
                d[k] = float(v)
            else:
                d[k] = v
        out.append(d)
    return out


# ─── Smart chart generation ────────────────────────────────────────────────

# Column name patterns for axis classification
_DATE_KEYWORDS   = {"date","month","year","period","quarter","week","day","time","at","budat","fkdat","erdat","audat","lfdat","bedat","created","updated","uploaded"}
_LABEL_KEYWORDS  = {"name","customer","vendor","material","product","country","region","currency","code","id","type","group","category","status","plant","org","center","description","text","desc","arktx","ktext","maktx","industry","supplier","format","class","doc","number","phase","stage","rfc","folio","uuid","lifnr","kunnr","matnr","prctr","kostl","hkont"}
_NUMERIC_KEYWORDS= {"amount","value","total","cost","revenue","sales","qty","quantity","count","price","weight","volume","stock","balance","rate","ratio","pct","percent","avg","average","sum","net","gross","tax","billed","paid","spent","profit","margin","labst","netwr","dmbtr","wrbtr","hsl","rmwwr","menge","brgew","ntgew","volum","salk3","stprs"}

CHART_COLORS = [
    "#3b82f6","#10b981","#f59e0b","#ef4444","#8b5cf6",
    "#06b6d4","#f97316","#ec4899","#14b8a6","#a855f7",
    "#eab308","#6366f1","#84cc16","#f43f5e","#0ea5e9",
]


def _col_role(col: str) -> str:
    """Classify a column as 'date', 'label', 'numeric', or 'other'."""
    c = col.lower()
    if any(k in c for k in _DATE_KEYWORDS):
        return "date"
    if any(k in c for k in _NUMERIC_KEYWORDS):
        return "numeric"
    if any(k in c for k in _LABEL_KEYWORDS):
        return "label"
    return "other"


def _is_numeric_val(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return True
    try:
        float(str(v).replace(",", ""))
        return True
    except Exception:
        return False


def _auto_charts(
    question: str,
    sql: str,
    data: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Auto-generate Recharts-compatible chart specs from query results.
    Returns a list of chart dicts (may be empty if no suitable chart).

    Strategy:
      1. Classify every column as date | label | numeric | other
      2. Pick chart type:
         - ≤12 rows + 1 label + 1-3 numeric → pie (if ≤8 rows) OR bar
         - date column + numeric → line/area
         - label column + numeric(s) → horizontal bar / grouped bar
         - 2 numeric series over label → grouped/stacked bar
      3. Return up to 2 charts (primary + secondary if useful)
    """
    if not data or len(data) < 1:
        return []

    cols = list(data[0].keys())
    # Classify columns based on name and actual values
    date_cols   = [c for c in cols if _col_role(c) == "date"]
    label_cols  = [c for c in cols if _col_role(c) == "label"]
    numeric_cols = [c for c in cols if _col_role(c) == "numeric" and _is_numeric_val(data[0].get(c))]

    # Also detect columns that are actually numeric by value but not by name
    for c in cols:
        if c not in date_cols + label_cols + numeric_cols:
            if _is_numeric_val(data[0].get(c)) and not isinstance(data[0].get(c), str):
                numeric_cols.append(c)

    # Need at least one dimension and one measure
    x_candidates = date_cols or label_cols or [c for c in cols if c not in numeric_cols]
    y_candidates = numeric_cols

    if not x_candidates or not y_candidates:
        return []

    charts: List[Dict[str, Any]] = []
    n_rows = len(data)
    n_numeric = len(y_candidates)
    x_key = x_candidates[0]
    y_keys = y_candidates[:4]  # max 4 series

    # Truncate label for long datasets
    chart_data = data[:50]  # max 50 points on a chart

    # ── Chart type selection ──────────────────────────────────────────────

    has_time = bool(date_cols)

    if n_rows <= 10 and n_numeric == 1 and not has_time:
        # Pie chart — few segments, one value
        q_lower = question.lower()
        use_pie = any(kw in q_lower for kw in ["distribution","share","breakdown","proportion","percent","pie","split","by currency","by country","by region","by type","by status","by category"])
        if use_pie or n_rows <= 6:
            charts.append({
                "chart_type": "pie",
                "title": _chart_title(question, "Distribution"),
                "description": f"Distribution of {y_keys[0].replace('_',' ')} by {x_key.replace('_',' ')}",
                "data": chart_data,
                "name_key": x_key,
                "value_key": y_keys[0],
                "colors": CHART_COLORS,
                "show_legend": True,
            })
            if n_rows > 1:
                # Also add bar as second view
                charts.append({
                    "chart_type": "bar",
                    "title": _chart_title(question, "Bar Chart"),
                    "description": f"{y_keys[0].replace('_',' ')} by {x_key.replace('_',' ')}",
                    "data": chart_data,
                    "x_key": x_key,
                    "y_keys": y_keys,
                    "colors": CHART_COLORS,
                    "show_legend": False,
                    "show_grid": True,
                })
            return charts

    if has_time:
        # Line / area chart for time series
        chart_type = "area" if n_numeric == 1 else "line"
        charts.append({
            "chart_type": chart_type,
            "title": _chart_title(question, "Trend"),
            "description": f"{', '.join(k.replace('_',' ') for k in y_keys)} over time",
            "data": chart_data,
            "x_key": date_cols[0],
            "y_keys": y_keys,
            "colors": CHART_COLORS,
            "show_legend": n_numeric > 1,
            "show_grid": True,
        })
        # Add bar as alternative if not too many points
        if n_rows <= 30 and n_numeric == 1:
            charts.append({
                "chart_type": "bar",
                "title": _chart_title(question, "Bar Chart"),
                "description": f"{y_keys[0].replace('_',' ')} by period",
                "data": chart_data,
                "x_key": date_cols[0],
                "y_keys": y_keys[:1],
                "colors": CHART_COLORS,
                "show_legend": False,
                "show_grid": True,
            })
        return charts

    # Default: bar chart (handles categorical + multi-series)
    is_stacked = any(kw in question.lower() for kw in ["stacked","breakdown","composition","by currency","split by"])
    charts.append({
        "chart_type": "stacked_bar" if (is_stacked and n_numeric > 1) else "bar",
        "title": _chart_title(question, "Chart"),
        "description": f"{', '.join(k.replace('_',' ') for k in y_keys)} by {x_key.replace('_',' ')}",
        "data": chart_data,
        "x_key": x_key,
        "y_keys": y_keys,
        "colors": CHART_COLORS,
        "show_legend": n_numeric > 1,
        "show_grid": True,
        "stacked": is_stacked and n_numeric > 1,
    })

    # Add pie for comparison queries with ≤12 categories
    if n_numeric == 1 and n_rows <= 12 and x_key in label_cols:
        charts.append({
            "chart_type": "pie",
            "title": _chart_title(question, "Distribution"),
            "description": f"Share of {y_keys[0].replace('_',' ')} by {x_key.replace('_',' ')}",
            "data": chart_data,
            "name_key": x_key,
            "value_key": y_keys[0],
            "colors": CHART_COLORS,
            "show_legend": True,
        })

    return charts[:2]  # max 2 charts per query


def _chart_title(question: str, fallback: str) -> str:
    """Generate a short chart title from the question."""
    q = question.strip().rstrip("?").strip()
    # Truncate to ~50 chars
    if len(q) <= 50:
        return q
    # Try to get the first meaningful phrase
    for sep in [" by ", " from ", " using ", " between ", " for ", " in ", " of "]:
        idx = q.lower().find(sep)
        if idx > 15:
            return q[:idx].strip()
    return q[:50].strip() + "…"


def _universal_query(
    question: str,
    api_key: str,
    db: Session,
    use_sap: bool,
    max_retries: int = 3,
) -> Optional[Dict[str, Any]]:
    """
    Main engine: send full schema + question to GPT-4o, execute result,
    auto-retry with error feedback up to max_retries times.
    """
    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    schema = _build_schema_prompt()
    model = os.getenv("OPENAI_MODEL", "gpt-4o")
    fast_model = os.getenv("OPENAI_FAST_MODEL", "gpt-4o-mini")

    full_system = _SYSTEM_PROMPT_CORE + "\n\n" + schema
    messages = [
        {"role": "system", "content": full_system},
        {"role": "user", "content": f"Question: {question}\n\nGenerate the SQL:"},
    ]

    sql = ""
    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages, temperature=0.05, max_tokens=900,
            )
            raw = resp.choices[0].message.content or ""
            sql = _extract_sql(raw)
            if not sql:
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": "Provide SQL in a ```sql block."})
                continue

            logger.info(f"[universal] attempt {attempt+1}: {sql[:200]}")

            sess = None
            try:
                sess = get_sap_session() if use_sap else db
                data = _execute_sql(sess if use_sap else db, sql, question)
            finally:
                if use_sap and sess is not None:
                    try:
                        sess.close()
                    except Exception:
                        pass

            logger.info(f"[universal] success: {len(data)} rows")

            # ── Generate charts and summary in parallel ──────────────────────
            charts: List[Dict[str, Any]] = []
            summary = f"Query returned {len(data)} result(s)."

            if data:
                # Auto-generate chart specs from result data
                try:
                    charts = _auto_charts(question, sql, data)
                    logger.info(f"[universal] generated {len(charts)} chart(s)")
                except Exception as chart_err:
                    logger.warning(f"[universal] chart generation failed: {chart_err}")

                # Generate natural language summary
                try:
                    chart_note = f" {len(charts)} chart(s) generated." if charts else ""
                    sr = client.chat.completions.create(
                        model=fast_model,
                        messages=[
                            {"role": "system", "content": (
                                "You are a data analyst. Summarize database results in 2-4 clear, specific sentences. "
                                "Include key numbers, top values, and actionable insights. Be specific and concise."
                            )},
                            {"role": "user", "content": (
                                f"Question: {question}\n"
                                f"SQL: {sql[:300]}\n"
                                f"Results ({len(data)} rows, sample of first 10):\n{data[:10]}\n"
                                f"Write a 2-4 sentence summary:"
                            )},
                        ],
                        temperature=0.15, max_tokens=350,
                    )
                    summary = (sr.choices[0].message.content.strip() or summary) + chart_note
                except Exception:
                    pass
            else:
                summary = (
                    f"The query executed successfully but returned **0 rows**. "
                    f"This may mean no data matches your criteria, or the database "
                    f"may not have data for the specified period.\n\n"
                    f"**SQL executed:**\n```sql\n{sql}\n```"
                )

            result: Dict[str, Any] = {"sql": sql, "rowCount": len(data), "data": data, "summary": summary}
            if charts:
                result["charts"] = charts
            return result

        except Exception as err:
            err_msg = str(err)
            logger.warning(f"[universal] attempt {attempt+1} failed: {err_msg[:200]}")
            messages.append({"role": "assistant", "content": f"```sql\n{sql}\n```" if sql else "(no SQL)"})
            messages.append({
                "role": "user",
                "content": (
                    f"PostgreSQL error:\n```\n{err_msg[:500]}\n```\n\n"
                    "Fix the SQL. Common issues:\n"
                    "- SAP TEXT numeric cols need: SUM(CAST(NULLIF(TRIM(CAST(alias.\"col\" AS TEXT)),'') AS NUMERIC))\n"
                    "- SAP tables MUST be quoted: FROM \"VBRK\" AS k\n"
                    "- vbrp is stored lowercase but still needs quotes: FROM \"vbrp\" AS p\n"
                    "- SAP dates are TEXT YYYYMMDD — compare as strings, never CAST to DATE\n"
                    "- HAVING cannot reference SELECT aliases — repeat the full aggregate\n"
                    "- Check column names against the schema provided\n"
                    "Return ONLY the corrected SQL in a ```sql block."
                ),
            })

    logger.error(f"[universal] all {max_retries} attempts failed for: {question[:100]}")
    return None


def _followup_analysis(question: str, prev_q: str, prev_sql: str,
                       rows: List[Dict], api_key: str) -> str:
    from openai import OpenAI
    from ..services.schema_context_builder import build_schema_context
    client = OpenAI(api_key=api_key)

    schema_ctx = build_schema_context(
        question=f"{prev_q}\n{question}", focus_tables=None, max_tables=25, max_cols_per_table=40,
    )
    is_empty = len(rows) == 0
    prompt = (
        "You are a helpful SAP/database analyst.\n"
        "Rules: If rows are non-empty, answer from them. If empty or user wants to fix SQL, propose improved SQL.\n"
        "Proposed SQL must use only real table/column names from schema.\n"
        f"Schema:\n{schema_ctx}\n\n"
        f"Previous question:\n{prev_q}\n\n"
        f"Previous SQL:\n{prev_sql[:1500]}\n\n"
        f"Row sample ({len(rows)} rows):\n{rows[:20]}\n\n"
        f"Follow-up question:\n{question}\n\n"
        f"rows_empty={is_empty}"
    )
    resp = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1, max_tokens=900,
    )
    return (resp.choices[0].message.content or "").strip() or "Could not generate follow-up answer."


# ─── Router ───────────────────────────────────────────────────────────────────

@router.get("/api/query/health")
async def adaptive_query_health() -> Dict[str, Any]:
    s = _load_schema()
    return {"status": "ok", "tables": len(s), "columns": sum(len(v) for v in s.values())}


@router.get("/api/query/schema-diagnostics")
async def adaptive_query_schema_diagnostics() -> Dict[str, Any]:
    s = _load_schema()
    return {"status": "ok", "table_count": len(s),
            "column_count": sum(len(v) for v in s.values()),
            "tables": sorted(s.keys())}


@router.get("/api/query/adaptive")
async def get_query_adaptive() -> Dict[str, Any]:
    return {"error": "method_not_allowed", "message": "Use POST /api/query/adaptive"}


@router.post("/api/query/adaptive")
async def post_query_adaptive(
    question: str = Body(..., embed=True),
    tableHint: Optional[str] = Body(default=None, embed=True),
    contextData: Optional[Dict[str, Any]] = Body(default=None, embed=True),
    overrideSql: Optional[str] = Body(default=None, embed=True),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    q = (question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail='Send JSON: {"question": "..."}')
    if len(q) > 4000:
        raise HTTPException(status_code=400, detail="question_too_long (max 4000)")

    api_key = _get_openai_key()

    # ── Path 1: Execute user-provided SQL directly ──────────────────────────
    if overrideSql and overrideSql.strip():
        sql_up = overrideSql.upper().strip()
        if not sql_up.startswith("SELECT"):
            raise HTTPException(status_code=400, detail="overrideSql must be SELECT")
        for d in ["DELETE","UPDATE","DROP","ALTER","TRUNCATE","INSERT","CREATE","EXEC","GRANT","REVOKE"]:
            if re.search(r'\b' + d + r'\b', sql_up):
                raise HTTPException(status_code=400, detail=f"Forbidden keyword: {d}")
        sess = None
        try:
            sess = get_sap_session() if USE_SAP_DB_FOR_AI else db
            data = _execute_sql(sess if USE_SAP_DB_FOR_AI else db, overrideSql, q)
        finally:
            if USE_SAP_DB_FOR_AI and sess is not None:
                try: sess.close()
                except Exception: pass
        summary = f"Custom SQL executed. {len(data)} row(s) returned."
        try:
            from openai import OpenAI
            c = OpenAI(api_key=api_key)
            r = c.chat.completions.create(
                model=os.getenv("OPENAI_FAST_MODEL", "gpt-4o-mini"),
                messages=[{"role": "user", "content": f"SQL: {overrideSql[:400]}\nResults ({len(data)} rows): {data[:5]}\nSummarize in 2 sentences:"}],
                temperature=0.1, max_tokens=200,
            )
            summary = r.choices[0].message.content.strip() or summary
        except Exception: pass
        return {"sql": overrideSql, "rowCount": len(data), "data": data,
                "summary": summary, "tableHint": tableHint}

    # ── Path 2: Follow-up analysis ──────────────────────────────────────────
    if contextData and isinstance(contextData, dict):
        prev_q   = str(contextData.get("previousQuestion") or "").strip()
        prev_sql = str(contextData.get("previousSQL") or "").strip()
        rows_raw = contextData.get("data")
        rows_list: List[Dict[str, Any]] = rows_raw if isinstance(rows_raw, list) else []
        try:
            answer = _followup_analysis(q, prev_q, prev_sql, rows_list, api_key)
            return {"type": "analysis", "answer": answer}
        except Exception as e:
            raise HTTPException(status_code=500, detail={"error_code": "follow_up_failed", "message": str(e)})

    # ── Path 3: Universal NL → SQL → Execute ───────────────────────────────
    logger.info(f"[universal] question: {q[:120]}")
    try:
        result = _universal_query(q, api_key, db, USE_SAP_DB_FOR_AI, max_retries=3)
        if result:
            result["tableHint"] = tableHint
            return result
        raise RuntimeError("Universal engine: all retries failed")
    except Exception as univ_err:
        logger.warning(f"[universal] falling back to orchestrator: {univ_err}")
        try:
            from ..services.ai_analysis_orchestrator import run_ai_analysis_orchestrator, orchestrator_payload
            sap_sess = get_sap_session() if USE_SAP_DB_FOR_AI else None
            try:
                orch = run_ai_analysis_orchestrator(
                    api_key=api_key, user_id=0, user_query=q, db=db,
                    conversation_history=[], context_str="", sap_db=sap_sess,
                    time_scope="current", days=30, thread_id=None, query_mode="new",
                )
                payload = orchestrator_payload(orch)
            finally:
                if sap_sess is not None:
                    try: sap_sess.close()
                    except Exception: pass
            rows_out = payload.get("rows") or payload.get("rows_preview") or []
            out: Dict[str, Any] = {
                "sql": payload.get("sql") or "",
                "rowCount": len(rows_out),
                "data": rows_out,
                "tableHint": tableHint,
                "summary": payload.get("reply") or "Query completed.",
            }
            if payload.get("charts"):
                out["charts"] = payload["charts"]
            return out
        except Exception as orch_err:
            raise HTTPException(status_code=500, detail={
                "error_code": "query_failed",
                "message": str(orch_err),
                "hint": "Try specifying table names explicitly (e.g. 'from VBRK' or 'using invoice_v2_business_data').",
            })
