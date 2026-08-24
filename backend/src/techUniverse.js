// Static, hand-curated broad tech-sector symbol universe -- semiconductors,
// software, internet/platform, hardware, cloud/enterprise infrastructure,
// and tech-adjacent communication services/media. Deliberately broader than
// just mega-caps, but not exhaustive (there's no live sector-classification
// API wired up here). Edit these lists directly to add/remove coverage.

const SEMICONDUCTORS = [
  "NVDA", "AMD", "INTC", "QCOM", "TXN", "AVGO", "MU", "ADI", "MRVL", "ON",
  "SWKS", "QRVO", "LRCX", "AMAT", "KLAC", "TSM", "ARM", "NXPI", "MPWR",
  "TER", "ENTG", "COHR", "RMBS", "LSCC", "DIOD", "POWI", "SLAB", "CRUS",
  "MTSI", "SITM", "ONTO", "FORM", "UCTT", "ACLS", "AMKR", "ASML", "WOLF",
  "GFS", "UMC", "MCHP", "SIMO", "HIMX", "SMCI",
];

const SOFTWARE = [
  "MSFT", "ORCL", "CRM", "ADBE", "INTU", "SAP", "NOW", "WDAY", "TEAM",
  "ADSK", "SNPS", "CDNS", "PANW", "CRWD", "FTNT", "ZS", "OKTA", "DDOG",
  "NET", "MDB", "SNOW", "PLTR", "HUBS", "DOCU", "ZM", "TWLO", "VEEV",
  "PAYC", "PCTY", "BILL", "ESTC", "GTLB", "FROG", "PATH", "S", "DT", "AI",
  "SMAR", "ASAN", "MNDY", "PD", "FSLY", "APPF", "TYL", "MANH", "PEGA",
  "QLYS", "RPD", "TENB", "CYBR", "VRNS", "SAIL", "BSY", "ZI", "AMPL",
  "CFLT", "DV", "APP", "U",
];

const INTERNET_PLATFORM = [
  "GOOGL", "GOOG", "META", "AMZN", "NFLX", "UBER", "ABNB", "BKNG", "EBAY",
  "ETSY", "PINS", "SNAP", "SPOT", "DASH", "RBLX", "TTD", "SHOP", "MELI",
  "SE", "BIDU", "JD", "PDD", "BABA", "CPNG", "W", "CHWY", "CVNA", "YELP",
  "ANGI", "IAC", "MTCH", "BMBL", "GRPN", "LYFT", "TRIP", "EXPE", "Z",
  "RDFN", "OPEN", "CARG",
];

const HARDWARE = [
  "AAPL", "DELL", "HPQ", "HPE", "NTAP", "WDC", "STX", "LOGI", "GPRO",
  "GRMN", "ZBRA", "KEYS", "TDY", "FFIV", "JNPR", "CIEN", "VIAV", "LITE",
  "INFN", "CALX", "EXTR", "PSTG", "ANET", "NTNX",
];

const CLOUD_ENTERPRISE = ["IBM", "CSCO", "AKAM", "DBX", "BOX", "DOCN", "RXT"];

const COMMUNICATION_SERVICES = [
  "TMUS", "VZ", "T", "CMCSA", "CHTR", "LUMN", "WBD", "DIS", "LYV", "EA",
  "TTWO", "ROKU", "FUBO", "SIRI",
];

// Payments/fintech names commonly bucketed with "tech" earnings coverage.
const FINTECH_ADJACENT = ["PYPL", "SQ", "GPN", "FIS", "FISV", "AFRM", "SOFI", "COIN"];

export const TECH_SYMBOLS = new Set([
  ...SEMICONDUCTORS,
  ...SOFTWARE,
  ...INTERNET_PLATFORM,
  ...HARDWARE,
  ...CLOUD_ENTERPRISE,
  ...COMMUNICATION_SERVICES,
  ...FINTECH_ADJACENT,
]);
