export type FollowupChip = { label: string; question: string };

const FOLLOWUP_MAP: { match: RegExp; label: string }[] = [
  { match: /supplier concentration|purchase-order value|concentrated suppliers/i, label: 'Show supplier concentration' },
  { match: /highest supplier|which supplier is highest|the highest one|largest supplier/i, label: 'Show the highest supplier' },
  { match: /what percentage|show the percentage|share of purchase/i, label: 'Show the percentage' },
  { match: /^show top 3\.?$|top 3 suppliers/i, label: 'Show top 3' },
  { match: /customer contribution/i, label: 'Show customers' },
  { match: /industry breakdown/i, label: 'Break down by industry' },
  { match: /country|region|land1/i, label: 'Break down by region' },
  { match: /year comparison/i, label: 'Compare with last year' },
  { match: /monthly trend/i, label: 'Show monthly trend' },
  { match: /quarterly trend/i, label: 'Show quarterly trend' },
  { match: /product breakdown/i, label: 'Show products' },
  { match: /invoice document cost|wavwr/i, label: 'Show COGS' },
  { match: /gross margin/i, label: 'Show margin' },
  { match: /quantity \/ volume/i, label: 'Show quantity' },
  { match: /average selling|asp/i, label: 'Show ASP' },
  { match: /order → delivery|process links/i, label: 'Show selling process' },
  { match: /purchase order \/ vendor/i, label: 'Show buying process' },
  { match: /vendors sourcing|supplier/i, label: 'Show suppliers' },
  { match: /stock value|inventory snapshot|mbew/i, label: 'Show inventory' },
  { match: /plant code|mard\.werks|warehouse/i, label: 'Show inventory by plant' },
  { match: /material group|product group|mara\.matkl/i, label: 'Show product groups' },
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
    // Labels may be shortened, but sending a chip must retain its actual
    // question, including the period, metric, filters, and selected entities.
    const chip: FollowupChip = {
      label: mapped?.label || stripTechnical(text) || text,
      question: text,
    };
    const key = chip.question.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(chip);
    if (out.length >= limit) break;
  }
  return out;
}
