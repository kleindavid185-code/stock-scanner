// Fetches the upcoming earnings calendar from Alpha Vantage's
// EARNINGS_CALENDAR endpoint (CSV response, parsed into JSON here) and
// filters it down to the broad tech-sector universe in techUniverse.js.

import { TECH_SYMBOLS } from "./techUniverse.js";

const ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query";

function apiKey() {
  const key = process.env.ALPHA_VANTAGE_API_KEY;
  if (!key) {
    throw new Error(
      "Missing ALPHA_VANTAGE_API_KEY. Add it to your .env file to use the earnings calendar."
    );
  }
  return key;
}

// Minimal CSV parser -- handles double-quoted fields (which may contain
// commas, e.g. `"Some Company, Inc."`) since Alpha Vantage doesn't
// guarantee the name column is comma-free.
function parseCsv(text) {
  const lines = text.trim().split(/\r?\n/);
  if (!lines.length) return [];

  const parseLine = (line) => {
    const fields = [];
    let cur = "";
    let inQuotes = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (inQuotes) {
        if (ch === '"' && line[i + 1] === '"') {
          cur += '"';
          i++;
        } else if (ch === '"') {
          inQuotes = false;
        } else {
          cur += ch;
        }
      } else if (ch === '"') {
        inQuotes = true;
      } else if (ch === ",") {
        fields.push(cur);
        cur = "";
      } else {
        cur += ch;
      }
    }
    fields.push(cur);
    return fields;
  };

  const headers = parseLine(lines[0]).map((h) => h.trim());
  return lines
    .slice(1)
    .filter(Boolean)
    .map((line) => {
      const values = parseLine(line);
      const row = {};
      headers.forEach((h, i) => {
        row[h] = values[i] !== undefined ? values[i].trim() : "";
      });
      return row;
    });
}

/**
 * Raw parsed rows from Alpha Vantage's earnings calendar:
 * { symbol, name, reportDate, fiscalDateEnding, estimate, currency }
 */
async function fetchEarningsCalendar(horizon = "3month") {
  const url = new URL(ALPHA_VANTAGE_URL);
  url.searchParams.set("function", "EARNINGS_CALENDAR");
  url.searchParams.set("horizon", horizon);
  url.searchParams.set("apikey", apiKey());

  const res = await fetch(url);
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Alpha Vantage API error ${res.status}: ${body}`);
  }
  const csv = await res.text();

  // Alpha Vantage returns a JSON body (not CSV) for bad requests or when
  // rate-limited -- detect that rather than silently parsing garbage rows.
  const trimmed = csv.trim();
  if (trimmed.startsWith("{")) {
    let message = trimmed;
    try {
      const parsed = JSON.parse(trimmed);
      message = parsed.Note || parsed.Information || parsed["Error Message"] || trimmed;
    } catch {
      // fall through with raw text
    }
    throw new Error(`Alpha Vantage did not return earnings CSV data: ${message}`);
  }

  const rows = parseCsv(csv);

  // Alpha Vantage has also been observed returning HTTP 200 with a
  // CSV-shaped body for error cases (e.g. a missing/blank apikey), where
  // the error text gets mangled into a single row that technically
  // parses but isn't real earnings data (e.g. a "symbol" of "E" from the
  // word "Error"). A real row always has an ISO reportDate -- use that
  // as a sanity check so this doesn't silently look like "no earnings".
  const looksValid = rows.every((r) => /^\d{4}-\d{2}-\d{2}$/.test(r.reportDate));
  if (!looksValid) {
    throw new Error(
      `Alpha Vantage returned an unexpected response instead of earnings data: ${trimmed.slice(0, 200)}`
    );
  }

  return rows;
}

/**
 * Upcoming earnings for the tech-sector universe, sorted by report date.
 */
export async function getTechEarnings(horizon = "3month") {
  const rows = await fetchEarningsCalendar(horizon);
  return rows
    .filter((r) => TECH_SYMBOLS.has(r.symbol))
    .map((r) => ({
      symbol: r.symbol,
      company: r.name,
      reportDate: r.reportDate,
      fiscalQuarterEnd: r.fiscalDateEnding,
      epsEstimate: r.estimate === "" || r.estimate === "None" ? null : Number(r.estimate),
    }))
    .sort((a, b) => (a.reportDate < b.reportDate ? -1 : a.reportDate > b.reportDate ? 1 : 0));
}
