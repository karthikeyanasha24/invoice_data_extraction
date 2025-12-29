"""
SAT-SAP Account Mapping Service
Handles Excel upload, parsing, and mapping lookups for SAT-SAP account mapping
"""
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
import pandas as pd
import logging
from io import BytesIO

from ..models.sat_sap_account_mapping import SATSAPAccountMapping

logger = logging.getLogger(__name__)


class SATAccountMappingService:
    """Service for managing SAT-SAP account mappings"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def parse_excel_mapping_file(self, file_content: bytes, sheet_name: str = None) -> List[Dict[str, Any]]:
        """
        Parse Excel file containing SAT-SAP account mappings.
        
        Expected Excel columns:
        - ClaveProdServ (or similar)
        - SAP_GL_Account / G/L Account / GL Account
        - Code_Group / CodeGroup / Group
        - Description
        - Account_Type (optional)
        
        Args:
            file_content: Excel file bytes
            sheet_name: Sheet name to read (if None, reads first sheet)
        
        Returns:
            List of dictionaries with parsed mapping data
        """
        try:
            logger.info("📄 Parsing Excel mapping file...")
            
            # Read Excel file
            if sheet_name:
                df = pd.read_excel(BytesIO(file_content), sheet_name=sheet_name)
            else:
                df = pd.read_excel(BytesIO(file_content))
            
            logger.info(f"📊 Found {len(df)} rows in Excel file")
            logger.info(f"📋 Columns: {list(df.columns)}")
            
            # Normalize column names (handle different naming conventions)
            df.columns = df.columns.str.strip()
            column_mapping = self._normalize_column_names(df.columns)
            
            if not column_mapping:
                raise ValueError("Could not find required columns in Excel file. Expected: ClaveProdServ, GL_Account, Code_Group")
            
            df = df.rename(columns=column_mapping)
            
            # Convert to list of dicts
            mappings = []
            for idx, row in df.iterrows():
                try:
                    # Skip empty rows
                    if pd.isna(row.get('clave_prod_serv')) or str(row.get('clave_prod_serv')).strip() == '':
                        continue
                    
                    mapping = {
                        'clave_prod_serv': str(row['clave_prod_serv']).strip(),
                        'sap_gl_account': str(row.get('sap_gl_account', '')).strip(),
                        'code_group': str(row.get('code_group', '99')).strip(),
                        'description': str(row.get('description', '')).strip() if pd.notna(row.get('description')) else None,
                        'description_en': str(row.get('description_en', '')).strip() if pd.notna(row.get('description_en')) else None,
                        'account_type': str(row.get('account_type', '')).strip() if pd.notna(row.get('account_type')) else None,
                        'sat_category': str(row.get('sat_category', '')).strip() if pd.notna(row.get('sat_category')) else None,
                    }
                    
                    # Validate required fields
                    if not mapping['sap_gl_account']:
                        logger.warning(f"Row {idx + 2}: Missing SAP GL Account for ClaveProdServ {mapping['clave_prod_serv']}")
                        continue
                    
                    mappings.append(mapping)
                    
                except Exception as e:
                    logger.error(f"Error parsing row {idx + 2}: {e}")
                    continue
            
            logger.info(f"✅ Successfully parsed {len(mappings)} valid mappings")
            return mappings
            
        except Exception as e:
            logger.error(f"❌ Error parsing Excel file: {e}")
            raise ValueError(f"Failed to parse Excel file: {str(e)}")
    
    def _normalize_column_names(self, columns: List[str]) -> Dict[str, str]:
        """
        Normalize column names to standard format.
        Handles various naming conventions from different Excel files.
        """
        mapping = {}
        
        for col in columns:
            col_lower = col.lower().replace(' ', '_').replace('-', '_')
            
            # ClaveProdServ variations
            if any(term in col_lower for term in ['claveprodserv', 'clave_prod', 'sat_code', 'product_service']):
                mapping[col] = 'clave_prod_serv'
            
            # SAP G/L Account variations
            elif any(term in col_lower for term in ['gl_account', 'g/l_account', 'sap_account', 'account_number', 'glaccount']):
                mapping[col] = 'sap_gl_account'
            
            # Code Group variations
            elif any(term in col_lower for term in ['code_group', 'codegroup', 'group', 'codgrp']):
                mapping[col] = 'code_group'
            
            # Description variations
            elif col_lower in ['description', 'desc', 'descripcion', 'name']:
                if 'description' not in mapping.values():
                    mapping[col] = 'description'
                else:
                    mapping[col] = 'description_en'
            
            # Description English
            elif any(term in col_lower for term in ['description_en', 'desc_en', 'english']):
                mapping[col] = 'description_en'
            
            # Account Type
            elif any(term in col_lower for term in ['account_type', 'type', 'classification']):
                mapping[col] = 'account_type'
            
            # SAT Category
            elif any(term in col_lower for term in ['sat_category', 'category', 'categoria']):
                mapping[col] = 'sat_category'
        
        # Check if required columns are present
        required = ['clave_prod_serv', 'sap_gl_account']
        if not all(field in mapping.values() for field in required):
            logger.error(f"Missing required columns. Found: {list(mapping.values())}")
            return None
        
        return mapping
    
    def bulk_upsert_mappings(self, mappings: List[Dict[str, Any]], overwrite: bool = False) -> Dict[str, int]:
        """
        Bulk insert or update account mappings.
        
        Args:
            mappings: List of mapping dictionaries
            overwrite: If True, update existing mappings. If False, skip duplicates.
        
        Returns:
            Dictionary with counts: {'inserted': X, 'updated': Y, 'skipped': Z}
        """
        try:
            logger.info(f"💾 Bulk upserting {len(mappings)} mappings (overwrite={overwrite})...")
            
            inserted = 0
            updated = 0
            skipped = 0
            
            for mapping_data in mappings:
                clave = mapping_data['clave_prod_serv']
                
                # Check if mapping already exists
                existing = self.db.query(SATSAPAccountMapping).filter(
                    SATSAPAccountMapping.clave_prod_serv == clave
                ).first()
                
                if existing:
                    if overwrite:
                        # Update existing mapping
                        for key, value in mapping_data.items():
                            if key != 'clave_prod_serv':  # Don't update the key itself
                                setattr(existing, key, value)
                        updated += 1
                    else:
                        # Skip duplicate
                        skipped += 1
                else:
                    # Insert new mapping
                    new_mapping = SATSAPAccountMapping(**mapping_data)
                    self.db.add(new_mapping)
                    inserted += 1
            
            self.db.commit()
            
            logger.info(f"✅ Bulk upsert complete: {inserted} inserted, {updated} updated, {skipped} skipped")
            
            return {
                'inserted': inserted,
                'updated': updated,
                'skipped': skipped,
                'total': len(mappings)
            }
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"❌ Bulk upsert failed: {e}")
            raise
    
    def get_mapping_by_clave(self, clave_prod_serv: str) -> Optional[SATSAPAccountMapping]:
        """
        Get mapping for a specific ClaveProdServ code.
        
        Args:
            clave_prod_serv: SAT product/service code
        
        Returns:
            SATSAPAccountMapping object or None
        """
        return self.db.query(SATSAPAccountMapping).filter(
            SATSAPAccountMapping.clave_prod_serv == clave_prod_serv,
            SATSAPAccountMapping.is_active == True
        ).first()
    
    def get_all_mappings(
        self, 
        skip: int = 0, 
        limit: int = 100,
        search: Optional[str] = None,
        account_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get all account mappings with pagination and filters.
        
        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            search: Search term for ClaveProdServ, GL Account, or Description
            account_type: Filter by account type
        
        Returns:
            Dictionary with 'total' count and 'mappings' list
        """
        query = self.db.query(SATSAPAccountMapping)
        
        # Apply filters
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                (SATSAPAccountMapping.clave_prod_serv.ilike(search_term)) |
                (SATSAPAccountMapping.sap_gl_account.ilike(search_term)) |
                (SATSAPAccountMapping.description.ilike(search_term)) |
                (SATSAPAccountMapping.description_en.ilike(search_term))
            )
        
        if account_type:
            query = query.filter(SATSAPAccountMapping.account_type == account_type)
        
        total = query.count()
        mappings = query.offset(skip).limit(limit).all()
        
        return {
            'total': total,
            'mappings': [m.to_dict() for m in mappings]
        }
    
    def delete_mapping(self, mapping_id: int) -> bool:
        """Delete a mapping by ID"""
        mapping = self.db.query(SATSAPAccountMapping).filter(
            SATSAPAccountMapping.id == mapping_id
        ).first()
        
        if mapping:
            self.db.delete(mapping)
            self.db.commit()
            return True
        return False
    
    def get_or_create_default_mapping(self) -> SATSAPAccountMapping:
        """
        Get or create a default fallback mapping for unknown ClaveProdServ codes.
        Uses: ClaveProdServ = "01010101", GL Account = "409999", Code Group = "99"
        """
        default = self.db.query(SATSAPAccountMapping).filter(
            SATSAPAccountMapping.is_default == True
        ).first()
        
        if not default:
            logger.info("Creating default fallback mapping...")
            default = SATSAPAccountMapping(
                clave_prod_serv="01010101",
                sap_gl_account="409999",
                code_group="99",
                description="Generic / Unknown Product",
                description_en="Generic / Unknown Product",
                account_type="Generic",
                is_default=True,
                is_active=True
            )
            self.db.add(default)
            self.db.commit()
            self.db.refresh(default)
        
        return default
    
    def map_clave_to_gl_account(self, clave_prod_serv: str) -> Dict[str, Any]:
        """
        Map a ClaveProdServ to SAP G/L Account with fallback logic.
        
        Args:
            clave_prod_serv: SAT product/service code
        
        Returns:
            Dictionary with GL account, code group, and description
        """
        # Try to find exact mapping
        mapping = self.get_mapping_by_clave(clave_prod_serv)
        
        if mapping:
            return {
                'sap_gl_account': mapping.sap_gl_account,
                'code_group': mapping.code_group,
                'description': mapping.description or mapping.description_en,
                'account_type': mapping.account_type,
                'found': True
            }
        
        # Fallback to default mapping
        logger.warning(f"⚠️ No mapping found for ClaveProdServ: {clave_prod_serv}, using default")
        default = self.get_or_create_default_mapping()
        
        return {
            'sap_gl_account': default.sap_gl_account,
            'code_group': default.code_group,
            'description': f"Unknown ({clave_prod_serv})",
            'account_type': default.account_type,
            'found': False,
            'original_clave': clave_prod_serv
        }

