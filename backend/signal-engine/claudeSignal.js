/**
 * claudeSignal.js
 * Sends a computed indicator bundle to Claude and gets back a structured
 * signal: direction, confidence, reasoning, and key levels.
 *
 * Requires ANTHROPIC_API_KEY in your environment (same as your existing
 * natural-language query box in the scanner app backend).
 */

import Anthropic from "@anthropic-ai/sdk";

const anthropic = new Anthropic({
  apiKey: process.env.ANTHROPIC_API_KEY,
});

const MODEL = "claude-sonnet-4-5";

const SYSTEM_PROMPT = `You are a technical analysis assistant embedded in a personal intraday stock scanner. You are given computed technical indicators for a single symbol, not raw chart images. Your job is to interpret the indicators like an experienced discretionary trader would, and output a structured signal.

Rules:
- Base your read ONLY on the indicator data provided. Do not assume information you weren't given.
- Be conservative: if the indicators are mixed or inconclusive, say "neutral" rather than forcing a direction.
- Confidence should reflect how well the indicators agree with each other, not how exciting the setup looks.
- Never suggest position sizing, leverage, or dollar amounts — this tool identifies technical setups only, it does not give financial advice.
- The indicator data includes a precomputed "expectedRange" (today/tomorrow low-high, derived from ATR(14)). This is a statistical volatility estimate, not a prediction. Do not calculate or guess these numbers yourself — you may reference them in your reasoning, but the exact figures are supplied separately and will overwrite anything you output for these fields.
- Output ONLY valid JSON matching this exact shape, no preamble, no markdown fences:
{
  "symbol": string,
  "direction": "bullish" | "bearish" | "neutral",
  "confidence": number (0-100),
  "reasoning": string (2-4 sentences, plain language, cite the specific indicator values that drove the call),
  "key_level_watch": string (one specific price or condition to watch next, e.g. "break above VWAP at 4.82 on rising rel volume"),
  "expected_range_today": { "low": number, "high": number },
  "expected_range_tomorrow": { "low": number, "high": number }
}`;

/**
 * Claude sometimes wraps the signal object in an extra layer (e.g.
 * { "signal": { ... } }) despite the system prompt asking for the flat
 * shape. If we get a single-key object whose value looks like a signal,
 * unwrap it rather than treating the wrapper as the signal itself.
 */
function unwrapSignalShape(parsed) {
  if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
    if ("direction" in parsed) return parsed;
    const keys = Object.keys(parsed);
    if (keys.length === 1) {
      const inner = parsed[keys[0]];
      if (inner && typeof inner === "object" && "direction" in inner) {
        return inner;
      }
    }
  }
  return parsed;
}

function isValidSignalShape(candidate) {
  return (
    candidate &&
    typeof candidate === "object" &&
    typeof candidate.direction === "string" &&
    typeof candidate.confidence === "number" &&
    typeof candidate.reasoning === "string"
  );
}

/**
 * @param {string} symbol
 * @param {object} indicatorBundle - output of computeIndicatorBundle()
 * @returns {Promise<object>} structured signal
 */
async function getSignal(symbol, indicatorBundle) {
  const userContent = JSON.stringify(
    {
      symbol,
      indicators: indicatorBundle,
    },
    null,
    2
  );

  const response = await anthropic.messages.create({
    model: MODEL,
    max_tokens: 500,
    system: SYSTEM_PROMPT,
    messages: [{ role: "user", content: userContent }],
  });

  const raw = response.content
    .map((block) => (block.type === "text" ? block.text : ""))
    .join("");

  const cleaned = raw.replace(/```json|```/g, "").trim();

  // Computed directly from ATR — never taken from Claude's output, since
  // there's no reason to let a language model guess at arithmetic we can
  // do exactly ourselves.
  const expectedRangeToday = indicatorBundle?.expectedRange?.today ?? null;
  const expectedRangeTomorrow = indicatorBundle?.expectedRange?.tomorrow ?? null;

  try {
    const candidate = unwrapSignalShape(JSON.parse(cleaned));
    if (!isValidSignalShape(candidate)) {
      throw new Error("Parsed JSON did not match the expected signal shape.");
    }
    // Always trust our own symbol over whatever Claude echoed back -- this
    // is also what latestSignals is keyed on, so a mismatch here would
    // silently store the signal under the wrong (or missing) key. Same
    // logic for the expected ranges: overwrite with our own computed
    // values regardless of what Claude echoed back.
    return {
      ...candidate,
      symbol,
      expected_range_today: expectedRangeToday,
      expected_range_tomorrow: expectedRangeTomorrow,
    };
  } catch (err) {
    // Fail safe: return a neutral signal with the raw text attached so the
    // caller can log it, rather than crashing the polling loop.
    console.error(`[signal-engine] malformed Claude response for ${symbol}:`, err.message, "raw:", raw);
    return {
      symbol,
      direction: "neutral",
      confidence: 0,
      reasoning: "Signal parse error — raw model output attached for debugging.",
      key_level_watch: null,
      expected_range_today: expectedRangeToday,
      expected_range_tomorrow: expectedRangeTomorrow,
      _raw: raw,
      _error: err.message,
    };
  }
}

/**
 * Batch helper — runs signals for multiple symbols with basic concurrency
 * control so you don't blow through rate limits on a big watchlist.
 */
async function getSignalsBatch(symbolIndicatorPairs, concurrency = 4) {
  const results = [];
  const queue = [...symbolIndicatorPairs];

  async function worker() {
    while (queue.length) {
      const { symbol, indicators } = queue.shift();
      try {
        const signal = await getSignal(symbol, indicators);
        results.push(signal);
      } catch (err) {
        results.push({
          symbol,
          direction: "neutral",
          confidence: 0,
          reasoning: "Signal request failed.",
          key_level_watch: null,
          expected_range_today: indicators?.expectedRange?.today ?? null,
          expected_range_tomorrow: indicators?.expectedRange?.tomorrow ?? null,
          _error: err.message,
        });
      }
    }
  }

  await Promise.all(Array.from({ length: concurrency }, worker));
  return results;
}

export { getSignal, getSignalsBatch };
