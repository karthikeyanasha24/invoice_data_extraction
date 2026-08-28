export type FollowupChip = { label: string; question: string };

const FOLLOWUP_MAP: { match: RegExp; label: string; question: string }[] = [
  { match: /supplier concentration|purchase-order value|concentrated suppliers/i, label: 'Show supplier concentration', question: 'Show supplier concentration.' },
  { match: /highest supplier|which supplier is highest|the highest one|largest supplier/i, label: 'Show the highest supplier', question: 'Show the highest supplier.' },
  { match: /what percentage|show the percentage|share of purchase/i, label: 'Show the percentage', question: 'Show the percentage.' },
  { match: /^show top 3\.?$|top 3 suppliers/i, label: 'Show top 3', question: 'Show top 3.' },
  { match: /customer contribution/i, label: 'Show customers', question: 'Show their customers.' },
  { match: /industry breakdown/i, label: 'Break down by industry', question: 'Show their industries.' },
  { match: /country|region|land1/i, label: 'Break down by region', question: 'Show their regions.' },
  { match: /year comparison/i, label: 'Compare with last year', question: 'Compare their sales with last year.' },
  { match: /monthly trend/i, label: 'Show monthly trend', question: 'Show monthly revenue.' },
  { match: /quarterly trend/i, label: 'Show quarterly trend', question: 'Show quarterly revenue.' },
  { match: /product breakdown/i, label: 'Show products', question: 'Show their products.' },
  { match: /invoice document cost|wavwr/i, label: 'Show COGS', question: 'Show COGS.' },
  { match: /gross margin/i, label: 'Show margin', question: 'Show their margin.' },
  { match: /quantity \/ volume/i, label: 'Show quantity', question: 'Show quantity sold.' },
  { match: /average selling|asp/i, label: 'Show ASP', question: 'Show ASP.' },
  { match: /order → delivery|process links/i, label: 'Show selling process', question: 'Show the selling process.' },
  { match: /purchase order \/ vendor/i, label: 'Show buying process', question: 'Show the buying process.' },
  { match: /vendors sourcing|supplier/i, label: 'Show suppliers', question: 'Show their suppliers.' },
  { match: /stock value|inventory snapshot|mbew/i, label: 'Show inventory', question: 'Show their inventory.' },
  { match: /plant code|mard\.werks|warehouse/i, label: 'Show inventory by plant', question: 'Show inventory by plant.' },
  { match: /material group|product group|mara\.matkl/i, label: 'Show product groups', question: 'Show their product groups.' },
];

function stripTechnical(raw: string): string {
  return raw
    .replace(/\s*\([^)]*(LAND1|VBRK|WAVWR|MBEW|MARD|MARA|FKDAT|WERKS|MATKL|BRSCH)[^)]*\)/gi, '')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

export function humanizeFollowups(raw: string[] | undefined | null, limit = 6): FollowupChip[] {
  const seen = new Set<string>();
  const out: FollowupChip[] = [];
  for (const item of raw || []) {
    const text = String(item || '').trim();
    if (!text) continue;
    const mapped = FOLLOWUP_MAP.find((row) => row.match.test(text));
    const chip: FollowupChip = mapped
      ? { label: mapped.label, question: mapped.question }
      : { label: stripTechnical(text) || text, question: text.endsWith('?') || text.endsWith('.') ? text : `${text}.` };
    const key = chip.question.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(chip);
    if (out.length >= limit) break;
  }
  return out;
}
