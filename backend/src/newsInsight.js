// Synthesizes "why is this stock moving" from recent news headlines --
// grounded strictly in the actual articles, not a price prediction. Mirrors
// aiSearch.js's direct-fetch pattern for calling Claude (same model already
// used elsewhere in this backend).

import { getNews } from "./alpacaClient.js";

const ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages";
const MODEL = "claude-sonnet-4-5";

function buildPrompt(symbol, newsItems) {
  const compact = newsItems.map((n) => ({
    headline: n.headline,
    summary: n.summary || null,
    source: n.source,
    created_at: n.created_at,
  }));

  return `You are a research assistant helping a day trader understand why a stock is moving, based only on recent news headlines. You are NOT predicting future price.

Symbol: ${symbol}

Recent news (JSON array, newest first):
${JSON.stringify(compact, null, 2)}

Rules:
- Base your read ONLY on the headlines/summaries provided. Do not invent news you weren't given, and don't assume anything about price action beyond what's implied by the news itself.
- This is a NEWS-BASED READ, not a prediction. Never give a price target, never say the stock "will" go up or down. Describe what the news suggests and how traders might interpret it -- nothing more.
- If the news doesn't clearly explain a move, say so plainly rather than forcing a narrative.
- Only name a specific catalyst (earnings, FDA news, contract announcement, upgrade/downgrade, dilution/offering, short report, etc.) if one is clearly identifiable in the headlines. Otherwise use null.
- "watchFor" should describe what to monitor next (follow-up filings, guidance calls, further coverage) -- not a price level or direction guarantee.

Output ONLY valid JSON matching this exact shape, no preamble, no markdown fences:
{
  "summary": string (2-4 sentences synthesizing what appears to be driving the stock, grounded in the specific headlines),
  "sentiment": "bullish" | "bearish" | "mixed" | "neutral",
  "catalyst": string or null (one short phrase naming the specific catalyst if identifiable),
  "watchFor": string (one or two sentences on what a day trader should watch for next)
}`;
}

function emptyNewsSynthesis() {
  return {
    summary:
      "No recent news found for this symbol. Today's move (if any) doesn't appear to be news-driven, or coverage just hasn't been indexed yet.",
    sentiment: "neutral",
    catalyst: null,
    watchFor:
      "Watch for any headline that breaks intraday -- price/volume action without accompanying news is more likely driven by technical levels or a broader sector move than a fundamental catalyst.",
  };
}

function isValidSynthesisShape(candidate) {
  return (
    candidate &&
    typeof candidate === "object" &&
    typeof candidate.summary === "string" &&
    typeof candidate.sentiment === "string"
  );
}

/**
 * @param {string} symbol
 * @returns {Promise<{symbol: string, synthesis: object, headlines: object[], generatedAt: string}>}
 */
export async function getStockInsight(symbol) {
  const news = await getNews(symbol, 10);

  const headlines = news.map((n) => ({
    headline: n.headline,
    source: n.source,
    url: n.url,
    createdAt: n.created_at,
  }));

  if (!news.length) {
    return {
      symbol,
      synthesis: emptyNewsSynthesis(),
      headlines,
      generatedAt: new Date().toISOString(),
    };
  }

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    throw new Error(
      "Missing ANTHROPIC_API_KEY. Add it to your .env file to use news insight."
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
      max_tokens: 600,
      messages: [{ role: "user", content: buildPrompt(symbol, news) }],
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

  let synthesis;
  try {
    const cleaned = text.replace(/```json|```/g, "").trim();
    const parsed = JSON.parse(cleaned);
    if (!isValidSynthesisShape(parsed)) {
      throw new Error("Parsed JSON did not match the expected synthesis shape.");
    }
    synthesis = parsed;
  } catch (err) {
    console.error(`[news-insight] malformed Claude response for ${symbol}:`, err.message, "raw:", text);
    synthesis = {
      summary: "Couldn't synthesize a read from the news right now -- raw headlines are still shown below.",
      sentiment: "neutral",
      catalyst: null,
      watchFor: "Review the headlines below directly.",
    };
  }

  return { symbol, synthesis, headlines, generatedAt: new Date().toISOString() };
}
