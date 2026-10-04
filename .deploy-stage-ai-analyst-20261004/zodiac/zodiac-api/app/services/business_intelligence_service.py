"""
Business Intelligence Data Extraction Service

Extracts business intelligence from invoices:
- Customer information
- Supplier information
- Product details
- Industry classification
- Financial data
"""
import logging
import re
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from lxml import etree

logger = logging.getLogger(__name__)

# ============================================================
# INDUSTRY CLASSIFICATION KEYWORDS
# ============================================================
INDUSTRY_KEYWORDS = {
    'Technology': {
        'high': ['software', 'saas', 'cloud computing', 'IT services', 'technology consulting'],
        'medium': ['computer', 'hardware', 'electronics', 'digital', 'tech', 'app', 'platform'],
        'low': ['IT', 'tech support', 'web']
    },
    'Healthcare': {
        'high': ['pharmaceutical', 'medical device', 'healthcare services', 'hospital'],
        'medium': ['medicine', 'health', 'clinical', 'medical', 'pharmacy'],
        'low': ['care', 'wellness']
    },
    'Retail': {
        'high': ['retail store', 'e-commerce', 'online shopping'],
        'medium': ['clothing', 'apparel', 'fashion', 'accessories', 'shoes', 'store'],
        'low': ['retail', 'shop', 'merchandise']
    },
    'Food & Beverage': {
        'high': ['restaurant', 'catering service', 'food manufacturing'],
        'medium': ['food', 'beverage', 'drink', 'meal', 'catering'],
        'low': ['cafe', 'bar', 'dining']
    },
    'Manufacturing': {
        'high': ['manufacturing', 'industrial equipment', 'factory'],
        'medium': ['machinery', 'equipment', 'tools', 'parts', 'components'],
        'low': ['assembly', 'production']
    },
    'Construction': {
        'high': ['construction services', 'building contractor'],
        'medium': ['building', 'construction', 'materials', 'cement', 'steel'],
        'low': ['contractor', 'builder']
    },
    'Automotive': {
        'high': ['automotive manufacturer', 'car dealer'],
        'medium': ['car', 'vehicle', 'automotive', 'auto parts', 'tire'],
        'low': ['auto', 'motor']
    },
    'Energy': {
        'high': ['energy provider', 'oil and gas', 'renewable energy'],
        'medium': ['energy', 'oil', 'gas', 'electricity', 'power', 'solar'],
        'low': ['fuel', 'utility']
    },
    'Logistics': {
        'high': ['logistics services', 'freight forwarding', 'shipping company'],
        'medium': ['logistics', 'transportation', 'shipping', 'delivery', 'freight'],
        'low': ['transport', 'courier']
    },
    'Financial Services': {
        'high': ['banking', 'insurance company', 'investment services'],
        'medium': ['financial', 'finance', 'insurance', 'banking', 'investment'],
        'low': ['bank', 'credit']
    },
    'Telecommunications': {
        'high': ['telecommunications', 'telecom services', 'network provider'],
        'medium': ['telecom', 'communications', 'internet service', 'mobile'],
        'low': ['phone', 'network']
    },
    'Professional Services': {
        'high': ['consulting services', 'legal services', 'accounting firm'],
        'medium': ['consulting', 'advisory', 'professional services', 'legal', 'accounting'],
        'low': ['services', 'consulting']
    },
}


class BusinessIntelligenceExtractor:
    """Extracts business intelligence from invoice XML/EDI data"""
    
    def __init__(self):
        self.namespaces = {
            'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
            'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
            'ubl': 'urn:oasis:names:specification:ubl:schema:xsd:Invoice-2'
        }
    
    def extract_from_xml(self, xml_content) -> Dict:
        """
        Extract business intelligence from XML invoice
        
        Args:
            xml_content: XML content (string or bytes)
            
        Returns:
            Dictionary with extracted business data
        """
        try:
            # Handle both string and bytes
            if isinstance(xml_content, str):
                xml_bytes = xml_content.encode('utf-8')
            else:
                xml_bytes = xml_content
            
            root = etree.fromstring(xml_bytes)
            
            # Extract all components
            customer_data = self._extract_customer_from_xml(root)
            supplier_data = self._extract_supplier_from_xml(root)
            products = self._extract_products_from_xml(root)
            financial_data = self._extract_financial_data_from_xml(root)
            
            # Classify industry based on products
            industry, confidence, keywords = self._classify_industry(products, customer_data.get('customer_name'))
            
            return {
                **customer_data,
                **supplier_data,
                'products': products,
                'product_count': len(products),
                'industry': industry,
                'industry_confidence': confidence,
                'industry_keywords_matched': keywords,
                **financial_data,
                'source_format': 'XML'
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to extract business data from XML: {e}")
            return self._get_empty_data()
    
    def _extract_customer_from_xml(self, root) -> Dict:
        """Extract customer information from XML"""
        try:
            customer_party = root.find('.//cac:AccountingCustomerParty/cac:Party', self.namespaces)
            if customer_party is None:
                return {}
            
            # Customer ID
            customer_id_elem = root.find('.//cac:AccountingCustomerParty/cac:Party/cbc:EndpointID', self.namespaces)
            customer_id = customer_id_elem.text if customer_id_elem is not None else None
            
            # Customer name
            name_elem = customer_party.find('.//cac:PartyName/cbc:Name', self.namespaces)
            if name_elem is None:
                name_elem = customer_party.find('.//cac:PartyLegalEntity/cbc:RegistrationName', self.namespaces)
            customer_name = name_elem.text if name_elem is not None else None
            
            # Address
            address = customer_party.find('.//cac:PostalAddress', self.namespaces)
            country = None
            city = None
            full_address = None
            
            if address is not None:
                country_elem = address.find('.//cac:Country/cbc:IdentificationCode', self.namespaces)
                city_elem = address.find('.//cbc:CityName', self.namespaces)
                
                country = country_elem.text if country_elem is not None else None
                city = city_elem.text if city_elem is not None else None
                
                # Build full address
                address_parts = []
                for elem in ['cbc:StreetName', 'cbc:CityName', 'cbc:PostalZone']:
                    addr_elem = address.find(f'.//{elem}', self.namespaces)
                    if addr_elem is not None and addr_elem.text:
                        address_parts.append(addr_elem.text)
                full_address = ', '.join(address_parts) if address_parts else None
            
            # Tax ID
            tax_id_elem = customer_party.find('.//cac:PartyTaxScheme/cbc:CompanyID', self.namespaces)
            tax_id = tax_id_elem.text if tax_id_elem is not None else None
            
            return {
                'customer_id': customer_id,
                'customer_name': customer_name,
                'customer_country': country,
                'customer_city': city,
                'customer_address': full_address,
                'customer_tax_id': tax_id
            }
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to extract customer data: {e}")
            return {}
    
    def _extract_supplier_from_xml(self, root) -> Dict:
        """Extract supplier information from XML"""
        try:
            supplier_party = root.find('.//cac:AccountingSupplierParty/cac:Party', self.namespaces)
            if supplier_party is None:
                return {}
            
            # Supplier ID
            supplier_id_elem = root.find('.//cac:AccountingSupplierParty/cac:Party/cbc:EndpointID', self.namespaces)
            supplier_id = supplier_id_elem.text if supplier_id_elem is not None else None
            
            # Supplier name
            name_elem = supplier_party.find('.//cac:PartyName/cbc:Name', self.namespaces)
            if name_elem is None:
                name_elem = supplier_party.find('.//cac:PartyLegalEntity/cbc:RegistrationName', self.namespaces)
            supplier_name = name_elem.text if name_elem is not None else None
            
            # Country
            country_elem = supplier_party.find('.//cac:PostalAddress/cac:Country/cbc:IdentificationCode', self.namespaces)
            country = country_elem.text if country_elem is not None else None
            
            return {
                'supplier_id': supplier_id,
                'supplier_name': supplier_name,
                'supplier_country': country
            }
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to extract supplier data: {e}")
            return {}
    
    def _extract_products_from_xml(self, root) -> List[Dict]:
        """Extract product/line items from XML"""
        products = []
        
        try:
            invoice_lines = root.findall('.//cac:InvoiceLine', self.namespaces)
            
            for line in invoice_lines:
                try:
                    # Product name
                    name_elem = line.find('.//cac:Item/cbc:Name', self.namespaces)
                    name = name_elem.text if name_elem is not None else 'Unknown Product'
                    
                    # Description
                    desc_elem = line.find('.//cac:Item/cbc:Description', self.namespaces)
                    description = desc_elem.text if desc_elem is not None else None
                    
                    # Quantity
                    qty_elem = line.find('.//cbc:InvoicedQuantity', self.namespaces)
                    quantity = float(qty_elem.text) if qty_elem is not None else 0
                    
                    # Price
                    price_elem = line.find('.//cac:Price/cbc:PriceAmount', self.namespaces)
                    unit_price = float(price_elem.text) if price_elem is not None else 0
                    
                    # Line total
                    total_elem = line.find('.//cbc:LineExtensionAmount', self.namespaces)
                    line_total = float(total_elem.text) if total_elem is not None else (quantity * unit_price)
                    
                    # Currency
                    currency = price_elem.get('currencyID') if price_elem is not None else 'USD'
                    
                    products.append({
                        'name': name,
                        'description': description,
                        'quantity': quantity,
                        'unit_price': unit_price,
                        'line_total': line_total,
                        'currency': currency
                    })
                    
                except Exception as e:
                    logger.warning(f"⚠️ Failed to extract product line: {e}")
                    continue
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to extract products: {e}")
        
        return products
    
    def _extract_financial_data_from_xml(self, root) -> Dict:
        """Extract financial information from XML"""
        try:
            # Invoice number
            inv_num_elem = root.find('.//cbc:ID', self.namespaces)
            invoice_number = inv_num_elem.text if inv_num_elem is not None else None
            
            # Dates
            inv_date_elem = root.find('.//cbc:IssueDate', self.namespaces)
            invoice_date = None
            if inv_date_elem is not None:
                try:
                    invoice_date = datetime.fromisoformat(inv_date_elem.text)
                except:
                    pass
            
            due_date_elem = root.find('.//cbc:DueDate', self.namespaces)
            due_date = None
            if due_date_elem is not None:
                try:
                    due_date = datetime.fromisoformat(due_date_elem.text)
                except:
                    pass
            
            # Totals
            total_elem = root.find('.//cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount', self.namespaces)
            if total_elem is None:
                total_elem = root.find('.//cac:LegalMonetaryTotal/cbc:PayableAmount', self.namespaces)
            total_amount = float(total_elem.text) if total_elem is not None else None
            
            # Tax amount
            tax_elem = root.find('.//cac:TaxTotal/cbc:TaxAmount', self.namespaces)
            tax_amount = float(tax_elem.text) if tax_elem is not None else None
            
            # Currency
            currency = total_elem.get('currencyID') if total_elem is not None else 'USD'
            
            return {
                'invoice_number': invoice_number,
                'invoice_date': invoice_date,
                'due_date': due_date,
                'total_amount': total_amount,
                'tax_amount': tax_amount,
                'currency': currency
            }
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to extract financial data: {e}")
            return {}
    
    def _classify_industry(self, products: List[Dict], customer_name: Optional[str] = None) -> Tuple[str, str, List[str]]:
        """
        Classify industry based on products and customer name
        
        Returns:
            Tuple of (industry_name, confidence_level, matched_keywords)
        """
        if not products and not customer_name:
            return ('General', 'low', [])
        
        # Combine product names and descriptions
        text_to_analyze = []
        for product in products:
            if product.get('name'):
                text_to_analyze.append(product['name'].lower())
            if product.get('description'):
                text_to_analyze.append(product['description'].lower())
        
        if customer_name:
            text_to_analyze.append(customer_name.lower())
        
        combined_text = ' '.join(text_to_analyze)
        
        # Score each industry
        industry_scores = {}
        matched_keywords = {}
        
        for industry, keyword_levels in INDUSTRY_KEYWORDS.items():
            score = 0
            keywords_found = []
            
            # High confidence keywords (3 points)
            for keyword in keyword_levels.get('high', []):
                if keyword.lower() in combined_text:
                    score += 3
                    keywords_found.append(keyword)
            
            # Medium confidence keywords (2 points)
            for keyword in keyword_levels.get('medium', []):
                if keyword.lower() in combined_text:
                    score += 2
                    keywords_found.append(keyword)
            
            # Low confidence keywords (1 point)
            for keyword in keyword_levels.get('low', []):
                if keyword.lower() in combined_text:
                    score += 1
                    keywords_found.append(keyword)
            
            if score > 0:
                industry_scores[industry] = score
                matched_keywords[industry] = keywords_found
        
        # Select industry with highest score
        if not industry_scores:
            return ('General', 'low', [])
        
        best_industry = max(industry_scores, key=industry_scores.get)
        best_score = industry_scores[best_industry]
        
        # Determine confidence level
        if best_score >= 5:
            confidence = 'high'
        elif best_score >= 2:
            confidence = 'medium'
        else:
            confidence = 'low'
        
        return (best_industry, confidence, matched_keywords.get(best_industry, []))
    
    def _get_empty_data(self) -> Dict:
        """Return empty data structure"""
        return {
            'customer_id': None,
            'customer_name': None,
            'customer_country': None,
            'customer_city': None,
            'customer_address': None,
            'customer_tax_id': None,
            'supplier_id': None,
            'supplier_name': None,
            'supplier_country': None,
            'products': [],
            'product_count': 0,
            'industry': 'General',
            'industry_confidence': 'low',
            'industry_keywords_matched': [],
            'invoice_number': None,
            'invoice_date': None,
            'due_date': None,
            'total_amount': None,
            'tax_amount': None,
            'currency': 'USD',
            'source_format': 'XML'
        }


# Global instance
business_intelligence_extractor = BusinessIntelligenceExtractor()

