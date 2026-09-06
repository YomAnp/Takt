import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { checkDocs } from "./check-docs.mjs";

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "takt-docs-test-"));
  t.after(() => {
    if (path.dirname(root) !== path.resolve(os.tmpdir()) ||
        !path.basename(root).startsWith("takt-docs-test-")) {
      throw new Error("Unexpected fixture directory");
    }
    fs.rmSync(root, { recursive: true, force: true });
  });
  const ru = path.join(root, "docs/ru/index.md");
  const en = path.join(root, "docs/en/index.md");
  fs.mkdirSync(path.dirname(ru), { recursive: true });
  fs.mkdirSync(path.dirname(en), { recursive: true });
  fs.writeFileSync(ru, "# Учёт\n\n[English](../en/index.md)\n\nНорма 6 часов. `initData`.\n");
  fs.writeFileSync(en, "# Accounting\n\n[Русский](../ru/index.md)\n\nRequired time: 6 hours. `initData`.\n");
  return { root, ru, en };
}

test("valid bilingual documentation passes all integrity checks", (t) => {
  const { root } = fixture(t);
  for (const mode of ["encoding", "links", "translations"]) {
    assert.deepEqual(checkDocs(mode, root).errors, []);
  }
});

test("invalid UTF-8 fails instead of silently replacing bytes", (t) => {
  const { root, ru } = fixture(t);
  fs.writeFileSync(ru, Buffer.from([0xc3, 0x28]));
  assert.throws(() => checkDocs("encoding", root));
});

test("encoding corruption and lost Cyrillic are reported", (t) => {
  const { root, ru } = fixture(t);
  fs.writeFileSync(ru, "# ???\n\n\uFFFD\n");
  assert.equal(checkDocs("encoding", root).errors.length, 3);
});

test("reference links and duplicate heading anchors are resolved", (t) => {
  const { root, en } = fixture(t);
  fs.appendFileSync(en, "\n[Section][section]\n\n[section]: #details-1\n\n## Details\n\nFirst.\n\n## Details\n\nSecond.\n");
  assert.deepEqual(checkDocs("links", root).errors, []);
});

test("missing files, incorrect case, missing anchors and escaped paths fail", (t) => {
  const { root, en } = fixture(t);
  fs.appendFileSync(en, "\n[Missing](missing.md)\n[Case](Index.md)\n[Anchor](#unknown)\n[Outside](../../../outside.md)\n");
  assert.equal(checkDocs("links", root).errors.length, 4);
});

test("an unmatched language page fails", (t) => {
  const { root, ru } = fixture(t);
  fs.writeFileSync(path.join(path.dirname(ru), "extra.md"), "# Дополнение\n");
  assert.match(checkDocs("translations", root).errors.join("\n"), /page sets/);
});

test("changed numbers, identifiers and sources are reported", (t) => {
  const { root, en } = fixture(t);
  fs.writeFileSync(en, "# Accounting\n\n[Русский](../ru/index.md)\n\n7 hours. `initDataUnsafe`. [Source](https://example.com/)\n");
  const errors = checkDocs("translations", root).errors.join("\n");
  assert.match(errors, /Numbers differ/);
  assert.match(errors, /Code identifiers differ/);
  assert.match(errors, /External sources differ/);
});

test("a language switch to the wrong page fails", (t) => {
  const { root, en } = fixture(t);
  fs.writeFileSync(en, fs.readFileSync(en, "utf8").replace("../ru/index.md", "../ru/other.md"));
  assert.match(checkDocs("translations", root).errors.join("\n"), /corresponding language/);
});
