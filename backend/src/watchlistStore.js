import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_FILE = path.join(__dirname, "..", "watchlists.json");

function load() {
  if (!fs.existsSync(DATA_FILE)) return {};
  try {
    return JSON.parse(fs.readFileSync(DATA_FILE, "utf-8"));
  } catch {
    return {};
  }
}

function save(data) {
  fs.writeFileSync(DATA_FILE, JSON.stringify(data, null, 2));
}

export function getAllWatchlists() {
  return load();
}

export function getWatchlist(name) {
  return load()[name] || [];
}

export function createWatchlist(name) {
  const data = load();
  if (!data[name]) data[name] = [];
  save(data);
  return data[name];
}

export function deleteWatchlist(name) {
  const data = load();
  delete data[name];
  save(data);
}

export function addSymbol(name, symbol) {
  const data = load();
  if (!data[name]) data[name] = [];
  symbol = symbol.toUpperCase();
  if (!data[name].includes(symbol)) data[name].push(symbol);
  save(data);
  return data[name];
}

export function removeSymbol(name, symbol) {
  const data = load();
  if (!data[name]) return [];
  data[name] = data[name].filter((s) => s !== symbol.toUpperCase());
  save(data);
  return data[name];
}
