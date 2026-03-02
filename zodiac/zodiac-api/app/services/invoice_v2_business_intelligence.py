"""
Invoice V2 Business Intelligence Extraction Service
Extracts BI data from validated invoices and classifies industries
"""
import logging
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, date
from decimal import Decimal
import json

logger = logging.getLogger("zodiac-api.v2_bi")

try:
    from openai import OpenAI
    openai_available = True
except ImportError:
    openai_available = False


class InvoiceV2BusinessIntelligence:
    """Service for extracting business intelligence from Invoice V2 validated invoices"""
    
    # Industry classification keywords
    INDUSTRY_KEYWORDS = {
        "Manufacturing": [
            "widget", "hardware", "equipment", "machine", "tool", "part", "component",
            "manufacturing", "industrial", "factory", "production", "assembly"
        ],
        "Professional Services": [
            "consulting", "service", "support", "advisory", "consulting", "professional",
            "training", "education", "legal", "accounting", "audit", "management"
        ],
        "Technology": [
            "software", "license", "cloud", "saas", "app", "platform", "hosting",
            "technology", "digital", "it", "system", "development", "programming"
        ],
        "Food & Beverage": [
            "food", "beverage", "drink", "catering", "restaurant", "cuisine",
            "meal", "snack", "coffee", "tea", "wine", "beer"
        ],
        "Healthcare": [
            "medical", "health", "pharmaceutical", "drug", "medicine", "hospital",
            "clinic", "care", "treatment", "therapy", "diagnostic"
        ],
        "Retail": [
            "retail", "store", "shop", "merchandise", "goods", "product",
            "clothing", "apparel", "fashion", "accessories"
        ],
        "Construction": [
            "construction", "building", "contractor", "renovation", "infrastructure",
            "cement", "concrete", "lumber", "steel", "material"
        ],
        "Transportation": [
            "transport", "shipping", "logistics", "freight", "delivery", "trucking",
            "courier", "warehouse", "distribution"
        ],
        "Energy": [
            "energy", "power", "electricity", "solar", "renewable", "oil", "gas",
            "utility", "fuel"
        ],
        "Telecommunications": [
            "telecom", "communication", "network", "wireless", "mobile", "broadband",
            "internet", "phone", "data"
        ]
    }
    
    def extract_bi_data(self, validated_invoice) -> Dict[str, Any]:
        """
        Extract business intelligence data from a validated invoice
        
        Args:
            validated_invoice: InvoiceV2Validated model instance
            
        Returns:
            Dictionary with structured BI data
        """
        logger.info(f"🔍 Extracting BI data from validated invoice {validated_invoice.id}")
        
        invoice_data = validated_invoice.invoice_data or {}
        
        # Extract customer data
        customer = {
            'id': invoice_data.get('customer_id'),
            'name': invoice_data.get('customer_name'),
            'country': self._extract_country(invoice_data, 'customer'),
            'tax_id': invoice_data.get('customer_tax_id')
        }
        
        # Extract supplier data
        supplier = {
            'id': invoice_data.get('supplier_id'),
            'name': invoice_data.get('supplier_name'),
            'country': self._extract_country(invoice_data, 'supplier'),
            'tax_id': invoice_data.get('supplier_tax_id')
        }
        
        # Extract and structure products
        products = self._extract_products(invoice_data)
        
        # Extract financial data
        financial = {
            'total_amount': self._to_decimal(invoice_data.get('total') or invoice_data.get('payable_amount')),
            'tax_amount': self._to_decimal(invoice_data.get('tax_amount')),
            'currency': invoice_data.get('currency', 'USD'),
            'invoice_date': self._parse_date(invoice_data.get('issue_date'))
        }
        
        # Infer industry from products and customer
        industry, confidence, keywords = self.infer_industry(products, customer['name'])
        
        # Calculate temporal fields
        temporal = self._calculate_temporal_fields(financial['invoice_date'])
        
        # Determine lifecycle stage
        lifecycle = self._determine_lifecycle_stage(validated_invoice)
        
        bi_data = {
            'validated_invoice_id': validated_invoice.id,
            'user_id': validated_invoice.document.user_id if validated_invoice.document else None,
            'customer': customer,
            'supplier': supplier,
            'products': products,
            'total_products_count': len(products),
            'financial': financial,
            'industry': industry,
            'industry_confidence': confidence,
            'industry_keywords_matched': keywords,
            'temporal': temporal,
            'lifecycle': lifecycle
        }
        
        logger.info(f"✅ Extracted BI data: {len(products)} products, industry={industry} ({confidence*100:.1f}% confidence)")
        
        return bi_data
    
    def infer_industry(
        self, 
        products: List[Dict[str, Any]], 
        customer_name: Optional[str] = None
    ) -> Tuple[str, float, List[str]]:
        """
        Infer industry from product names and customer name using keyword matching
        
        Args:
            products: List of product dictionaries
            customer_name: Optional customer name
            
        Returns:
            Tuple of (industry_name, confidence_score, matched_keywords)
        """
        # Collect all text to analyze
        text_to_analyze = []
        
        # Add product names and descriptions
        for product in products:
            if product.get('name'):
                text_to_analyze.append(product['name'].lower())
            if product.get('description'):
                text_to_analyze.append(product['description'].lower())
        
        # Add customer name
        if customer_name:
            text_to_analyze.append(customer_name.lower())
        
        if not text_to_analyze:
            return "General", 0.0, []
        
        combined_text = " ".join(text_to_analyze)
        
        # Score each industry
        industry_scores = {}
        matched_keywords_by_industry = {}
        
        for industry, keywords in self.INDUSTRY_KEYWORDS.items():
            matched_keywords = []
            score = 0
            
            for keyword in keywords:
                if keyword.lower() in combined_text:
                    matched_keywords.append(keyword)
                    # Weight keywords found in product names higher
                    weight = 2.0 if any(keyword.lower() in p.lower() for p in text_to_analyze[:-1] if p) else 1.0
                    score += weight
            
            if score > 0:
                industry_scores[industry] = score
                matched_keywords_by_industry[industry] = matched_keywords
        
        # Find best match
        if not industry_scores:
            return "General", 0.0, []
        
        best_industry = max(industry_scores, key=industry_scores.get)
        best_score = industry_scores[best_industry]
        
        # Calculate confidence (normalize by number of keywords in best industry)
        max_possible_score = len(self.INDUSTRY_KEYWORDS[best_industry]) * 2.0
        confidence = min(best_score / max_possible_score, 1.0) if max_possible_score > 0 else 0.0
        
        # Boost confidence if multiple keywords matched
        num_matches = len(matched_keywords_by_industry[best_industry])
        if num_matches >= 3:
            confidence = min(confidence * 1.2, 1.0)
        elif num_matches >= 2:
            confidence = min(confidence * 1.1, 1.0)
        
        logger.info(f"🏭 Industry classified: {best_industry} ({confidence*100:.1f}% confidence, {num_matches} keywords)")
        
        return best_industry, confidence, matched_keywords_by_industry[best_industry]
    
    def _extract_products(self, invoice_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract and structure product information from line_items (products)."""
        line_items = invoice_data.get('line_items', [])
        if not line_items or not isinstance(line_items, list):
            return []

        products = []
        for item in line_items:
            if not isinstance(item, dict):
                continue
            # Support both item_name and name (validation service uses item_name)
            name = item.get('item_name') or item.get('name') or 'Unknown Product'
            if isinstance(name, str):
                name = name.strip() or 'Unknown Product'
            # Revenue: line_amount or line_extension_amount
            line_amount = item.get('line_amount') or item.get('line_extension_amount')
            revenue = self._to_decimal(line_amount)
            # Tax: tax_percentage or tax_percent (validation uses tax_percent)
            tax_val = item.get('tax_percentage') or item.get('tax_percent')
            tax_pct = self._to_decimal(tax_val)
            quantity = self._to_decimal(item.get('quantity', 0))
            price = self._to_decimal(item.get('price', 0))

            product = {
                'id': item.get('line_id') or item.get('id'),
                'name': name,
                'description': item.get('item_description') or item.get('description'),
                'quantity': float(quantity) if quantity is not None else None,
                'unit_code': item.get('unit_code'),
                'price': float(price) if price is not None else None,
                'revenue': float(revenue) if revenue is not None else None,
                'seller_item_id': item.get('seller_item_id'),
                'buyer_item_id': item.get('buyer_item_id'),
                'standard_item_id': item.get('standard_item_id'),
                'origin_country': item.get('origin_country'),
                'commodity_code': item.get('commodity_code'),
                'tax_percentage': float(tax_pct) if tax_pct is not None else None,
            }
            product = {k: v for k, v in product.items() if v is not None}
            products.append(product)

        return products
    
    def _extract_country(self, invoice_data: Dict[str, Any], party_type: str) -> Optional[str]:
        """Extract country from party address. Use AI fallback when country is missing but address hints exist."""
        # Try direct field
        country = invoice_data.get(f'{party_type}_country')
        if country:
            return self._normalize_country_code(country)

        # Try address object
        address = invoice_data.get(f'{party_type}_address')
        if address and isinstance(address, dict):
            country = address.get('country')
            if country:
                return self._normalize_country_code(country)
            # AI fallback: infer country from city, postal_zone, street
            return self._ai_infer_country(
                address.get('city'),
                address.get('postal_zone'),
                address.get('street'),
                invoice_data.get('delivery_address') if party_type == 'customer' else None,
            )

        # Fallback: try delivery address for customer
        if party_type == 'customer':
            delivery = invoice_data.get('delivery_address')
            if isinstance(delivery, dict):
                country = delivery.get('country')
                if country:
                    return self._normalize_country_code(country)
                return self._ai_infer_country(
                    delivery.get('city'), delivery.get('postal_zone'), delivery.get('street'), None
                )

        return None

    def _normalize_country_code(self, code: str) -> str:
        """Normalize to uppercase ISO alpha-2 (e.g. UK -> GB handled separately if needed)."""
        if not code or not isinstance(code, str):
            return code or ""
        return code.strip().upper()[:2]

    def _ai_infer_country(
        self,
        city: Optional[str],
        postal_zone: Optional[str],
        street: Optional[str],
        delivery_address: Optional[Dict],
    ) -> Optional[str]:
        """Use AI to infer ISO country code from address hints when country is missing."""
        try:
            from ..config.config import OPENAI_API_KEY
        except ImportError:
            return None
        if not OPENAI_API_KEY or not openai_available:
            return None

        hints = []
        if city:
            hints.append(f"city: {city}")
        if postal_zone:
            hints.append(f"postal: {postal_zone}")
        if street:
            hints.append(f"street: {street}")
        if delivery_address and isinstance(delivery_address, dict):
            if delivery_address.get('city'):
                hints.append(f"delivery city: {delivery_address['city']}")
            if delivery_address.get('country'):
                return self._normalize_country_code(delivery_address['country'])
        if not hints:
            return None

        text = "; ".join(hints)
        try:
            client = OpenAI(api_key=OPENAI_API_KEY)
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": f"""Given this invoice address info (country missing), return ONLY the ISO 3166-1 alpha-2 country code (2 letters, e.g. NZ, AU, US). If unsure, return null.
Address: {text}""",
                }],
                temperature=0,
                max_tokens=5,
            )
            raw = (resp.choices[0].message.content or "").strip().upper()
            if raw and len(raw) == 2 and raw.isalpha() and raw != "NULL":
                logger.info(f"AI inferred country code: {raw} from hints: {text[:80]}...")
                return raw
        except Exception as e:
            logger.debug(f"AI country inference failed: {e}")
        return None
    
    def _calculate_temporal_fields(self, invoice_date: Optional[date]) -> Dict[str, Any]:
        """Calculate fiscal quarter, year, and season from invoice date"""
        if not invoice_date:
            return {
                'invoice_date': None,
                'fiscal_quarter': None,
                'fiscal_year': None,
                'season': None
            }
        
        # Ensure it's a date object
        if isinstance(invoice_date, str):
            try:
                invoice_date = datetime.strptime(invoice_date, '%Y-%m-%d').date()
            except:
                return {
                    'invoice_date': None,
                    'fiscal_quarter': None,
                    'fiscal_year': None,
                    'season': None
                }
        
        month = invoice_date.month
        year = invoice_date.year
        
        # Calculate fiscal quarter
        fiscal_quarter = f"Q{(month - 1) // 3 + 1}"
        
        # Determine season (Northern Hemisphere)
        if month in [12, 1, 2]:
            season = "Winter"
        elif month in [3, 4, 5]:
            season = "Spring"
        elif month in [6, 7, 8]:
            season = "Summer"
        else:  # 9, 10, 11
            season = "Fall"
        
        return {
            'invoice_date': invoice_date,
            'fiscal_quarter': fiscal_quarter,
            'fiscal_year': year,
            'season': season
        }
    
    def _determine_lifecycle_stage(self, validated_invoice) -> Dict[str, str]:
        """Determine current lifecycle stage and status"""
        # Check if converted
        try:
            from ..models.converted_invoice import ConvertedInvoice
            from sqlalchemy.orm import Session
            
            # This will be called with db session available
            # For now, return based on validation status
            stage = "VALIDATED"
            stage_status = "SUCCESS" if validated_invoice.status == "success" else "FAILED"
            
            return {
                'current_stage': stage,
                'stage_status': stage_status
            }
        except:
            return {
                'current_stage': "VALIDATED",
                'stage_status': "SUCCESS" if validated_invoice.status == "success" else "FAILED"
            }
    
    def _to_decimal(self, value: Any) -> Optional[Decimal]:
        """Convert value to Decimal, handling various input types"""
        if value is None:
            return None
        
        try:
            if isinstance(value, Decimal):
                return value
            elif isinstance(value, (int, float)):
                return Decimal(str(value))
            elif isinstance(value, str):
                # Remove currency symbols and commas
                cleaned = value.replace(',', '').replace('$', '').replace('€', '').replace('£', '').strip()
                return Decimal(cleaned) if cleaned else None
            else:
                return None
        except:
            return None
    
    def _parse_date(self, date_value: Any) -> Optional[date]:
        """Parse date from various formats"""
        if date_value is None:
            return None
        
        if isinstance(date_value, date):
            return date_value
        
        if isinstance(date_value, datetime):
            return date_value.date()
        
        if isinstance(date_value, str):
            # Try common formats
            for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y%m%d']:
                try:
                    return datetime.strptime(date_value, fmt).date()
                except:
                    continue
        
        return None
