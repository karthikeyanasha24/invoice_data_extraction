"""
Invoice V2 Validation Service - AI-powered invoice validation with correction cache
"""
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from decimal import Decimal, InvalidOperation
from lxml import etree
from sqlalchemy.orm import Session

from ..models.invoice_v2_document import InvoiceV2Document
from ..models.invoice_v2_validated import InvoiceV2Validated
from ..models.invoice_v2_business_data import InvoiceV2BusinessData
from .invoice_v2_correction_service import InvoiceV2CorrectionService
from .invoice_v2_business_intelligence import InvoiceV2BusinessIntelligence
from .file_service import read_file_from_storage

logger = logging.getLogger("zodiac-api.invoice_v2_validation")

# UBL 2.0 namespaces for lightweight extraction (e.g. customer_id only)
_UBL_NS = {
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}


def extract_customer_id_from_xml(xml_bytes: bytes) -> Optional[str]:
    """
    Lightweight extraction of customer_id from UBL XML (AccountingCustomerParty).
    Returns None if not found or on parse error. Used to filter unvalidated docs for customer users.
    """
    try:
        parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
        root = etree.fromstring(xml_bytes, parser)
        customer_party = root.find(".//cac:AccountingCustomerParty/cac:Party", _UBL_NS)
        if customer_party is None:
            return None
        endpoint = customer_party.find(".//cbc:EndpointID", _UBL_NS)
        if endpoint is not None and endpoint.text:
            return endpoint.text.strip()
        return None
    except Exception as e:
        logger.debug("extract_customer_id_from_xml failed: %s", e)
        return None


class InvoiceV2ValidationService:
    """
    AI-powered invoice validation with correction cache integration.
    Extracts fields from UBL XML and validates business rules.
    """
    
    # Define required fields
    REQUIRED_FIELDS = [
        "invoice_number",
        "issue_date",
        "currency",
        "customer_id",
        "customer_name",
        "supplier_id",
        "supplier_name",
        "total",
        "tax_percentage"
    ]
    
    # UBL 2.0 Namespaces
    UBL_NAMESPACES = {
        'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
        'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
        'invoice': 'urn:oasis:names:specification:ubl:schema:xsd:Invoice-2'
    }
    
    def __init__(self, db: Session):
        self.db = db
        self.correction_service = InvoiceV2CorrectionService(db)
    
    async def validate_invoice(self, document: InvoiceV2Document) -> InvoiceV2Validated:
        """
        Main validation pipeline:
        1. Load and parse XML
        2. Extract all required fields
        3. Check for missing fields
        4. If missing fields found, check correction cache
        5. Apply cached corrections if available
        6. Validate field formats and business rules
        7. Determine success/failed status
        8. Save to v2_validated_invoices
        """
        logger.info(f"🔍 Starting validation for document ID: {document.id}")
        
        try:
            # Load XML content
            xml_content = await self._load_xml_content(document)
            
            # Extract invoice fields
            invoice_data = self.extract_invoice_fields(xml_content)
            
            # Check for missing required fields
            missing_fields = self._find_missing_fields(invoice_data)
            
            # Try to apply corrections from cache for missing fields
            if missing_fields and invoice_data.get("customer_id"):
                logger.info(f"⚠️ Found {len(missing_fields)} missing fields, checking correction cache...")
                invoice_data, missing_fields, correction_applied, correction_id = await self._apply_corrections_from_cache(
                    invoice_data, 
                    missing_fields
                )
            else:
                correction_applied = False
                correction_id = None
            
            # Validate field formats and business rules
            validation_errors = self.validate_field_formats(invoice_data)
            
            # Determine status
            status = "success" if len(missing_fields) == 0 and len(validation_errors) == 0 else "failed"
            
            # Create validation notes
            validation_notes = self._generate_validation_notes(missing_fields, validation_errors, correction_applied)
            
            # Create validated invoice record
            validated_invoice = InvoiceV2Validated(
                document_id=document.id,
                status=status,
                invoice_data=invoice_data,
                missing_fields=missing_fields if missing_fields else None,
                validation_errors=validation_errors if validation_errors else None,
                validation_notes=validation_notes,
                correction_applied=correction_applied,
                correction_cache_id=correction_id
            )
            
            self.db.add(validated_invoice)
            
            # Update document status
            document.validation_status = "validated"
            
            self.db.commit()
            self.db.refresh(validated_invoice)
            
            # Auto-save BI for dashboard when validation succeeds (products, industry, etc.)
            if status == "success" and document.user_id:
                try:
                    existing = self.db.query(InvoiceV2BusinessData).filter(
                        InvoiceV2BusinessData.validated_invoice_id == validated_invoice.id
                    ).first()
                    if not existing:
                        bi_service = InvoiceV2BusinessIntelligence()
                        bi_data = bi_service.extract_bi_data(validated_invoice)
                        user_id = getattr(document, "user_id", None) or bi_data.get("user_id")
                        if not user_id:
                            logger.warning("   BI auto-save skipped: no user_id")
                        else:
                            bi_record = InvoiceV2BusinessData(
                                validated_invoice_id=bi_data["validated_invoice_id"],
                                user_id=user_id,
                                customer_id=bi_data["customer"].get("id"),
                                customer_name=bi_data["customer"].get("name"),
                                customer_country=bi_data["customer"].get("country"),
                                supplier_id=bi_data["supplier"].get("id"),
                                supplier_name=bi_data["supplier"].get("name"),
                                products=bi_data["products"],
                                total_products_count=bi_data["total_products_count"],
                                total_amount=bi_data["financial"].get("total_amount"),
                                tax_amount=bi_data["financial"].get("tax_amount"),
                                currency=bi_data["financial"].get("currency"),
                                industry=bi_data["industry"],
                                industry_confidence=bi_data["industry_confidence"],
                                industry_keywords_matched=bi_data["industry_keywords_matched"],
                                invoice_date=bi_data["temporal"].get("invoice_date"),
                                fiscal_quarter=bi_data["temporal"].get("fiscal_quarter"),
                                fiscal_year=bi_data["temporal"].get("fiscal_year"),
                                season=bi_data["temporal"].get("season"),
                                current_stage=bi_data["lifecycle"].get("current_stage"),
                                stage_status=bi_data["lifecycle"].get("stage_status"),
                            )
                            self.db.add(bi_record)
                            self.db.commit()
                            logger.info(f"   BI data saved for dashboard (products: {bi_data['total_products_count']})")
                except Exception as bi_err:
                    logger.warning(f"   BI auto-save skipped: {bi_err}")
                    self.db.rollback()
            
            logger.info(f"✅ Validation completed: {status.upper()}")
            logger.info(f"   Missing fields: {len(missing_fields)}")
            logger.info(f"   Validation errors: {len(validation_errors)}")
            
            return validated_invoice
            
        except Exception as e:
            logger.error(f"❌ Validation failed: {e}")
            logger.exception(e)
            self.db.rollback()
            
            # Create failed validation record
            validated_invoice = InvoiceV2Validated(
                document_id=document.id,
                status="failed",
                invoice_data={},
                missing_fields=self.REQUIRED_FIELDS,
                validation_errors=[{"field": "general", "message": f"Validation error: {str(e)}"}],
                validation_notes=f"Critical validation error: {str(e)}"
            )
            
            self.db.add(validated_invoice)
            document.validation_status = "validated"
            self.db.commit()
            self.db.refresh(validated_invoice)
            
            return validated_invoice
    
    async def _load_xml_content(self, document: InvoiceV2Document) -> str:
        """Load XML content from storage"""
        try:
            # For blob storage, pass the blob URL directly
            if document.blob_xml_path:
                xml_bytes = await read_file_from_storage(
                    file_path=document.blob_xml_path,
                    blob_xml_path=document.blob_xml_path
                )
            elif document.xml_path:
                xml_bytes = await read_file_from_storage(
                    file_path=document.xml_path,
                    blob_xml_path=None
                )
            else:
                raise ValueError("No file path available for this document")
            
            # Convert bytes to string
            xml_content = xml_bytes.decode('utf-8')
            return xml_content
        except Exception as e:
            logger.error(f"❌ Failed to load XML: {e}")
            raise
    
    def extract_invoice_fields(self, xml_content: str) -> Dict[str, Any]:
        """
        Extract all fields from UBL XML (Hybrid Approach):
        - Invoice header (number, dates, currency, metadata)
        - Customer details (ID, name, tax ID, address, contact)
        - Supplier details (ID, name, tax ID, address, contact)
        - Monetary totals (tax, subtotal, total, allowances, charges)
        - Payment information (means, terms, account)
        - Tax breakdown (amount, percentage, category)
        - Delivery information
        - Order and document references
        - Line items (with product IDs, tax info, etc.)
        """
        logger.info("📋 Extracting invoice fields from XML...")
        
        try:
            # Parse XML
            parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
            root = etree.fromstring(xml_content.encode('utf-8'), parser)
            
            ns = self.UBL_NAMESPACES
            
            # Extract invoice header with metadata
            invoice_data = {
                "invoice_number": self._get_text(root, './/cbc:ID', ns),
                "issue_date": self._get_text(root, './/cbc:IssueDate', ns),
                "due_date": self._get_text(root, './/cbc:DueDate', ns),
                "currency": self._get_text(root, './/cbc:DocumentCurrencyCode', ns),
                "invoice_type_code": self._get_text(root, './/cbc:InvoiceTypeCode', ns),
                "customization_id": self._get_text(root, './/cbc:CustomizationID', ns),
                "profile_id": self._get_text(root, './/cbc:ProfileID', ns),
                "note": self._get_text(root, './/cbc:Note', ns),
                "accounting_cost": self._get_text(root, './/cbc:AccountingCost', ns),
                "buyer_reference": self._get_text(root, './/cbc:BuyerReference', ns),
            }
            
            # Extract invoice period
            invoice_period = root.find('.//cac:InvoicePeriod', ns)
            if invoice_period is not None:
                invoice_data["invoice_period_start"] = self._get_text(invoice_period, './/cbc:StartDate', ns)
                invoice_data["invoice_period_end"] = self._get_text(invoice_period, './/cbc:EndDate', ns)
            
            # Extract order and document references
            order_ref = root.find('.//cac:OrderReference', ns)
            if order_ref is not None:
                invoice_data["order_reference"] = self._get_text(order_ref, './/cbc:ID', ns)
                invoice_data["sales_order_id"] = self._get_text(order_ref, './/cbc:SalesOrderID', ns)
            
            invoice_data["contract_reference"] = self._get_text(root, './/cac:ContractDocumentReference/cbc:ID', ns)
            invoice_data["project_reference"] = self._get_text(root, './/cac:ProjectReference/cbc:ID', ns)
            
            # Extract customer (AccountingCustomerParty)
            customer_party = root.find('.//cac:AccountingCustomerParty/cac:Party', ns)
            if customer_party is not None:
                invoice_data.update({
                    "customer_id": self._get_text(customer_party, './/cbc:EndpointID', ns),
                    "customer_id_scheme": self._get_attribute(customer_party, './/cbc:EndpointID', 'schemeID', ns),
                    "customer_name": self._get_text(customer_party, './/cac:PartyName/cbc:Name', ns),
                    "customer_tax_id": self._get_text(customer_party, './/cac:PartyTaxScheme/cbc:CompanyID', ns),
                    "customer_legal_name": self._get_text(customer_party, './/cac:PartyLegalEntity/cbc:RegistrationName', ns),
                    "customer_company_legal_form": self._get_text(customer_party, './/cac:PartyLegalEntity/cbc:CompanyLegalForm', ns),
                    "customer_address": self._extract_address(customer_party, ns),
                })
                
                # Extract customer contact
                customer_contact = self._extract_party_contact(customer_party, ns)
                if customer_contact:
                    invoice_data["customer_contact_name"] = customer_contact.get("name")
                    invoice_data["customer_contact_telephone"] = customer_contact.get("telephone")
                    invoice_data["customer_contact_email"] = customer_contact.get("email")
            
            # Extract supplier (AccountingSupplierParty)
            supplier_party = root.find('.//cac:AccountingSupplierParty/cac:Party', ns)
            if supplier_party is not None:
                invoice_data.update({
                    "supplier_id": self._get_text(supplier_party, './/cbc:EndpointID', ns),
                    "supplier_id_scheme": self._get_attribute(supplier_party, './/cbc:EndpointID', 'schemeID', ns),
                    "supplier_name": self._get_text(supplier_party, './/cac:PartyName/cbc:Name', ns),
                    "supplier_tax_id": self._get_text(supplier_party, './/cac:PartyTaxScheme/cbc:CompanyID', ns),
                    "supplier_legal_name": self._get_text(supplier_party, './/cac:PartyLegalEntity/cbc:RegistrationName', ns),
                    "supplier_company_legal_form": self._get_text(supplier_party, './/cac:PartyLegalEntity/cbc:CompanyLegalForm', ns),
                    "supplier_address": self._extract_address(supplier_party, ns),
                })
                
                # Extract supplier contact
                supplier_contact = self._extract_party_contact(supplier_party, ns)
                if supplier_contact:
                    invoice_data["supplier_contact_name"] = supplier_contact.get("name")
                    invoice_data["supplier_contact_telephone"] = supplier_contact.get("telephone")
                    invoice_data["supplier_contact_email"] = supplier_contact.get("email")
            
            # Extract monetary totals (enhanced)
            legal_monetary = root.find('.//cac:LegalMonetaryTotal', ns)
            if legal_monetary is not None:
                invoice_data.update({
                    "line_extension_amount": self._get_text(legal_monetary, './/cbc:LineExtensionAmount', ns),
                    "subtotal": self._get_text(legal_monetary, './/cbc:TaxExclusiveAmount', ns),
                    "total": self._get_text(legal_monetary, './/cbc:TaxInclusiveAmount', ns),
                    "payable_amount": self._get_text(legal_monetary, './/cbc:PayableAmount', ns),
                    "allowance_total_amount": self._get_text(legal_monetary, './/cbc:AllowanceTotalAmount', ns),
                    "charge_total_amount": self._get_text(legal_monetary, './/cbc:ChargeTotalAmount', ns),
                    "prepaid_amount": self._get_text(legal_monetary, './/cbc:PrepaidAmount', ns),
                })
            
            # Extract tax breakdown (enhanced with percentage)
            tax_breakdown = self._extract_tax_breakdown(root, ns)
            invoice_data.update(tax_breakdown)
            
            # Extract payment information
            payment_info = self._extract_payment_info(root, ns)
            invoice_data.update(payment_info)
            
            # Extract delivery information
            delivery_info = self._extract_delivery_info(root, ns)
            invoice_data.update(delivery_info)
            
            # Extract allowances and charges
            allowances_charges = self._extract_allowances_charges(root, ns)
            if allowances_charges:
                invoice_data["allowances_charges"] = allowances_charges
            
            # Extract line items (enhanced with product IDs and tax info)
            line_items = []
            invoice_lines = root.findall('.//cac:InvoiceLine', ns)
            for line in invoice_lines:
                line_item = {
                    "id": self._get_text(line, './/cbc:ID', ns),
                    "line_note": self._get_text(line, './/cbc:Note', ns),
                    "quantity": self._get_text(line, './/cbc:InvoicedQuantity', ns),
                    "unit_code": self._get_attribute(line, './/cbc:InvoicedQuantity', 'unitCode', ns),
                    "line_amount": self._get_text(line, './/cbc:LineExtensionAmount', ns),
                    "accounting_cost": self._get_text(line, './/cbc:AccountingCost', ns),
                    "order_line_reference": self._get_text(line, './/cac:OrderLineReference/cbc:LineID', ns),
                    "item_name": self._get_text(line, './/cac:Item/cbc:Name', ns),
                    "item_description": self._get_text(line, './/cac:Item/cbc:Description', ns),
                    "buyer_item_id": self._get_text(line, './/cac:Item/cac:BuyersItemIdentification/cbc:ID', ns),
                    "seller_item_id": self._get_text(line, './/cac:Item/cac:SellersItemIdentification/cbc:ID', ns),
                    "standard_item_id": self._get_text(line, './/cac:Item/cac:StandardItemIdentification/cbc:ID', ns),
                    "origin_country": self._get_text(line, './/cac:Item/cac:OriginCountry/cbc:IdentificationCode', ns),
                    "tax_category": self._get_text(line, './/cac:Item/cac:ClassifiedTaxCategory/cbc:ID', ns),
                    "tax_percent": self._get_text(line, './/cac:Item/cac:ClassifiedTaxCategory/cbc:Percent', ns),
                    "price": self._get_text(line, './/cac:Price/cbc:PriceAmount', ns),
                }
                line_items.append(line_item)
            
            invoice_data["line_items"] = line_items
            invoice_data["line_items_count"] = len(line_items)
            
            logger.info(f"✅ Extracted {len(invoice_data)} fields (hybrid approach)")
            
            return invoice_data
            
        except Exception as e:
            logger.error(f"❌ Failed to extract invoice fields: {e}")
            logger.exception(e)
            return {}
    
    def _get_text(self, element, xpath: str, namespaces: dict) -> Optional[str]:
        """Safely extract text from XML element"""
        try:
            elem = element.find(xpath, namespaces)
            if elem is not None and elem.text:
                return elem.text.strip()
        except Exception:
            pass
        return None
    
    def _get_attribute(self, element, xpath: str, attr_name: str, namespaces: dict) -> Optional[str]:
        """Safely extract attribute from XML element"""
        try:
            elem = element.find(xpath, namespaces)
            if elem is not None:
                return elem.get(attr_name)
        except Exception:
            pass
        return None
    
    def _extract_address(self, party_element, namespaces: dict) -> Optional[Dict[str, str]]:
        """Extract postal address from party element"""
        try:
            address_elem = party_element.find('.//cac:PostalAddress', namespaces)
            if address_elem is not None:
                return {
                    "street": self._get_text(address_elem, './/cbc:StreetName', namespaces),
                    "additional_street": self._get_text(address_elem, './/cbc:AdditionalStreetName', namespaces),
                    "city": self._get_text(address_elem, './/cbc:CityName', namespaces),
                    "postal_zone": self._get_text(address_elem, './/cbc:PostalZone', namespaces),
                    "country": self._get_text(address_elem, './/cac:Country/cbc:IdentificationCode', namespaces),
                }
        except Exception:
            pass
        return None
    
    def _extract_party_contact(self, party_element, namespaces: dict) -> Optional[Dict[str, str]]:
        """Extract contact information from party element"""
        try:
            contact_elem = party_element.find('.//cac:Contact', namespaces)
            if contact_elem is not None:
                return {
                    "name": self._get_text(contact_elem, './/cbc:Name', namespaces),
                    "telephone": self._get_text(contact_elem, './/cbc:Telephone', namespaces),
                    "email": self._get_text(contact_elem, './/cbc:ElectronicMail', namespaces),
                }
        except Exception:
            pass
        return None
    
    def _extract_payment_info(self, root, namespaces: dict) -> Dict[str, Any]:
        """Extract payment means and terms"""
        payment_info = {}
        try:
            payment_means = root.find('.//cac:PaymentMeans', namespaces)
            if payment_means is not None:
                payment_info["payment_means_code"] = self._get_text(payment_means, './/cbc:PaymentMeansCode', namespaces)
                payment_info["payment_means_name"] = self._get_attribute(payment_means, './/cbc:PaymentMeansCode', 'name', namespaces)
                payment_info["payment_id"] = self._get_text(payment_means, './/cbc:PaymentID', namespaces)
                
                # Extract financial account
                financial_account = payment_means.find('.//cac:PayeeFinancialAccount', namespaces)
                if financial_account is not None:
                    payment_info["payee_financial_account"] = {
                        "account_id": self._get_text(financial_account, './/cbc:ID', namespaces),
                        "account_name": self._get_text(financial_account, './/cbc:Name', namespaces),
                        "bank_id": self._get_text(financial_account, './/cac:FinancialInstitutionBranch/cbc:ID', namespaces),
                    }
            
            # Extract payment terms
            payment_terms = root.find('.//cac:PaymentTerms', namespaces)
            if payment_terms is not None:
                payment_info["payment_terms"] = self._get_text(payment_terms, './/cbc:Note', namespaces)
                
        except Exception as e:
            logger.warning(f"Could not extract payment info: {e}")
        
        return payment_info
    
    def _extract_tax_breakdown(self, root, namespaces: dict) -> Dict[str, Any]:
        """Extract full tax breakdown including percentage"""
        tax_info = {}
        try:
            tax_total = root.find('.//cac:TaxTotal', namespaces)
            if tax_total is not None:
                tax_info["tax_amount"] = self._get_text(tax_total, './/cbc:TaxAmount', namespaces)
                
                # Extract tax subtotal details
                tax_subtotal = tax_total.find('.//cac:TaxSubtotal', namespaces)
                if tax_subtotal is not None:
                    tax_info["taxable_amount"] = self._get_text(tax_subtotal, './/cbc:TaxableAmount', namespaces)
                    
                    # Extract tax category
                    tax_category = tax_subtotal.find('.//cac:TaxCategory', namespaces)
                    if tax_category is not None:
                        tax_info["tax_category_id"] = self._get_text(tax_category, './/cbc:ID', namespaces)
                        tax_info["tax_percentage"] = self._get_text(tax_category, './/cbc:Percent', namespaces)
                        
                        # Extract tax scheme
                        tax_scheme = tax_category.find('.//cac:TaxScheme', namespaces)
                        if tax_scheme is not None:
                            tax_info["tax_scheme"] = self._get_text(tax_scheme, './/cbc:ID', namespaces)
        except Exception as e:
            logger.warning(f"Could not extract tax breakdown: {e}")
        
        return tax_info
    
    def _extract_allowances_charges(self, root, namespaces: dict) -> List[Dict[str, Any]]:
        """Extract allowance/charge array"""
        allowances_charges = []
        try:
            ac_elements = root.findall('.//cac:AllowanceCharge', namespaces)
            for ac in ac_elements:
                item = {
                    "charge_indicator": self._get_text(ac, './/cbc:ChargeIndicator', namespaces),
                    "reason_code": self._get_text(ac, './/cbc:AllowanceChargeReasonCode', namespaces),
                    "reason": self._get_text(ac, './/cbc:AllowanceChargeReason', namespaces),
                    "multiplier": self._get_text(ac, './/cbc:MultiplierFactorNumeric', namespaces),
                    "amount": self._get_text(ac, './/cbc:Amount', namespaces),
                    "base_amount": self._get_text(ac, './/cbc:BaseAmount', namespaces),
                }
                allowances_charges.append(item)
        except Exception as e:
            logger.warning(f"Could not extract allowances/charges: {e}")
        
        return allowances_charges
    
    def _extract_delivery_info(self, root, namespaces: dict) -> Dict[str, Any]:
        """Extract delivery details"""
        delivery_info = {}
        try:
            delivery = root.find('.//cac:Delivery', namespaces)
            if delivery is not None:
                delivery_info["delivery_date"] = self._get_text(delivery, './/cbc:ActualDeliveryDate', namespaces)
                
                # Extract delivery location
                delivery_location = delivery.find('.//cac:DeliveryLocation', namespaces)
                if delivery_location is not None:
                    delivery_info["delivery_location_id"] = self._get_text(delivery_location, './/cbc:ID', namespaces)
                    
                    # Extract delivery address
                    address_elem = delivery_location.find('.//cac:Address', namespaces)
                    if address_elem is not None:
                        delivery_info["delivery_address"] = {
                            "street": self._get_text(address_elem, './/cbc:StreetName', namespaces),
                            "additional_street": self._get_text(address_elem, './/cbc:AdditionalStreetName', namespaces),
                            "city": self._get_text(address_elem, './/cbc:CityName', namespaces),
                            "postal_zone": self._get_text(address_elem, './/cbc:PostalZone', namespaces),
                            "country": self._get_text(address_elem, './/cac:Country/cbc:IdentificationCode', namespaces),
                        }
                
                # Extract delivery party
                delivery_party = delivery.find('.//cac:DeliveryParty', namespaces)
                if delivery_party is not None:
                    delivery_info["delivery_party_name"] = self._get_text(delivery_party, './/cac:PartyName/cbc:Name', namespaces)
                    
        except Exception as e:
            logger.warning(f"Could not extract delivery info: {e}")
        
        return delivery_info
    
    def _find_missing_fields(self, invoice_data: Dict[str, Any]) -> List[str]:
        """Find missing required fields"""
        missing = []
        for field in self.REQUIRED_FIELDS:
            value = invoice_data.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                missing.append(field)
        return missing
    
    async def _apply_corrections_from_cache(
        self, 
        invoice_data: Dict[str, Any], 
        missing_fields: List[str]
    ) -> Tuple[Dict[str, Any], List[str], bool, Optional[str]]:
        """
        Apply corrections from cache for missing fields.
        Returns: (updated_invoice_data, remaining_missing_fields, correction_applied, correction_id)
        """
        customer_id = invoice_data.get("customer_id")
        if not customer_id:
            return invoice_data, missing_fields, False, None
        
        corrections_applied = []
        correction_id = None
        
        for field_name in list(missing_fields):
            # Find correction in cache
            correction = self.correction_service.find_correction(customer_id, field_name)
            
            if correction:
                logger.info(f"✨ Applying cached correction for field: {field_name}")
                invoice_data[field_name] = correction.field_value
                missing_fields.remove(field_name)
                corrections_applied.append(field_name)
                correction_id = correction.id
                
                # Mark success
                self.correction_service.mark_success(correction.id)
        
        if corrections_applied:
            logger.info(f"✅ Applied {len(corrections_applied)} corrections from cache: {corrections_applied}")
            self.db.commit()
        
        return invoice_data, missing_fields, len(corrections_applied) > 0, correction_id
    
    def validate_field_formats(self, invoice_data: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Validate business rules:
        - Date formats (ISO 8601)
        - Currency codes (3-letter)
        - Amount calculations (subtotal + tax = total)
        - Required field presence
        """
        errors = []
        
        # Validate date format
        for date_field in ["issue_date", "due_date"]:
            if date_field in invoice_data and invoice_data[date_field]:
                try:
                    datetime.strptime(invoice_data[date_field], "%Y-%m-%d")
                except ValueError:
                    errors.append({
                        "field": date_field,
                        "message": f"Invalid date format. Expected YYYY-MM-DD, got: {invoice_data[date_field]}"
                    })
        
        # Validate currency code (3 letters)
        if "currency" in invoice_data and invoice_data["currency"]:
            if len(invoice_data["currency"]) != 3:
                errors.append({
                    "field": "currency",
                    "message": f"Invalid currency code. Expected 3-letter code, got: {invoice_data['currency']}"
                })
        
        # Validate numeric amounts
        for amount_field in ["subtotal", "total", "tax_amount"]:
            if amount_field in invoice_data and invoice_data[amount_field]:
                try:
                    Decimal(invoice_data[amount_field])
                except (InvalidOperation, ValueError):
                    errors.append({
                        "field": amount_field,
                        "message": f"Invalid numeric value: {invoice_data[amount_field]}"
                    })
        
        # Validate calculation: subtotal + tax = total (with tolerance)
        try:
            if all(k in invoice_data and invoice_data[k] for k in ["subtotal", "tax_amount", "total"]):
                subtotal = Decimal(invoice_data["subtotal"])
                tax = Decimal(invoice_data["tax_amount"])
                total = Decimal(invoice_data["total"])
                calculated_total = subtotal + tax
                
                # Allow 0.01 tolerance for rounding
                if abs(calculated_total - total) > Decimal("0.01"):
                    errors.append({
                        "field": "total",
                        "message": f"Amount mismatch: subtotal({subtotal}) + tax({tax}) = {calculated_total}, but total is {total}"
                    })
        except Exception as e:
            logger.warning(f"Could not validate amount calculation: {e}")
        
        return errors
    
    def _generate_validation_notes(
        self, 
        missing_fields: List[str], 
        validation_errors: List[Dict[str, str]], 
        correction_applied: bool
    ) -> str:
        """Generate human-readable validation notes"""
        notes = []
        
        if not missing_fields and not validation_errors:
            notes.append("✅ All required fields extracted and validated successfully")
        
        if missing_fields:
            notes.append(f"⚠️ Missing {len(missing_fields)} required field(s): {', '.join(missing_fields)}")
        
        if validation_errors:
            notes.append(f"⚠️ Found {len(validation_errors)} validation error(s)")
        
        if correction_applied:
            notes.append("✨ Corrections applied from cache")
        
        return " | ".join(notes)
