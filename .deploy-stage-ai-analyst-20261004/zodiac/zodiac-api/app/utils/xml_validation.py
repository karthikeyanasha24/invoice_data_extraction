import xml.etree.ElementTree as ET
from typing import Optional, Union
from ..services.file_service import read_file_from_storage
import logging
import asyncio
from lxml import etree

logger = logging.getLogger("zodiac.xml_utils")


def validate_xml_structure_early(xml_content: str) -> tuple[bool, str, list[str]]:
    """Quick structural validation before full processing.
    
    Fast-fail validation that checks for required fields without deep validation.
    This prevents invoices from hanging during processing by catching structural
    issues early.
    
    Args:
        xml_content: Raw XML content as string
    
    Returns:
        Tuple of (is_valid, error_message, missing_fields)
        - is_valid: True if structure is valid, False otherwise
        - error_message: Descriptive error message if validation fails
        - missing_fields: List of missing required fields
    """
    missing_fields = []
    
    try:
        logger.info("🔍 ===== EARLY STRUCTURE VALIDATION =====")
        logger.info(f"📊 XML content length: {len(xml_content)} bytes")
        
        # Parse XML with timeout protection (already handled by caller)
        try:
            parser = etree.XMLParser(recover=False, resolve_entities=False, no_network=True)
            root = etree.fromstring(xml_content.encode('utf-8'), parser)
            logger.info("✅ XML is well-formed")
        except etree.XMLSyntaxError as e:
            error_msg = f"XML is not well-formed: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return False, error_msg, ["well-formed XML"]
        except Exception as e:
            error_msg = f"XML parsing error: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return False, error_msg, ["parseable XML"]
        
        # Define namespaces for UBL and CFDI
        ubl_namespaces = {
            'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
            'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'
        }
        cfdi_namespaces = {
            'cfdi': 'http://www.sat.gob.mx/cfd/4',
            'cfdi3': 'http://www.sat.gob.mx/cfd/3',
        }
        
        # Detect format (UBL or CFDI)
        is_ubl = root.tag.endswith('Invoice') or root.find('.//cac:AccountingSupplierParty', ubl_namespaces) is not None
        is_cfdi = root.tag.endswith('Comprobante') or root.find('.//cfdi:Comprobante', cfdi_namespaces) is not None
        
        if not is_cfdi:
            is_cfdi = root.find('.//cfdi3:Comprobante', cfdi_namespaces) is not None
        
        logger.info(f"📋 Detected format: {'UBL' if is_ubl else 'CFDI' if is_cfdi else 'UNKNOWN'}")
        
        if is_ubl:
            # Validate UBL structure
            logger.info("🔍 Checking UBL required elements...")
            
            # Check for Invoice ID
            invoice_id = root.find('.//cbc:ID', ubl_namespaces)
            if invoice_id is None or not invoice_id.text or not invoice_id.text.strip():
                missing_fields.append("Invoice ID (cbc:ID)")
                logger.warning("⚠️ Missing Invoice ID")
            
            # Check for AccountingSupplierParty
            supplier_party = root.find('.//cac:AccountingSupplierParty', ubl_namespaces)
            if supplier_party is None:
                missing_fields.append("AccountingSupplierParty")
                logger.warning("⚠️ Missing AccountingSupplierParty")
            else:
                # Check for Supplier EndpointID or CompanyID
                supplier_endpoint = supplier_party.find('.//cbc:EndpointID', ubl_namespaces)
                supplier_company_id = supplier_party.find('.//cac:PartyLegalEntity/cbc:CompanyID', ubl_namespaces)
                if (supplier_endpoint is None or not supplier_endpoint.text or not supplier_endpoint.text.strip()) and \
                   (supplier_company_id is None or not supplier_company_id.text or not supplier_company_id.text.strip()):
                    missing_fields.append("Supplier EndpointID or CompanyID")
                    logger.warning("⚠️ Missing Supplier identifier")
            
            # Check for AccountingCustomerParty
            customer_party = root.find('.//cac:AccountingCustomerParty', ubl_namespaces)
            if customer_party is None:
                missing_fields.append("AccountingCustomerParty")
                logger.warning("⚠️ Missing AccountingCustomerParty")
            else:
                # Check for Customer EndpointID or CompanyID
                customer_endpoint = customer_party.find('.//cbc:EndpointID', ubl_namespaces)
                customer_company_id = customer_party.find('.//cac:PartyLegalEntity/cbc:CompanyID', ubl_namespaces)
                if (customer_endpoint is None or not customer_endpoint.text or not customer_endpoint.text.strip()) and \
                   (customer_company_id is None or not customer_company_id.text or not customer_company_id.text.strip()):
                    missing_fields.append("Customer EndpointID or CompanyID")
                    logger.warning("⚠️ Missing Customer identifier")
            
            # Check for IssueDate
            issue_date = root.find('.//cbc:IssueDate', ubl_namespaces)
            if issue_date is None or not issue_date.text or not issue_date.text.strip():
                missing_fields.append("Issue Date (cbc:IssueDate)")
                logger.warning("⚠️ Missing Issue Date")
        
        elif is_cfdi:
            # Validate CFDI structure
            logger.info("🔍 Checking CFDI required elements...")
            
            # Find Comprobante element (CFDI 4.0 or 3.3)
            comprobante = root if root.tag.endswith('Comprobante') else root.find('.//cfdi:Comprobante', cfdi_namespaces)
            if comprobante is None:
                comprobante = root.find('.//cfdi3:Comprobante', cfdi_namespaces)
            
            if comprobante is None:
                missing_fields.append("Comprobante root element")
                logger.warning("⚠️ Missing Comprobante element")
            else:
                # Check for Folio (Invoice number)
                folio = comprobante.get('Folio')
                if not folio or not folio.strip():
                    missing_fields.append("Folio (Invoice number)")
                    logger.warning("⚠️ Missing Folio")
                
                # Check for Fecha (Issue date)
                fecha = comprobante.get('Fecha')
                if not fecha or not fecha.strip():
                    missing_fields.append("Fecha (Issue date)")
                    logger.warning("⚠️ Missing Fecha")
        
        else:
            # Unknown format
            logger.warning("⚠️ Could not detect UBL or CFDI format")
            missing_fields.append("Recognized XML format (UBL or CFDI)")
        
        # Determine if validation passed
        if missing_fields:
            error_msg = f"XML structure validation failed. Missing required fields: {', '.join(missing_fields)}"
            logger.error(f"❌ {error_msg}")
            return False, error_msg, missing_fields
        
        logger.info("✅ XML structure validation passed - all required fields present")
        return True, "XML structure is valid", []
    
    except Exception as e:
        error_msg = f"Error during structure validation: {str(e)}"
        logger.error(f"❌ {error_msg}")
        logger.exception(e)
        return False, error_msg, ["structure validation"]


def validate_xml(file_path: Union[str, dict], strict_validation: bool = False) -> tuple[bool, Optional[str], list[str]]:
    """Validate XML file structure - core well-formed check + optional enhanced validation with warnings

    Args:
        file_path: Path to the XML file to validate
        strict_validation: If True, treats validation issues as errors (default: False, issues are warnings only)

    Returns:
        Tuple of (is_valid, message, warnings)
    """
    logger.info(f"🔍 validate_xml: Starting XML validation for {file_path}")
    logger.info(f"📊 validate_xml: Strict validation mode: {strict_validation}")
    warnings = []

    try:
        logger.info(f"📄 validate_xml: Reading and parsing XML file...")

        # Handle blob storage vs local storage
        if isinstance(file_path, dict):
            # This is a blob response, we need to read the content differently
            logger.info(f"🔍 validate_xml: Detected blob storage response")
            try:
                # Use requests to download the file content
                import requests
                download_url = file_path.get('url', str(file_path))
                logger.info(
                    f"🌐 validate_xml: Downloading from blob URL: {download_url}")
                response = requests.get(download_url)
                response.raise_for_status()
                file_content = response.content
                logger.info(
                    f"✅ validate_xml: Downloaded {len(file_content)} bytes from blob")

                if len(file_content) == 0:
                    error_msg = "XML file is empty"
                    logger.error(f"❌ validate_xml: {error_msg}")
                    return False, error_msg, warnings

                # Parse XML from content
                root = ET.fromstring(file_content)
                logger.info(
                    f"✅ validate_xml: Core XML parsing successful - file is well-formed")

                # CRITICAL VALIDATION: Check for sender and receiver IDs (required, fails if missing)
                logger.info(
                    f"🔍 validate_xml: Running critical sender/receiver ID validation...")
                ids_valid, ids_error = validate_sender_receiver_ids(root)
                if not ids_valid:
                    error_msg = f"Sender/Receiver ID validation failed: {ids_error}"
                    logger.error(f"❌ validate_xml: {error_msg}")
                    return False, error_msg, warnings

            except Exception as e:
                logger.error(
                    f"❌ validate_xml: Failed to download/parse from blob: {e}")
                return False, f"Failed to download/parse XML from blob storage: {str(e)}", warnings
        else:
            # This is a local file path
            logger.info(f"🔍 validate_xml: Detected local file path")
            import os
            if not os.path.exists(file_path):
                error_msg = f"XML file not found: {file_path}"
                logger.error(f"❌ validate_xml: {error_msg}")
                return False, error_msg, warnings

            file_size = os.path.getsize(file_path)
            logger.info(f"📊 validate_xml: File size: {file_size} bytes")

            if file_size == 0:
                error_msg = "XML file is empty"
                logger.error(f"❌ validate_xml: {error_msg}")
                return False, error_msg, warnings

            # CORE VALIDATION: Check if XML is well-formed (matches old API behavior)
            tree = ET.parse(file_path)
            root = tree.getroot()
            logger.info(
                f"✅ validate_xml: Core XML parsing successful - file is well-formed")

        # CRITICAL VALIDATION: Check for sender and receiver IDs (required, fails if missing)
        logger.info(
            f"🔍 validate_xml: Running critical sender/receiver ID validation...")
        ids_valid, ids_error = validate_sender_receiver_ids(root)
        if not ids_valid:
            error_msg = f"Sender/Receiver ID validation failed: {ids_error}"
            logger.error(f"❌ validate_xml: {error_msg}")
            return False, error_msg, warnings

        # ENHANCED VALIDATION: Always run optional checks (warnings only, non-blocking)
        logger.info(
            f"🔍 validate_xml: Running optional enhanced validation checks...")
        validation_warnings = perform_enhanced_xml_validation(
            root, strict_validation)
        warnings.extend(validation_warnings)

        # If strict validation is enabled and there are validation warnings, treat them as errors
        if strict_validation and validation_warnings:
            error_msg = f"Strict validation failed: {'; '.join(validation_warnings)}"
            logger.error(f"❌ validate_xml: {error_msg}")
            return False, error_msg, warnings

        logger.info(
            f"✅ validate_xml: XML validation completed with {len(warnings)} warnings")
        return True, "XML validation passed - file is well-formed", warnings

    except ET.ParseError as e:
        error_msg = f"XML parsing error: {str(e)}"
        logger.error(f"❌ validate_xml: Parse error - {error_msg}")
        return False, error_msg, []
    except Exception as e:
        error_msg = f"XML validation error: {str(e)}"
        logger.error(f"❌ validate_xml: Unexpected error - {error_msg}")
        return False, error_msg, []


def validate_sender_receiver_ids(root) -> tuple[bool, Optional[str]]:
    """Validate that sender (supplier) and receiver (customer) IDs are present in XML

    Args:
        root: XML root element

    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if both IDs are present and non-empty, False otherwise
        - error_message: Error message if validation fails, None if valid
    """
    try:
        namespaces = {
            'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
            'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'
        }

        # Check for sender (supplier) EndpointID
        supplier_party = root.find(
            './/cac:AccountingSupplierParty', namespaces)
        if supplier_party is None:
            return False, "Missing AccountingSupplierParty element"

        sender_endpoint_id = supplier_party.find(
            './/cbc:EndpointID', namespaces)
        sender_id = None
        if sender_endpoint_id is not None:
            sender_id = sender_endpoint_id.text.strip() if sender_endpoint_id.text else None

        # Also check CompanyID as fallback
        if not sender_id:
            sender_company_id = supplier_party.find(
                './/cac:PartyLegalEntity/cbc:CompanyID', namespaces)
            if sender_company_id is not None and sender_company_id.text:
                sender_id = sender_company_id.text.strip()

        # Check for receiver (customer) EndpointID
        customer_party = root.find(
            './/cac:AccountingCustomerParty', namespaces)
        if customer_party is None:
            return False, "Missing AccountingCustomerParty element"

        receiver_endpoint_id = customer_party.find(
            './/cbc:EndpointID', namespaces)
        receiver_id = None
        if receiver_endpoint_id is not None:
            receiver_id = receiver_endpoint_id.text.strip(
            ) if receiver_endpoint_id.text else None

        # Also check CompanyID as fallback
        if not receiver_id:
            receiver_company_id = customer_party.find(
                './/cac:PartyLegalEntity/cbc:CompanyID', namespaces)
            if receiver_company_id is not None and receiver_company_id.text:
                receiver_id = receiver_company_id.text.strip()

        # Validate both IDs are present
        errors = []
        if not sender_id:
            errors.append(
                "Sender ID (Supplier EndpointID or CompanyID) is missing or empty")
        if not receiver_id:
            errors.append(
                "Receiver ID (Customer EndpointID or CompanyID) is missing or empty")

        if errors:
            error_message = "Critical validation failed: " + "; ".join(errors)
            logger.error(
                f"❌ Sender/Receiver ID validation failed: {error_message}")
            return False, error_message

        logger.info(
            f"✅ Sender/Receiver ID validation passed - Sender: {sender_id}, Receiver: {receiver_id}")
        return True, None

    except Exception as e:
        error_message = f"Error validating sender/receiver IDs: {str(e)}"
        logger.error(f"❌ {error_message}")
        return False, error_message


def perform_enhanced_xml_validation(root, strict_validation: bool = False) -> list[str]:
    """Perform enhanced XML validation and return warnings (non-blocking)

    Args:
        root: XML root element
        strict_validation: If True, performs additional strict content validation

    Returns:
        List of validation warning messages
    """
    warnings = []

    try:
        # Check for UBL namespace elements (optional warning)
        namespaces = {
            'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
            'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2'
        }

        # Check for common UBL invoice elements
        invoice_id = root.find('.//cbc:ID', namespaces)
        if invoice_id is None:
            warnings.append(
                "⚠️ No UBL Invoice ID (cbc:ID) found - may affect conversion")

        issue_date = root.find('.//cbc:IssueDate', namespaces)
        if issue_date is None:
            warnings.append(
                "⚠️ No UBL Issue Date (cbc:IssueDate) found - may affect conversion")

        payable_amount = root.find(
            './/cac:LegalMonetaryTotal/cbc:PayableAmount', namespaces)
        if payable_amount is None:
            warnings.append(
                "⚠️ No UBL Payable Amount found - may affect conversion")

        supplier_party = root.find(
            './/cac:AccountingSupplierParty', namespaces)
        if supplier_party is None:
            warnings.append(
                "⚠️ No UBL Supplier Party found - may affect conversion")

        customer_party = root.find(
            './/cac:AccountingCustomerParty', namespaces)
        if customer_party is None:
            warnings.append(
                "⚠️ No UBL Customer Party found - may affect conversion")

        # Check for invoice lines
        invoice_lines = root.findall('.//cac:InvoiceLine', namespaces)
        if not invoice_lines:
            warnings.append(
                "⚠️ No UBL Invoice Lines found - may affect conversion")

        # STRICT VALIDATION: Always run strict content validation, return as warnings
        logger.info(
            f"🔍 Enhanced validation: Running strict content validation...")
        strict_warnings = perform_strict_content_validation(root, namespaces)
        warnings.extend(strict_warnings)
        logger.info(
            f"🔍 Enhanced validation: Strict validation completed with {len(strict_warnings)} warnings")

        logger.info(
            f"🔍 Enhanced validation completed with {len(warnings)} warnings")

    except Exception as e:
        logger.warning(f"⚠️ Enhanced validation error: {e}")
        warnings.append(f"⚠️ Enhanced validation error: {e}")

    return warnings


def perform_strict_content_validation(root, namespaces) -> list[str]:
    """Perform strict content validation on XML elements (warnings only)

    Args:
        root: XML root element
        namespaces: XML namespace mapping

    Returns:
        List of strict validation warning messages
    """
    warnings = []

    try:
        logger.info(
            f"🔍 Strict validation: Checking element content and data types...")

        # Check Invoice ID content
        invoice_id = root.find('.//cbc:ID', namespaces)
        if invoice_id is not None and invoice_id.text:
            id_value = invoice_id.text.strip()
            if len(id_value) < 1:
                warnings.append("⚠️ Invoice ID is empty")
            elif len(id_value) > 100:
                warnings.append("⚠️ Invoice ID is too long (>100 characters)")

        # Check Issue Date content
        issue_date = root.find('.//cbc:IssueDate', namespaces)
        if issue_date is not None and issue_date.text:
            date_value = issue_date.text.strip()
            if len(date_value) < 1:
                warnings.append("⚠️ Issue Date is empty")
            else:
                # Try to parse as date
                try:
                    from datetime import datetime
                    datetime.strptime(date_value, "%Y-%m-%d")
                except ValueError:
                    warnings.append(
                        "⚠️ Issue Date format may be invalid (expected YYYY-MM-DD)")

        # Check Payable Amount content
        payable_amount = root.find(
            './/cac:LegalMonetaryTotal/cbc:PayableAmount', namespaces)
        if payable_amount is not None and payable_amount.text:
            amount_value = payable_amount.text.strip()
            if len(amount_value) < 1:
                warnings.append("⚠️ Payable Amount is empty")
            else:
                # Try to parse as decimal
                try:
                    float(amount_value)
                except ValueError:
                    warnings.append(
                        "⚠️ Payable Amount format may be invalid (expected decimal number)")

        # Check Supplier Name content
        supplier_name = root.find(
            './/cac:AccountingSupplierParty//cbc:Name', namespaces)
        if supplier_name is not None and supplier_name.text:
            name_value = supplier_name.text.strip()
            if len(name_value) < 1:
                warnings.append("⚠️ Supplier Name is empty")
            elif len(name_value) > 255:
                warnings.append(
                    "⚠️ Supplier Name is too long (>255 characters)")

        # Check Customer Name content
        customer_name = root.find(
            './/cac:AccountingCustomerParty//cbc:Name', namespaces)
        if customer_name is not None and customer_name.text:
            name_value = customer_name.text.strip()
            if len(name_value) < 1:
                warnings.append("⚠️ Customer Name is empty")
            elif len(name_value) > 255:
                warnings.append(
                    "⚠️ Customer Name is too long (>255 characters)")

        # Check Invoice Lines content
        invoice_lines = root.findall('.//cac:InvoiceLine', namespaces)
        for i, line in enumerate(invoice_lines, 1):
            line_id = line.find('cbc:ID', namespaces)
            if line_id is not None and line_id.text:
                line_id_value = line_id.text.strip()
                if len(line_id_value) < 1:
                    warnings.append(f"⚠️ Invoice Line {i} ID is empty")

            quantity = line.find('cbc:InvoicedQuantity', namespaces)
            if quantity is not None and quantity.text:
                qty_value = quantity.text.strip()
                try:
                    float(qty_value)
                except ValueError:
                    warnings.append(
                        f"⚠️ Invoice Line {i} quantity format may be invalid")

            price = line.find('.//cac:Price/cbc:PriceAmount', namespaces)
            if price is not None and price.text:
                price_value = price.text.strip()
                try:
                    float(price_value)
                except ValueError:
                    warnings.append(
                        f"⚠️ Invoice Line {i} price format may be invalid")

        logger.info(
            f"🔍 Strict validation: Completed with {len(warnings)} warnings")

    except Exception as e:
        logger.warning(f"⚠️ Strict validation error: {e}")
        warnings.append(f"⚠️ Strict validation error: {e}")

    return warnings


async def validate_edi_format(edi_path: Union[str, dict]) -> tuple[bool, Optional[str], Optional[dict]]:
    """Validate EDI format fields for correct values, format, and length"""
    logger.info(
        f"🔍 validate_edi_format: Starting EDI format validation for {edi_path}")

    try:
        logger.info(f"📄 validate_edi_format: Reading EDI file...")
        try:
            edi_content_bytes = await read_file_from_storage(edi_path, None, None)
        except:
            edi_content_bytes = await read_file_from_storage(None, None, edi_path)
        edi_content = edi_content_bytes.decode('utf-8')

        logger.info(
            f"✅ validate_edi_format: EDI file read successfully ({len(edi_content)} characters)")

        # Split into segments
        segments = [seg.strip()
                    for seg in edi_content.split('~') if seg.strip()]
        logger.info(f"📊 validate_edi_format: Found {len(segments)} segments")

        validation_results = {
            'isa_segment': {'valid': False, 'errors': []},
            'gs_segment': {'valid': False, 'errors': []},
            'st_segment': {'valid': False, 'errors': []},
            'big_segment': {'valid': False, 'errors': []},
            'n1_segments': {'valid': False, 'errors': []},
            'it1_segment': {'valid': False, 'errors': []},
            'tds_segment': {'valid': False, 'errors': []},
            'trailer_segments': {'valid': False, 'errors': []}
        }

        logger.info(f"🔍 validate_edi_format: Validating each segment...")

        # Validate ISA Segment (Interchange Control Header)
        isa_segment = next(
            (seg for seg in segments if seg.startswith('ISA')), None)
        if isa_segment:
            logger.info(f"   - ISA Segment: {isa_segment}")
            isa_fields = isa_segment.split('*')
            if len(isa_fields) >= 16:
                # Check ISA field lengths and formats
                if len(isa_fields[1]) != 2:  # Authorization Information Qualifier
                    validation_results['isa_segment']['errors'].append(
                        "ISA02: Authorization Info Qualifier must be 2 characters")
                if len(isa_fields[2]) != 10:  # Authorization Information
                    validation_results['isa_segment']['errors'].append(
                        "ISA03: Authorization Info must be 10 characters")
                if len(isa_fields[3]) != 2:  # Security Information Qualifier
                    validation_results['isa_segment']['errors'].append(
                        "ISA04: Security Info Qualifier must be 2 characters")
                if len(isa_fields[4]) != 10:  # Security Information
                    validation_results['isa_segment']['errors'].append(
                        "ISA05: Security Info must be 10 characters")
                if len(isa_fields[5]) != 2:  # Interchange ID Qualifier
                    validation_results['isa_segment']['errors'].append(
                        "ISA06: Interchange ID Qualifier must be 2 characters")
                if len(isa_fields[6]) != 15:  # Interchange Sender ID
                    validation_results['isa_segment']['errors'].append(
                        "ISA07: Sender ID must be 15 characters")
                if len(isa_fields[7]) != 2:  # Interchange ID Qualifier
                    validation_results['isa_segment']['errors'].append(
                        "ISA08: Interchange ID Qualifier must be 2 characters")
                if len(isa_fields[8]) != 15:  # Interchange Receiver ID
                    validation_results['isa_segment']['errors'].append(
                        "ISA09: Receiver ID must be 15 characters")

                validation_results['isa_segment']['valid'] = len(
                    validation_results['isa_segment']['errors']) == 0
                logger.info(
                    f"     ISA Validation: {'✅ PASS' if validation_results['isa_segment']['valid'] else '❌ FAIL'}")
                if validation_results['isa_segment']['errors']:
                    for error in validation_results['isa_segment']['errors']:
                        logger.error(f"       {error}")
            else:
                validation_results['isa_segment']['errors'].append(
                    "ISA segment must have at least 16 fields")
                logger.error(
                    f"     ISA Validation: ❌ FAIL - Insufficient fields")
        else:
            validation_results['isa_segment']['errors'].append(
                "ISA segment not found")
            logger.error(f"     ISA Validation: ❌ FAIL - Segment not found")

        # Validate GS Segment (Functional Group Header)
        gs_segment = next(
            (seg for seg in segments if seg.startswith('GS')), None)
        if gs_segment:
            logger.info(f"   - GS Segment: {gs_segment}")
            gs_fields = gs_segment.split('*')
            if len(gs_fields) >= 8:
                # Check GS field formats
                if gs_fields[1] != 'IN':  # Functional Identifier Code
                    validation_results['gs_segment']['errors'].append(
                        "GS02: Functional Identifier must be 'IN' for Invoice")
                if len(gs_fields[2]) != 2:  # Application Sender's Code
                    validation_results['gs_segment']['errors'].append(
                        "GS03: Application Sender Code must be 2 characters")
                if len(gs_fields[3]) != 2:  # Application Receiver's Code
                    validation_results['gs_segment']['errors'].append(
                        "GS04: Application Receiver Code must be 2 characters")

                validation_results['gs_segment']['valid'] = len(
                    validation_results['gs_segment']['errors']) == 0
                logger.info(
                    f"     GS Validation: {'✅ PASS' if validation_results['gs_segment']['valid'] else '❌ FAIL'}")
                if validation_results['gs_segment']['errors']:
                    for error in validation_results['gs_segment']['errors']:
                        logger.error(f"       {error}")
            else:
                validation_results['gs_segment']['errors'].append(
                    "GS segment must have at least 8 fields")
                logger.error(
                    f"     GS Validation: ❌ FAIL - Insufficient fields")
        else:
            validation_results['gs_segment']['errors'].append(
                "GS segment not found")
            logger.error(f"     GS Validation: ❌ FAIL - Segment not found")

        # Validate ST Segment (Transaction Set Header)
        st_segment = next(
            (seg for seg in segments if seg.startswith('ST')), None)
        if st_segment:
            logger.info(f"   - ST Segment: {st_segment}")
            st_fields = st_segment.split('*')
            if len(st_fields) >= 2:
                if st_fields[1] != '810':  # Transaction Set Identifier Code
                    validation_results['st_segment']['errors'].append(
                        "ST02: Transaction Set Identifier must be '810' for Invoice")

                validation_results['st_segment']['valid'] = len(
                    validation_results['st_segment']['errors']) == 0
                logger.info(
                    f"     ST Validation: {'✅ PASS' if validation_results['st_segment']['valid'] else '❌ FAIL'}")
                if validation_results['st_segment']['errors']:
                    for error in validation_results['st_segment']['errors']:
                        logger.error(f"       {error}")
            else:
                validation_results['st_segment']['errors'].append(
                    "ST segment must have at least 2 fields")
                logger.error(
                    f"     ST Validation: ❌ FAIL - Insufficient fields")
        else:
            validation_results['st_segment']['errors'].append(
                "ST segment not found")
            logger.error(f"     ST Validation: ❌ FAIL - Segment not found")

        # Validate BIG Segment (Beginning Segment for Invoice)
        big_segment = next(
            (seg for seg in segments if seg.startswith('BIG')), None)
        if big_segment:
            logger.info(f"   - BIG Segment: {big_segment}")
            big_fields = big_segment.split('*')
            if len(big_fields) >= 3:
                # Check date format (should be YYYYMMDD)
                if big_fields[1] and len(big_fields[1]) == 8:
                    try:
                        # Validate date format
                        year = int(big_fields[1][:4])
                        month = int(big_fields[1][4:6])
                        day = int(big_fields[1][6:8])
                        if not (1 <= month <= 12 and 1 <= day <= 31):
                            validation_results['big_segment']['errors'].append(
                                "BIG02: Invalid date format")
                    except ValueError:
                        validation_results['big_segment']['errors'].append(
                            "BIG02: Date must be numeric YYYYMMDD format")
                else:
                    validation_results['big_segment']['errors'].append(
                        "BIG02: Invoice date must be 8 characters (YYYYMMDD)")

                # Check invoice number
                if not big_fields[2] or len(big_fields[2]) == 0:
                    validation_results['big_segment']['errors'].append(
                        "BIG03: Invoice number cannot be empty")

                validation_results['big_segment']['valid'] = len(
                    validation_results['big_segment']['errors']) == 0
                logger.info(
                    f"     BIG Validation: {'✅ PASS' if validation_results['big_segment']['valid'] else '❌ FAIL'}")
                if validation_results['big_segment']['errors']:
                    for error in validation_results['big_segment']['errors']:
                        logger.error(f"       {error}")
            else:
                validation_results['big_segment']['errors'].append(
                    "BIG segment must have at least 3 fields")
                logger.error(
                    f"     BIG Validation: ❌ FAIL - Insufficient fields")
        else:
            validation_results['big_segment']['errors'].append(
                "BIG segment not found")
            logger.error(f"     BIG Validation: ❌ FAIL - Segment not found")

        # Validate N1 Segments (Name/Address Information)
        n1_segments = [seg for seg in segments if seg.startswith('N1')]
        if len(n1_segments) >= 2:
            logger.info(f"   - N1 Segments: Found {len(n1_segments)} segments")
            for i, n1_seg in enumerate(n1_segments):
                logger.info(f"     N1-{i+1}: {n1_seg}")
                n1_fields = n1_seg.split('*')
                if len(n1_fields) >= 2:
                    if n1_fields[1] not in ['BY', 'SE']:  # Entity Identifier Code
                        validation_results['n1_segments']['errors'].append(
                            f"N1-{i+1}: Entity Identifier must be 'BY' or 'SE'")
                else:
                    validation_results['n1_segments']['errors'].append(
                        f"N1-{i+1}: Segment must have at least 2 fields")

            validation_results['n1_segments']['valid'] = len(
                validation_results['n1_segments']['errors']) == 0
            logger.info(
                f"     N1 Validation: {'✅ PASS' if validation_results['n1_segments']['valid'] else '❌ FAIL'}")
            if validation_results['n1_segments']['errors']:
                for error in validation_results['n1_segments']['errors']:
                    logger.error(f"       {error}")
        else:
            validation_results['n1_segments']['errors'].append(
                "Must have at least 2 N1 segments (Buyer and Seller)")
            logger.error(
                f"     N1 Validation: ❌ FAIL - Insufficient N1 segments")

        # Validate IT1 Segment (Baseline Item Data)
        it1_segment = next(
            (seg for seg in segments if seg.startswith('IT1')), None)
        if it1_segment:
            logger.info(f"   - IT1 Segment: {it1_segment}")
            it1_fields = it1_segment.split('*')
            if len(it1_fields) >= 6:
                # Check quantity and amount fields
                try:
                    quantity = float(it1_fields[2]) if it1_fields[2] else 0
                    if quantity <= 0:
                        validation_results['it1_segment']['errors'].append(
                            "IT103: Quantity must be greater than 0")
                except ValueError:
                    validation_results['it1_segment']['errors'].append(
                        "IT103: Quantity must be numeric")

                validation_results['it1_segment']['valid'] = len(
                    validation_results['it1_segment']['errors']) == 0
                logger.info(
                    f"     IT1 Validation: {'✅ PASS' if validation_results['it1_segment']['valid'] else '❌ FAIL'}")
                if validation_results['it1_segment']['errors']:
                    for error in validation_results['it1_segment']['errors']:
                        logger.error(f"       {error}")
            else:
                validation_results['it1_segment']['errors'].append(
                    "IT1 segment must have at least 6 fields")
                logger.error(
                    f"     IT1 Validation: ❌ FAIL - Insufficient fields")
        else:
            validation_results['it1_segment']['errors'].append(
                "IT1 segment not found")
            logger.error(f"     IT1 Validation: ❌ FAIL - Segment not found")

        # Validate TDS Segment (Total Monetary Value Summary)
        tds_segment = next(
            (seg for seg in segments if seg.startswith('TDS')), None)
        if tds_segment:
            logger.info(f"   - TDS Segment: {tds_segment}")
            tds_fields = tds_segment.split('*')
            if len(tds_fields) >= 2:
                try:
                    amount = float(tds_fields[1]) if tds_fields[1] else 0
                    if amount <= 0:
                        validation_results['tds_segment']['errors'].append(
                            "TDS02: Total amount must be greater than 0")
                except ValueError:
                    validation_results['tds_segment']['errors'].append(
                        "TDS02: Total amount must be numeric")

                validation_results['tds_segment']['valid'] = len(
                    validation_results['tds_segment']['errors']) == 0
                logger.info(
                    f"     TDS Validation: {'✅ PASS' if validation_results['tds_segment']['valid'] else '❌ FAIL'}")
                if validation_results['tds_segment']['errors']:
                    for error in validation_results['tds_segment']['errors']:
                        logger.error(f"       {error}")
            else:
                validation_results['tds_segment']['errors'].append(
                    "TDS segment must have at least 2 fields")
                logger.error(
                    f"     TDS Validation: ❌ FAIL - Insufficient fields")
        else:
            validation_results['tds_segment']['errors'].append(
                "TDS segment not found")
            logger.error(f"     TDS Validation: ❌ FAIL - Segment not found")

        # Validate Trailer Segments (CTT, SE, GE, IEA)
        ctt_segment = next(
            (seg for seg in segments if seg.startswith('CTT')), None)
        se_segment = next(
            (seg for seg in segments if seg.startswith('SE')), None)
        ge_segment = next(
            (seg for seg in segments if seg.startswith('GE')), None)
        iea_segment = next(
            (seg for seg in segments if seg.startswith('IEA')), None)

        trailer_segments = [ctt_segment, se_segment, ge_segment, iea_segment]
        trailer_names = ['CTT', 'SE', 'GE', 'IEA']

        for i, (seg, name) in enumerate(zip(trailer_segments, trailer_names)):
            if seg:
                logger.info(f"   - {name} Segment: {seg}")
            else:
                validation_results['trailer_segments']['errors'].append(
                    f"{name} segment not found")
                logger.error(
                    f"     {name} Validation: ❌ FAIL - Segment not found")

        validation_results['trailer_segments']['valid'] = len(
            validation_results['trailer_segments']['errors']) == 0
        logger.info(
            f"     Trailer Validation: {'✅ PASS' if validation_results['trailer_segments']['valid'] else '❌ FAIL'}")

        # Summary of validation results
        all_valid = all(result['valid']
                        for result in validation_results.values())
        total_errors = sum(len(result['errors'])
                           for result in validation_results.values())

        logger.info(
            f"📊 validate_edi_format: EDI Format Validation Results Summary:")
        logger.info(f"   - Total Segments Found: {len(segments)}")
        logger.info(
            f"   - ISA Segment: {'✅ VALID' if validation_results['isa_segment']['valid'] else '❌ INVALID'}")
        logger.info(
            f"   - GS Segment: {'✅ VALID' if validation_results['gs_segment']['valid'] else '❌ INVALID'}")
        logger.info(
            f"   - ST Segment: {'✅ VALID' if validation_results['st_segment']['valid'] else '❌ INVALID'}")
        logger.info(
            f"   - BIG Segment: {'✅ VALID' if validation_results['big_segment']['valid'] else '❌ INVALID'}")
        logger.info(
            f"   - N1 Segments: {'✅ VALID' if validation_results['n1_segments']['valid'] else '❌ INVALID'}")
        logger.info(
            f"   - IT1 Segment: {'✅ VALID' if validation_results['it1_segment']['valid'] else '❌ INVALID'}")
        logger.info(
            f"   - TDS Segment: {'✅ VALID' if validation_results['tds_segment']['valid'] else '❌ INVALID'}")
        logger.info(
            f"   - Trailer Segments: {'✅ VALID' if validation_results['trailer_segments']['valid'] else '❌ INVALID'}")
        logger.info(f"   - Total Validation Errors: {total_errors}")
        logger.info(
            f"   - Overall Validation: {'✅ PASS' if all_valid else '❌ FAIL'}")

        if all_valid:
            logger.info(f"✅ validate_edi_format: EDI format validation passed")
            return True, "EDI format validation passed", None
        else:
            error_msg = f"EDI format validation failed with {total_errors} errors"
            logger.error(f"❌ validate_edi_format: {error_msg}")
            return False, error_msg, validation_results

    except FileNotFoundError:
        error_msg = f"EDI file not found: {edi_path}"
        logger.error(f"❌ validate_edi_format: {error_msg}")
        return False, error_msg, None
    except Exception as e:
        error_msg = f"EDI format validation error: {str(e)}"
        logger.error(f"❌ validate_edi_format: Unexpected error - {error_msg}")
        return False, error_msg, None
