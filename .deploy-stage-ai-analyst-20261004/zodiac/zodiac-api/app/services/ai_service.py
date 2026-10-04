import logging
import traceback
import asyncio
import time
from openai import OpenAI
from ..config.config import OPENAI_API_KEY
client = OpenAI(api_key=OPENAI_API_KEY)

logger = logging.getLogger("zodiac-api.ai_service")

async def _call_openai_with_retry(
    messages: list,
    model: str = "gpt-4o-mini",
    temperature: float = 0.3,
    max_retries: int = 3,
    timeout: int = 30
) -> str:
    """
    Call OpenAI API with retry logic and timeout
    
    Args:
        messages: List of chat messages
        model: OpenAI model to use
        temperature: Temperature parameter
        max_retries: Maximum number of retry attempts
        timeout: Timeout in seconds per attempt
    
    Returns:
        str: AI response content
    
    Raises:
        Exception: If all retries fail
    """
    last_error = None
    
    for attempt in range(max_retries):
        try:
            logger.info(f"🤖 AI request attempt {attempt + 1}/{max_retries}")
            start_time = time.time()
            
            # Call OpenAI API (synchronous, but we'll handle timeout)
            completion = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                timeout=timeout
            )
            
            elapsed = time.time() - start_time
            logger.info(f"✅ AI response received in {elapsed:.2f}s")
            
            content = completion.choices[0].message.content.strip()
            
            # Validate response
            if not content:
                raise ValueError("Empty response from AI")
            
            return content
            
        except Exception as e:
            last_error = e
            elapsed = time.time() - start_time
            logger.warning(f"⚠️ AI request attempt {attempt + 1} failed after {elapsed:.2f}s: {e}")
            
            # Don't retry on last attempt
            if attempt < max_retries - 1:
                # Exponential backoff: 2^attempt seconds (2s, 4s, 8s)
                backoff = 2 ** attempt
                logger.info(f"⏳ Retrying in {backoff}s...")
                await asyncio.sleep(backoff)
            else:
                logger.error(f"❌ All {max_retries} AI request attempts failed")
    
    # All retries failed
    raise Exception(f"AI request failed after {max_retries} attempts: {last_error}")


async def auto_correct_xml_with_ai(xml_content: str, strict_validation: bool) -> tuple[bool, str]:
    """
    Use AI (GPT) to analyze and correct XML structure or content issues.
    Returns (was_corrected, corrected_xml)
    """
    try:
        logger.info("🧠 Starting AI-powered XML correction...")
        logger.debug(f"   XML length: {len(xml_content)} chars")
        logger.debug(f"   Strict validation: {strict_validation}")
        
        # Enhanced prompt with common error patterns
        prompt = f"""
You are an XML data correction assistant for e-invoices (UBL and SAT CFDI formats).

COMMON ISSUES TO FIX:
1. Missing or invalid EndpointID elements (supplier/customer)
2. Invalid date formats (should be YYYY-MM-DD)
3. Missing required namespaces
4. Malformed XML tags or attributes
5. Missing mandatory elements (ID, IssueDate, etc.)
6. Incorrect decimal formatting for amounts

INSTRUCTIONS:
- Correct any syntax, structure, or schema-related issues
- Keep the same business data and structure
- Only fix formatting, tag mismatches, or missing required elements
- If EndpointID is missing, use supplier/customer tax ID or name
- Respond ONLY with corrected XML
- Output must start with '<' and be valid XML
- NO markdown formatting (no ```, no ```xml, no explanations)

Strict validation mode: {strict_validation}

XML TO CORRECT:
{xml_content}
"""

        messages = [{"role": "user", "content": prompt}]
        
        # Call with retry logic
        corrected_xml = await _call_openai_with_retry(
            messages=messages,
            model="gpt-4o-mini",
            temperature=0.3,
            max_retries=3,
            timeout=30
        )
        
        # Clean up any remaining markdown artifacts
        corrected_xml = corrected_xml.strip()
        for marker in ["```xml", "```", "``"]:
            corrected_xml = corrected_xml.replace(marker, "")
        corrected_xml = corrected_xml.strip()
        
        # Validate that the result is XML
        if not corrected_xml.startswith("<"):
            logger.error(f"❌ AI output doesn't start with '<': {corrected_xml[:100]}")
            return False, xml_content
        
        # Check if anything was actually changed
        if corrected_xml == xml_content:
            logger.info("ℹ️ AI correction produced no changes")
            return False, xml_content
        
        # Try to parse to ensure valid XML
        try:
            from lxml import etree
            etree.fromstring(corrected_xml.encode('utf-8'))
            logger.info("✅ AI-corrected XML is valid and parseable")
        except Exception as parse_err:
            logger.error(f"❌ AI-corrected XML is not valid: {parse_err}")
            return False, xml_content
        
        logger.info("✅ XML correction successful")
        return True, corrected_xml

    except Exception as e:
        logger.error(f"❌ AI XML correction failed: {e}")
        logger.error(f"   Error type: {type(e).__name__}")
        logger.error(f"   Traceback: {traceback.format_exc()}")
        return False, xml_content

async def auto_fix_edi_with_ai(
    xml_content: str,
    edi_content: str,
    edi_errors: str | list,
    strict_validation: bool
) -> tuple[bool, str]:
    """
    AI-assisted EDI correction and reformatting function.
    Fixes validation errors (ISA, GS, N1, etc.) using XML context and strict format rules.
    Returns (was_corrected, corrected_edi)
    """

    try:
        if isinstance(edi_errors, list):
            formatted_errors = "\n".join(
                [f"- {err.error_context.error_category if hasattr(err, 'error_context') else 'UNKNOWN'}: {err.user_message if hasattr(err, 'user_message') else str(err)}" for err in edi_errors]
            )
        else:
            formatted_errors = str(edi_errors)

        edi_validation_rules = """
EDI 810 STRICT FORMAT RULES:
1. ISA Segment (16 fields, fixed-length):
   - ISA06 (Sender ID): Must be exactly 15 characters (pad right with spaces if shorter).
   - ISA08 (Receiver ID): Must be exactly 15 characters (pad right with spaces if shorter).
   - ISA09 (Date): YYMMDD format.
   - ISA10 (Time): HHMM format.
   - Field separator: '*', segment terminator: '~'.

2. GS Segment:
   - GS02: Application Sender Code must be 2 characters (usually first 2 letters of Sender ID).
   - GS03: Application Receiver Code must be 2 characters (usually first 2 letters of Receiver ID).

3. N1 Segments:
   - Each invoice must have exactly two N1 segments:
     • One for Seller → must use Entity Identifier Code 'SE'
     • One for Buyer → must use Entity Identifier Code 'BY'
   - The Seller (SE) Name and ID should match the XML supplier/sender.
   - The Buyer (BY) Name and ID should match the XML customer/receiver.
   - Example:
       N1*SE*SAP Australia*12*SENDERID~
       N1*BY*RUN BEST PTY LTD*12*RECEIVERID~

4. Maintain all EDI segment ordering and structure (ST → BIG → N1 → IT1 → TDS → SE → GE → IEA).
5. Keep data accurate to XML (invoice number, date, totals, currency).
6. Do not include markdown, explanations, or comments — output only valid EDI text.
"""

        prompt = f"""
You are an expert in EDI X12 810 invoice correction and validation.
Your task is to fix all listed EDI format and mapping errors using the XML source data.

Follow all the rules below strictly:
{edi_validation_rules}

Strict validation: {strict_validation}

---
XML CONTENT:
{xml_content}
---
CURRENT EDI:
{edi_content}
---
ERRORS TO FIX:
{formatted_errors}
"""

        logger.info("🧠 Starting AI-powered EDI correction...")
        logger.debug(f"   EDI length: {len(edi_content)} chars")
        logger.debug(f"   Number of errors: {len(edi_errors) if isinstance(edi_errors, list) else 1}")

        messages = [{"role": "user", "content": prompt}]
        
        # Call with retry logic
        corrected_edi = await _call_openai_with_retry(
            messages=messages,
            model="gpt-4o-mini",
            temperature=0.2,
            max_retries=3,
            timeout=30
        )

        # Remove potential markdown fences (safety)
        corrected_edi = corrected_edi.strip()
        for marker in ("```edi", "```", "``"):
            corrected_edi = corrected_edi.replace(marker, "")
        corrected_edi = corrected_edi.strip()

        # ✅ Auto-format ISA and N1 fixes as safety net (post-AI)
        lines = corrected_edi.split("~")
        fixed_lines = []
        for line in lines:
            if line.startswith("ISA*"):
                parts = line.split("*")
                # Ensure 15-char sender/receiver IDs
                if len(parts) > 6:
                    parts[6] = parts[6].ljust(15)[:15]
                if len(parts) > 8:
                    parts[8] = parts[8].ljust(15)[:15]
                line = "*".join(parts)
            elif line.startswith("N1*SU*"):
                # Convert SU → SE (Seller)
                line = line.replace("N1*SU*", "N1*SE*")
            fixed_lines.append(line)
        corrected_edi = "~".join(fixed_lines)

        # Validate that the result starts with ISA (EDI header)
        if not corrected_edi.startswith("ISA"):
            logger.error(f"❌ AI output doesn't start with 'ISA': {corrected_edi[:100]}")
            return False, edi_content
        
        if corrected_edi and corrected_edi != edi_content:
            logger.info("✅ AI corrected EDI successfully based on validation rules")
            logger.debug(f"   Original length: {len(edi_content)}, Corrected length: {len(corrected_edi)}")
            return True, corrected_edi
        else:
            logger.info("ℹ️ AI EDI correction produced no changes")
            return False, edi_content

    except Exception as e:
        logger.error(f"❌ AI EDI correction failed: {e}")
        logger.error(f"   Error type: {type(e).__name__}")
        logger.error(f"   Traceback: {traceback.format_exc()}")
        return False, edi_content
