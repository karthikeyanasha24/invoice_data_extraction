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
from .invoice_v2_correction_service import InvoiceV2CorrectionService
from .file_service import read_file_from_storage

logger = logging.getLogger("zodiac-api.invoice_v2_validation")


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
        "total"
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
        Extract all fields from UBL XML:
        - Invoice header (number, dates, currency)
        - Customer details (ID, name, tax ID, address)
        - Supplier details (ID, name, tax ID)
        - Monetary totals (tax, subtotal, total)
        - Line items
        """
        logger.info("📋 Extracting invoice fields from XML...")
        
        try:
            # Parse XML
            parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
            root = etree.fromstring(xml_content.encode('utf-8'), parser)
            
            ns = self.UBL_NAMESPACES
            
            # Extract invoice header
            invoice_data = {
                "invoice_number": self._get_text(root, './/cbc:ID', ns),
                "issue_date": self._get_text(root, './/cbc:IssueDate', ns),
                "due_date": self._get_text(root, './/cbc:DueDate', ns),
                "currency": self._get_text(root, './/cbc:DocumentCurrencyCode', ns),
                "invoice_type_code": self._get_text(root, './/cbc:InvoiceTypeCode', ns),
            }
            
            # Extract customer (AccountingCustomerParty)
            customer_party = root.find('.//cac:AccountingCustomerParty/cac:Party', ns)
            if customer_party is not None:
                invoice_data.update({
                    "customer_id": self._get_text(customer_party, './/cbc:EndpointID', ns),
                    "customer_id_scheme": self._get_attribute(customer_party, './/cbc:EndpointID', 'schemeID', ns),
                    "customer_name": self._get_text(customer_party, './/cac:PartyName/cbc:Name', ns),
                    "customer_tax_id": self._get_text(customer_party, './/cac:PartyTaxScheme/cbc:CompanyID', ns),
                    "customer_legal_name": self._get_text(customer_party, './/cac:PartyLegalEntity/cbc:RegistrationName', ns),
                    "customer_address": self._extract_address(customer_party, ns),
                })
            
            # Extract supplier (AccountingSupplierParty)
            supplier_party = root.find('.//cac:AccountingSupplierParty/cac:Party', ns)
            if supplier_party is not None:
                invoice_data.update({
                    "supplier_id": self._get_text(supplier_party, './/cbc:EndpointID', ns),
                    "supplier_id_scheme": self._get_attribute(supplier_party, './/cbc:EndpointID', 'schemeID', ns),
                    "supplier_name": self._get_text(supplier_party, './/cac:PartyName/cbc:Name', ns),
                    "supplier_tax_id": self._get_text(supplier_party, './/cac:PartyTaxScheme/cbc:CompanyID', ns),
                    "supplier_legal_name": self._get_text(supplier_party, './/cac:PartyLegalEntity/cbc:RegistrationName', ns),
                    "supplier_address": self._extract_address(supplier_party, ns),
                })
            
            # Extract monetary totals
            legal_monetary = root.find('.//cac:LegalMonetaryTotal', ns)
            if legal_monetary is not None:
                invoice_data.update({
                    "subtotal": self._get_text(legal_monetary, './/cbc:TaxExclusiveAmount', ns),
                    "total": self._get_text(legal_monetary, './/cbc:TaxInclusiveAmount', ns),
                    "line_extension_amount": self._get_text(legal_monetary, './/cbc:LineExtensionAmount', ns),
                    "payable_amount": self._get_text(legal_monetary, './/cbc:PayableAmount', ns),
                })
            
            # Extract tax total
            tax_total = root.find('.//cac:TaxTotal', ns)
            if tax_total is not None:
                invoice_data["tax_amount"] = self._get_text(tax_total, './/cbc:TaxAmount', ns)
            
            # Extract line items
            line_items = []
            invoice_lines = root.findall('.//cac:InvoiceLine', ns)
            for line in invoice_lines:
                line_item = {
                    "id": self._get_text(line, './/cbc:ID', ns),
                    "quantity": self._get_text(line, './/cbc:InvoicedQuantity', ns),
                    "unit_code": self._get_attribute(line, './/cbc:InvoicedQuantity', 'unitCode', ns),
                    "line_amount": self._get_text(line, './/cbc:LineExtensionAmount', ns),
                    "item_name": self._get_text(line, './/cac:Item/cbc:Name', ns),
                    "item_description": self._get_text(line, './/cac:Item/cbc:Description', ns),
                    "price": self._get_text(line, './/cac:Price/cbc:PriceAmount', ns),
                }
                line_items.append(line_item)
            
            invoice_data["line_items"] = line_items
            invoice_data["line_items_count"] = len(line_items)
            
            logger.info(f"✅ Extracted {len(invoice_data)} fields")
            
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
