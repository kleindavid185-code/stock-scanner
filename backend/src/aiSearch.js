// Lets the user describe what they're looking for in plain English and
// has Claude filter/rank the current scan candidates against that
// description. This never invents data -- it only selects and explains
// picks from the real candidate list already pulled from Alpaca.

const ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages";
const MODEL = "claude-sonnet-4-5";

function buildPrompt(query, candidates) {
  // Keep the payload compact -- send only the fields the model needs to
  // reason about, not every internal field.
  const compact = candidates.map((c) => ({
    symbol: c.symbol,
    price: c.price,
    changePct: c.changePct,
    rvol: c.rvol,
    rangePct: c.rangePct,
    gapPct: c.gapPct,
    volume: c.volume,
    score: c.score,
  }));

  return `You are filtering a list of currently-active stocks against a user's request.

User request: "${query}"

Candidate stocks (JSON array, one object per stock):
${JSON.stringify(compact)}

Field meanings: price = current price, changePct = % change today, rvol = relative volume (multiple of typical volume), rangePct = today's high-to-low range as %, gapPct = gap from yesterday's close to today's open %, volume = today's share volume, score = composite momentum/volume ranking score (higher = more active).

Select the stocks from the list above that best match the user's request. Only choose from the provided list -- never invent a symbol that isn't in it. If nothing matches well, return an empty array.

Respond with ONLY a JSON array, no other text, no markdown fences. Each element: {"symbol": string, "reason": string}. Keep "reason" to one short sentence explaining why it fits the request, referencing the actual numbers.`;
}

export async function aiSearchCandidates(query, candidates) {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    throw new Error(
      "Missing ANTHROPIC_API_KEY. Add it to your .env file to use AI search."
    );
  }

  const res = await fetch(ANTHROPIC_API_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model: MODEL,
      max_tokens: 1500,
      messages: [{ role: "user", content: buildPrompt(query, candidates) }],
    }),
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Anthropic API error ${res.status}: ${body}`);
  }

  const data = await res.json();
  const text = (data.content || [])
    .map((block) => (block.type === "text" ? block.text : ""))
    .join("");

  let picks;
  try {
    const cleaned = text.replace(/```json|```/g, "").trim();
    picks = JSON.parse(cleaned);
  } catch {
    throw new Error("Could not parse AI response as JSON");
  }

  // Merge the AI's picks + reasons back with the full candidate data so
  // the app can show price/volume/etc alongside the reasoning.
  const bySymbol = Object.fromEntries(candidates.map((c) => [c.symbol, c]));
  return picks
    .filter((p) => bySymbol[p.symbol])
    .map((p) => ({ ...bySymbol[p.symbol], reason: p.reason }));
}
