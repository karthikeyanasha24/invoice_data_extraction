import logging
from sqlalchemy.orm import Session
from sqlalchemy.exc import ProgrammingError, OperationalError
from ..database import SessionLocal
from lxml import etree

logger = logging.getLogger("zodiac-api.database")

def check_customer_table(cust_id, cust_name, db: Session = None):
    """Lookup customer format and validation rules from zodiac_customers table.
    
    Returns:
        tuple: (format, validation_rules) where format is the target format string
               and validation_rules is the JSON string with required fields
    """
    close_after = db is None
    if close_after:
        db = SessionLocal()

    try:
        from ..models.customer import Customer
        customer = db.query(Customer).filter(
            (Customer.customer_id == cust_id) | (Customer.customer_id == cust_name)
        ).first()
        
        if customer:
            logger.info(f"🔍 Customer lookup for ID '{cust_id}' or Name '{cust_name}': "
                        f"Found format '{customer.format}' with "
                        f"{'custom validation rules' if customer.validation_rules else 'default validation'}")
            return customer.format or 'xml', customer.validation_rules
        else:
            logger.info(f"🔍 Customer lookup for ID '{cust_id}' or Name '{cust_name}': "
                        f"Not found, defaulting to XML with no custom rules")
            return 'xml', None
            
    except (ProgrammingError, OperationalError) as e:
        # Handle table doesn't exist or other DB structure errors
        logger.warning(f"⚠️ check_customer_table lookup failed (table may not exist): {e}")
        db.rollback()  # Rollback to clear the failed transaction
        return 'xml', None
    except Exception as e:
        logger.warning(f"⚠️ check_customer_table lookup failed: {e}")
        db.rollback()  # Rollback for any other errors
        return 'xml', None
    finally:
        if close_after:
            db.close()

def extract_supplier_info_from_string(xml_content: str) -> tuple[str | None, str | None]:
    """
    Extract customer (accounting customer party) ID and name from a UBL XML string.
    
    In UBL invoices:
    - AccountingSupplierParty = the seller/supplier
    - AccountingCustomerParty = the buyer/customer (who receives the invoice)
    
    We extract from AccountingCustomerParty to identify which customer this invoice is for.
    """
    namespaces = {
        'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
        'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
    }

    try:
        # Parse directly from XML string
        root = etree.fromstring(xml_content.encode('utf-8'))

        # Navigate to the customer party element (AccountingCustomerParty)
        customer_party = root.find(
            './/cac:AccountingCustomerParty/cac:Party', namespaces)

        if customer_party is not None:
            # Try to extract ID from EndpointID (preferred - PEPPOL format uses this)
            customer_id_elem = customer_party.find('cbc:EndpointID', namespaces)
            if customer_id_elem is None:
                # Fallback to PartyIdentification/ID (alternative format)
                customer_id_elem = customer_party.find('cac:PartyIdentification/cbc:ID', namespaces)
            
            customer_id = customer_id_elem.text if customer_id_elem is not None else None

            # Extract Name from PartyName/Name
            customer_name_elem = customer_party.find('cac:PartyName/cbc:Name', namespaces)
            if customer_name_elem is None:
                # Fallback to PartyLegalEntity/RegistrationName
                customer_name_elem = customer_party.find('cac:PartyLegalEntity/cbc:RegistrationName', namespaces)
            
            customer_name = customer_name_elem.text if customer_name_elem is not None else None

            logger.info(f"✅ Extracted customer info - ID: {customer_id}, Name: {customer_name}")
            return customer_id, customer_name

        logger.warning(f"⚠️ AccountingCustomerParty not found in XML")
        return None, None

    except Exception as e:
        logger.error(f"❌ Error parsing XML to extract customer info: {e}")
        return None, None
