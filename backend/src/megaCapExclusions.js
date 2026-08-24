// Static exclusion list for the Scanner: broad-market/sector ETFs and
// mega-cap/blue-chip stocks. These have too much float and too little
// idiosyncratic volatility to fit a low-float momentum trading style, so
// they're excluded from Scanner results outright -- regardless of
// RVOL/price/trend -- rather than just ranked low. Reasonably long, not
// exhaustive: covers the names that keep showing up in "most active"/
// "movers" screeners without being a real fit for this style.

const BROAD_MARKET_ETFS = [
  "SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "VUG", "VTV", "IVV", "IJH",
  "IJR", "MDY", "VEA", "VWO", "EFA", "EEM", "ACWI", "ACWX",
];

const SECTOR_ETFS = [
  "XLF", "XLK", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE",
  "XLC", "SMH", "SOXX", "XBI", "IBB", "ARKK", "ARKG", "ARKW", "ARKF",
  "FDN", "IGV", "KRE", "XOP", "ITB", "IYR",
];

const BOND_ETFS = ["AGG", "BND", "TLT", "IEF", "SHY", "LQD", "HYG", "TIP", "MUB"];

const COMMODITY_ETFS = ["GLD", "SLV", "USO", "UNG", "DBC", "GDX", "GDXJ"];

const OTHER_BROAD_ETFS = ["SCHD", "VYM", "DVY", "SPLV", "VXX", "UVXY", "VIXY"];

const MEGA_CAP_STOCKS = [
  "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA", "WMT",
  "JPM", "V", "MA", "UNH", "JNJ", "PG", "HD", "CVX", "XOM", "BAC", "KO",
  "PEP", "COST", "ABBV", "MRK", "LLY", "AVGO", "ORCL", "CRM", "NFLX",
  "ADBE", "DIS", "MCD", "NKE", "TMO", "ABT", "PFE", "CSCO", "INTC", "IBM",
  "GE", "VZ", "T", "CMCSA", "TMUS", "BA", "CAT", "GS", "MS", "C", "WFC",
  "BLK", "SCHW", "AXP", "SPGI", "UPS", "HON", "RTX", "LMT", "LOW", "TGT",
  "SBUX", "QCOM", "TXN", "AMD", "MU", "ACN", "DE", "MDT", "BMY", "AMGN",
  "GILD", "CVS", "ELV", "CI", "SO", "DUK", "NEE", "D", "AEP", "LIN",
  "APD", "ECL", "SHW", "EMR", "ITW", "PH", "MMC", "AON", "PGR", "TRV",
  "ALL", "MET", "PRU", "USB", "PNC", "TFC", "COF", "ICE", "CME", "NDAQ",
  "MCO", "PYPL", "ADSK", "NOW", "INTU", "TJX", "BKNG", "GM", "F",
];

export const MEGA_CAP_EXCLUDED = new Set([
  ...BROAD_MARKET_ETFS,
  ...SECTOR_ETFS,
  ...BOND_ETFS,
  ...COMMODITY_ETFS,
  ...OTHER_BROAD_ETFS,
  ...MEGA_CAP_STOCKS,
]);
