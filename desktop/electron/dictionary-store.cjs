const fs = require("node:fs/promises");
const path = require("node:path");

const MAX_TERM_CHARS = 500;
const MAX_TERMS = 20000;

function text(value, name) {
  if (typeof value !== "string" || !value.trim() || value.length > MAX_TERM_CHARS) {
    throw new Error(`${name} 必须是 1-${MAX_TERM_CHARS} 字的非空字符串`);
  }
  return value;
}

/**
 * Atomically write a flat {source: target} glossary JSON.
 * updates: array of {source, target}; sources must be unique and non-empty.
 */
async function writeDictionary(filePath, updates) {
  if (!Array.isArray(updates)) throw new Error("术语表更新必须是数组");
  if (updates.length > MAX_TERMS) throw new Error(`术语表条目超过上限（${MAX_TERMS}）`);
  const seen = new Set();
  const dictionary = {};
  for (const [index, update] of updates.entries()) {
    const item = update && typeof update === "object" && !Array.isArray(update) ? update : null;
    if (!item) throw new Error(`updates[${index}] 必须是对象`);
    const source = text(item.source, `updates[${index}].source`);
    const target = typeof item.target === "string" ? item.target : "";
    if (!target.trim()) throw new Error(`updates[${index}].target 不能为空`);
    const key = source.trim();
    if (seen.has(key)) throw new Error(`术语原文重复：${key.slice(0, 60)}`);
    seen.add(key);
    dictionary[key] = target;
  }
  const sorted = Object.fromEntries(Object.entries(dictionary).sort(([a], [b]) => a.localeCompare(b, "en")));
  const resolved = path.resolve(filePath);
  const temporary = `${resolved}.tmp-${process.pid}`;
  await fs.writeFile(temporary, `${JSON.stringify(sorted, null, 2)}\n`, "utf8");
  await fs.rename(temporary, resolved);
  return { updated: Object.keys(sorted).length, path: resolved };
}

/** Read a flat glossary JSON into row form; tolerant of empty objects. */
async function readDictionary(filePath) {
  const resolved = path.resolve(filePath);
  const payload = JSON.parse(await fs.readFile(resolved, "utf8"));
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("术语表必须是 JSON 对象");
  }
  const rows = Object.entries(payload).map(([source, target], index) => ({
    id: String(index + 1),
    source,
    target: typeof target === "string" ? target : "",
  }));
  return { updated: rows.length, path: resolved, rows };
}

module.exports = { writeDictionary, readDictionary };
