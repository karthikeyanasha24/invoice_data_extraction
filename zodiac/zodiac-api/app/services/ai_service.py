import logging
import traceback
from openai import OpenAI
from ..config.config import OPENAI_API_KEY
client = OpenAI(api_key=OPENAI_API_KEY)

logger = logging.getLogger("zodiac-api.ai_service")
async def auto_correct_xml_with_ai(xml_content: str, strict_validation: bool) -> tuple[bool, str]:
    """
    Use AI (GPT) to analyze and correct XML structure or content issues.
    Returns (was_corrected, corrected_xml)
    """
    try:
        prompt = f"""
        You are an XML data correction assistant for e-invoices.
        Given the XML below, correct any syntax, structure, or schema-related issues
        that could cause validation or EDI conversion to fail.
        Keep the same business data and structure; only fix formatting, tag mismatches, or missing required elements.
        Respond ONLY with corrected XML, no explanations.should always start with < and end with xml format, no extra text such as ``` or ```xml or anything else please.

        Strict validation: {strict_validation}
        ---
        {xml_content}
        """

        completion = client.chat.completions.create(
            model="gpt-4o-mini",  # or gpt-5 if available
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )

        corrected_xml = completion.choices[0].message.content.strip()
        try:
            corrected_xml = corrected_xml.replace("```xml", "")
            corrected_xml = corrected_xml.replace("```", "")
        except:
            traceback.print_exc()
        if corrected_xml and corrected_xml != xml_content:
            return True, corrected_xml
        else:
            return False, xml_content

    except Exception as e:
        logger.warning(f"⚠️ AI correction failed: {e}")
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

        logger.info("🤖 Sending EDI correction request to AI model...")

        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )

        corrected_edi = completion.choices[0].message.content.strip()

        # Remove potential markdown fences (safety)
        for marker in ("```edi", "```", "``"):
            corrected_edi = corrected_edi.replace(marker, "")

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

        if corrected_edi and corrected_edi != edi_content:
            logger.info(
                "✅ AI corrected EDI successfully based on validation rules.")
            return True, corrected_edi
        else:
            logger.warning("⚠️ AI correction produced no significant changes.")
            return False, edi_content

    except Exception as e:
        logger.warning(f"⚠️ AI EDI correction failed: {e}")
        return False, edi_content
