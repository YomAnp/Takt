import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import MarkdownIt from "markdown-it";
import GithubSlugger from "github-slugger";

const markdown = new MarkdownIt({ html: true });
const defaultRoot = fileURLToPath(new URL("../../", import.meta.url));

function filesIn(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(directory, entry.name);
    return entry.isDirectory() ? filesIn(target) : [target];
  });
}

function inventory(root) {
  const files = filesIn(path.join(root, "docs")).filter((file) => file.endsWith(".md"));
  if (!files.length) throw new Error("No Markdown documents found");
  return new Map(files.map((file) => {
    const source = new TextDecoder("utf-8", { fatal: true }).decode(fs.readFileSync(file));
    const tokens = markdown.parse(source, {});
    const inline = tokens.flatMap((token) => token.children ?? []);
    return [file, { source, tokens, inline }];
  }));
}

function sameValues(left, right) {
  return JSON.stringify([...left].sort()) === JSON.stringify([...right].sort());
}

function linkTargets(document) {
  return document.inline.flatMap((token) => {
    if (token.type === "link_open") return [token.attrGet("href")];
    if (token.type === "image") return [token.attrGet("src")];
    return [];
  });
}

function anchors(document) {
  const slugger = new GithubSlugger();
  const result = new Set();
  document.tokens.forEach((token, index) => {
    if (token.type === "heading_open") {
      const text = (document.tokens[index + 1].children ?? [])
        .filter((child) => ["text", "code_inline", "image"].includes(child.type))
        .map((child) => child.content).join("");
      result.add(slugger.slug(text));
    }
    if (["html_block", "inline"].includes(token.type)) {
      for (const match of token.content.matchAll(/\b(?:id|name)=["']([^"']+)["']/g)) {
        result.add(match[1]);
      }
    }
  });
  return result;
}

function exactPath(root, target) {
  const relative = path.relative(root, target);
  if (relative === ".." || relative.startsWith(".." + path.sep) || path.isAbsolute(relative)) {
    return false;
  }
  let current = root;
  for (const segment of relative.split(path.sep).filter(Boolean)) {
    if (!fs.existsSync(current) || !fs.statSync(current).isDirectory()) return false;
    if (!fs.readdirSync(current).includes(segment)) return false;
    current = path.join(current, segment);
  }
  return fs.existsSync(current);
}

export function checkDocs(mode, root = defaultRoot) {
  root = path.resolve(root);
  const docs = inventory(root);
  const errors = [];
  const fail = (file, message) => errors.push(path.relative(root, file) + ": " + message);

  if (mode === "encoding") {
    for (const [file, doc] of docs) {
      if (doc.source.includes("\uFFFD")) fail(file, "Unicode replacement character found");
      const prose = doc.inline.filter((t) => t.type === "text").map((t) => t.content).join(" ");
      if (/\?{3,}/.test(prose)) fail(file, "Repeated question marks may indicate damaged encoding");
      if (path.relative(root, file).split(path.sep)[1] === "ru" && !/[\u0400-\u04FF]/.test(prose)) {
        fail(file, "Russian page contains no Cyrillic prose");
      }
    }
  } else if (mode === "links") {
    for (const [file, doc] of docs) {
      for (const href of linkTargets(doc)) {
        if (/^(?:[a-z][a-z\d+.-]*:|\/\/)/i.test(href)) continue;
        const rawPath = decodeURIComponent(href.split(/[?#]/, 1)[0]);
        const target = rawPath
          ? path.resolve(rawPath.startsWith("/") ? root : path.dirname(file),
              rawPath.replace(/^\//, ""))
          : file;
        if (!exactPath(root, target)) {
          fail(file, "Missing or incorrectly cased link: " + href);
          continue;
        }
        const fragment = decodeURIComponent(href.includes("#") ? href.slice(href.indexOf("#") + 1) : "");
        if (fragment && docs.has(target) && !anchors(docs.get(target)).has(fragment)) {
          fail(file, "Missing heading or anchor: " + href);
        }
      }
    }
  } else if (mode === "translations") {
    const languageFiles = (language) => [...docs.keys()]
      .filter((file) => path.relative(root, file).split(path.sep)[1] === language)
      .map((file) => path.relative(path.join(root, "docs", language), file));
    const ruFiles = languageFiles("ru");
    const enFiles = languageFiles("en");
    if (!sameValues(ruFiles, enFiles) || !ruFiles.length) {
      errors.push("Russian and English page sets must match and must not be empty");
    }
    for (const relative of ruFiles) {
      const ruPath = path.join(root, "docs/ru", relative);
      const enPath = path.join(root, "docs/en", relative);
      if (!docs.has(enPath)) continue;
      const ru = docs.get(ruPath);
      const en = docs.get(enPath);
      const numbers = (doc) => [...doc.inline
        .filter((t) => ["text", "code_inline"].includes(t.type))
        .map((t) => t.content).join(" ").matchAll(/\d+(?::\d+|\.\d+)*/g)].map((m) => m[0]);
      const identifiers = (doc) => doc.inline.filter((t) => t.type === "code_inline").map((t) => t.content);
      const sources = (doc) => linkTargets(doc).filter((href) => /^https?:/.test(href));
      if (!sameValues(numbers(ru), numbers(en))) fail(ruPath, "Numbers differ from English counterpart");
      if (!sameValues(identifiers(ru), identifiers(en))) fail(ruPath, "Code identifiers differ from English counterpart");
      if (!sameValues(sources(ru), sources(en))) fail(ruPath, "External sources differ from English counterpart");
      for (const [from, to] of [[ruPath, enPath], [enPath, ruPath]]) {
        const linked = linkTargets(docs.get(from)).some((href) =>
          !/^[a-z][a-z\d+.-]*:/i.test(href) &&
          path.resolve(path.dirname(from), decodeURIComponent(href.split(/[?#]/, 1)[0])) === to);
        if (!linked) fail(from, "Missing link to corresponding language page");
      }
    }
  } else {
    throw new Error("Unknown check: " + mode);
  }
  return { files: docs.size, errors };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const { files, errors } = checkDocs(process.argv[2], process.argv[3]);
    for (const error of errors) console.error(error);
    if (errors.length) process.exitCode = 1;
    else console.log(process.argv[2] + ": " + files + " documents passed");
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
