const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");

const { writeDictionary, readDictionary } = require("./dictionary-store.cjs");

async function tempFile(name) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "hanengine-dict-"));
  return path.join(directory, name);
}

test("writes a sorted flat glossary and reads it back", async () => {
  const file = await tempFile("glossary.json");
  const result = await writeDictionary(file, [
    { source: "Headshot", target: "爆头" },
    { source: "Clownfish", target: "小丑鱼" },
  ]);
  assert.equal(result.updated, 2);
  const payload = JSON.parse(await fs.readFile(file, "utf8"));
  assert.deepEqual(payload, { Clownfish: "小丑鱼", Headshot: "爆头" });
  const back = await readDictionary(file);
  assert.equal(back.rows.length, 2);
  assert.equal(back.rows[0].source, "Clownfish");
});

test("rejects empty sources, empty targets, and duplicates", async () => {
  const file = await tempFile("glossary.json");
  await assert.rejects(() => writeDictionary(file, [{ source: "", target: "空" }]), /source/);
  await assert.rejects(() => writeDictionary(file, [{ source: "Boss", target: "  " }]), /target/);
  await assert.rejects(
    () => writeDictionary(file, [{ source: "Boss", target: "首领" }, { source: " Boss ", target: "头目" }]),
    /重复/,
  );
});

test("overwrites an existing glossary atomically without leaving temp files", async () => {
  const file = await tempFile("glossary.json");
  await writeDictionary(file, [{ source: "Old", target: "旧" }]);
  await writeDictionary(file, [{ source: "New", target: "新" }]);
  const payload = JSON.parse(await fs.readFile(file, "utf8"));
  assert.deepEqual(payload, { New: "新" });
  const leftovers = (await fs.readdir(path.dirname(file))).filter((name) => name.includes(".tmp-"));
  assert.equal(leftovers.length, 0);
});
