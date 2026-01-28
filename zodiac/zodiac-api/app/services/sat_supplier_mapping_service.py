"""
SAT Supplier Mapping Service
Manages RFC to SAP G/L Account mappings.
"""
import logging
from typing import List, Optional, Dict
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..models.sat_supplier_account_mapping import SATSupplierAccountMapping

logger = logging.getLogger("zodiac-api.sat_supplier_mapping")

# Lazy import pandas to avoid import errors if not installed
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    logger.warning("⚠️ pandas not available - Excel upload feature will be disabled")
    PANDAS_AVAILABLE = False
    pd = None


class SATSupplierMappingService:
    def __init__(self, db: Session):
        self.db = db
    
    def parse_excel_mapping_file(self, file_content: bytes) -> List[Dict]:
        """
        Parse Excel file containing supplier RFC to G/L account mappings.
        Expected columns: RFC, CTA (G/L Account), CTAS (Description), IS_ACTIVE
        New columns: COMPANY_CO, FISC_YR, CURR, OPEN_BAL, CRED, DEBE, CLOS_BAL
        """
        if not PANDAS_AVAILABLE:
            raise ImportError("pandas library is required for Excel file parsing but is not installed")
        
        try:
            # Read Excel file
            df = pd.read_excel(file_content, engine='openpyxl')
            
            # Normalize column names
            df.columns = self._normalize_column_names(df.columns)
            
            logger.info(f"📊 Excel columns: {list(df.columns)}")
            
            # Validate required columns
            required = ['rfc', 'cta']
            missing = [col for col in required if col not in df.columns]
            if missing:
                raise ValueError(f"Missing required columns: {missing}")
            
            # Convert to list of dicts
            mappings = []
            for _, row in df.iterrows():
                try:
                    mapping = {
                        'supplier_rfc': str(row['rfc']).strip().upper(),
                        'sap_gl_account': str(row['cta']).strip(),
                        'account_description': str(row.get('ctas', '')) if pd.notna(row.get('ctas')) else None,
                        'is_active': self._parse_boolean(row.get('is_active', True)),
                        # New fields
                        'company_code': str(row['company_co']).strip() if 'company_co' in row and pd.notna(row.get('company_co')) else None,
                        'fiscal_year': int(row['fisc_yr']) if 'fisc_yr' in row and pd.notna(row.get('fisc_yr')) else None,
                        'currency': str(row['curr']).strip().upper() if 'curr' in row and pd.notna(row.get('curr')) else 'MXN',
                        'opening_balance': float(row['open_bal']) if 'open_bal' in row and pd.notna(row.get('open_bal')) else 0.0,
                        'credit_amount': float(row['cred']) if 'cred' in row and pd.notna(row.get('cred')) else 0.0,
                        'debit_amount': float(row['debe']) if 'debe' in row and pd.notna(row.get('debe')) else 0.0,
                        'closing_balance': float(row['clos_bal']) if 'clos_bal' in row and pd.notna(row.get('clos_bal')) else 0.0
                    }
                    
                    # Skip empty rows
                    if not mapping['supplier_rfc'] or mapping['supplier_rfc'] == 'NAN':
                        continue
                    
                    mappings.append(mapping)
                except Exception as e:
                    logger.warning(f"⚠️ Skipping row due to error: {e}")
                    continue
            
            logger.info(f"✅ Parsed {len(mappings)} mappings from Excel")
            return mappings
            
        except Exception as e:
            logger.error(f"❌ Failed to parse Excel file: {e}")
            raise ValueError(f"Failed to parse Excel file: {str(e)}")
    
    def _normalize_column_names(self, columns):
        """Normalize column names to lowercase and remove spaces."""
        normalized = []
        for col in columns:
            col_lower = str(col).lower().strip()
            # Map common variations
            if col_lower in ['rfc', 'supplier_rfc', 'vendor_rfc']:
                normalized.append('rfc')
            elif col_lower in ['cta', 'gl_account', 'sap_gl_account', 'account', 'gl_acc']:
                normalized.append('cta')
            elif col_lower in ['ctas', 'description', 'account_description']:
                normalized.append('ctas')
            elif col_lower in ['is_active', 'active', 'status']:
                normalized.append('is_active')
            elif col_lower in ['company_co', 'company_code', 'companyco']:
                normalized.append('company_co')
            elif col_lower in ['fisc_yr', 'fiscal_year', 'fiscyr']:
                normalized.append('fisc_yr')
            elif col_lower in ['curr', 'currency']:
                normalized.append('curr')
            elif col_lower in ['open_bal', 'opening_balance', 'openbal']:
                normalized.append('open_bal')
            elif col_lower in ['cred', 'credit', 'credit_amount']:
                normalized.append('cred')
            elif col_lower in ['debe', 'debit', 'debit_amount']:
                normalized.append('debe')
            elif col_lower in ['clos_bal', 'closing_balance', 'closbal']:
                normalized.append('clos_bal')
            else:
                normalized.append(col_lower)
        return normalized
    
    def _parse_boolean(self, value) -> bool:
        """Parse boolean from various formats."""
        if pd.isna(value):
            return True
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.lower() in ['true', 'yes', '1', 'active', 'y']
        return True
    
    def bulk_upsert_mappings(self, mappings: List[Dict]) -> Dict[str, int]:
        """
        Bulk insert or update supplier mappings.
        Returns counts of created, updated, and skipped records.
        """
        created = 0
        updated = 0
        skipped = 0
        
        for mapping_data in mappings:
            try:
                rfc = mapping_data['supplier_rfc']
                
                # Check if mapping exists
                existing = self.db.query(SATSupplierAccountMapping).filter(
                    SATSupplierAccountMapping.supplier_rfc == rfc
                ).first()
                
                if existing:
                    # Update
                    existing.sap_gl_account = mapping_data['sap_gl_account']
                    existing.account_description = mapping_data.get('account_description')
                    existing.is_active = mapping_data.get('is_active', True)
                    # Update new fields
                    existing.company_code = mapping_data.get('company_code')
                    existing.fiscal_year = mapping_data.get('fiscal_year')
                    existing.currency = mapping_data.get('currency', 'MXN')
                    existing.opening_balance = mapping_data.get('opening_balance', 0.0)
                    existing.credit_amount = mapping_data.get('credit_amount', 0.0)
                    existing.debit_amount = mapping_data.get('debit_amount', 0.0)
                    existing.closing_balance = mapping_data.get('closing_balance', 0.0)
                    updated += 1
                else:
                    # Create
                    new_mapping = SATSupplierAccountMapping(
                        supplier_rfc=rfc,
                        sap_gl_account=mapping_data['sap_gl_account'],
                        account_description=mapping_data.get('account_description'),
                        is_active=mapping_data.get('is_active', True),
                        is_default=False,
                        # New fields
                        company_code=mapping_data.get('company_code'),
                        fiscal_year=mapping_data.get('fiscal_year'),
                        currency=mapping_data.get('currency', 'MXN'),
                        opening_balance=mapping_data.get('opening_balance', 0.0),
                        credit_amount=mapping_data.get('credit_amount', 0.0),
                        debit_amount=mapping_data.get('debit_amount', 0.0),
                        closing_balance=mapping_data.get('closing_balance', 0.0)
                    )
                    self.db.add(new_mapping)
                    created += 1
                
            except Exception as e:
                logger.warning(f"⚠️ Failed to process mapping for {mapping_data.get('supplier_rfc')}: {e}")
                skipped += 1
                continue
        
        self.db.commit()
        
        logger.info(f"✅ Bulk upsert complete: {created} created, {updated} updated, {skipped} skipped")
        return {"created": created, "updated": updated, "skipped": skipped}
    
    def get_mapping_by_rfc(self, supplier_rfc: str) -> Optional[SATSupplierAccountMapping]:
        """Get mapping for a specific supplier RFC."""
        return self.db.query(SATSupplierAccountMapping).filter(
            SATSupplierAccountMapping.supplier_rfc == supplier_rfc.upper(),
            SATSupplierAccountMapping.is_active == True
        ).first()
    
    def get_all_mappings(self, active_only: bool = False, skip: int = 0, limit: int = 100) -> Dict:
        """Get all supplier mappings."""
        query = self.db.query(SATSupplierAccountMapping)
        
        if active_only:
            query = query.filter(SATSupplierAccountMapping.is_active == True)
        
        total = query.count()
        mappings = query.order_by(
            SATSupplierAccountMapping.supplier_rfc
        ).offset(skip).limit(limit).all()
        
        return {
            "total": total,
            "mappings": [
                {
                    "id": m.id,
                    "supplier_rfc": m.supplier_rfc,
                    "sap_gl_account": m.sap_gl_account,
                    "account_description": m.account_description,
                    "is_active": m.is_active,
                    "is_default": m.is_default,
                    # New fields
                    "company_code": m.company_code,
                    "fiscal_year": m.fiscal_year,
                    "currency": m.currency,
                    "opening_balance": float(m.opening_balance) if m.opening_balance else 0.0,
                    "credit_amount": float(m.credit_amount) if m.credit_amount else 0.0,
                    "debit_amount": float(m.debit_amount) if m.debit_amount else 0.0,
                    "closing_balance": float(m.closing_balance) if m.closing_balance else 0.0,
                    # Timestamps
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                    "updated_at": m.updated_at.isoformat() if m.updated_at else None
                }
                for m in mappings
            ]
        }
    
    def delete_mapping(self, mapping_id: int) -> bool:
        """Delete a supplier mapping."""
        mapping = self.db.query(SATSupplierAccountMapping).filter(
            SATSupplierAccountMapping.id == mapping_id
        ).first()
        
        if not mapping:
            return False
        
        # Don't allow deleting default mapping
        if mapping.is_default:
            raise ValueError("Cannot delete default mapping")
        
        self.db.delete(mapping)
        self.db.commit()
        return True
    
    def get_or_create_default_mapping(self) -> Optional[SATSupplierAccountMapping]:
        """Get or create the default G/L account mapping."""
        default = self.db.query(SATSupplierAccountMapping).filter(
            SATSupplierAccountMapping.is_default == True
        ).first()
        
        if not default:
            # Create default mapping
            default = SATSupplierAccountMapping(
                supplier_rfc='DEFAULT',
                sap_gl_account='9999999999',
                account_description='Default unmapped supplier account',
                is_active=True,
                is_default=True
            )
            self.db.add(default)
            self.db.commit()
            self.db.refresh(default)
            logger.info("✅ Created default supplier mapping")
        
        return default

