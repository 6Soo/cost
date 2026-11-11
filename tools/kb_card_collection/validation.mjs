// 다운로드 산출물 검증 경계: 바이트/형식 지문, 원문 로그 금지, 덮어쓰기 금지 보존 경로 예약.
import { createHash } from "node:crypto";
import { open, unlink } from "node:fs/promises";
import path from "node:path";

import { AdapterError } from "./adapter.mjs";

const HTML_START = /^\s*(?:<!doctype\s+html|<html[\s>]|<head[\s>]|<body[\s>]|<meta[\s/])/i;
const OLE_SIGNATURE = [0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1];
const ZIP_SIGNATURE = [0x50, 0x4b, 0x03, 0x04];

function startsWith(buf, sig) {
  if (buf.length < sig.length) return false;
  return sig.every((b, i) => buf[i] === b);
}

function looksHtml(buf) {
  return HTML_START.test(buf.toString("utf8", 0, Math.min(buf.length, 512)));
}

function classifyKind(ext, head) {
  if (ext === ".xls") return startsWith(head, OLE_SIGNATURE) ? { kind: "xls", kindSource: "content" } : { kind: "other", kindSource: "extension" };
  if (ext === ".xlsx" || ext === ".xlsm") return startsWith(head, ZIP_SIGNATURE) ? { kind: "xlsx", kindSource: "content" } : { kind: "other", kindSource: "extension" };
  if (ext === ".csv") {
    try {
      new TextDecoder("utf-8", { fatal: true }).decode(head);
      return { kind: "csv", kindSource: "extension" };
    } catch {
      return { kind: "other", kindSource: "content" };
    }
  }
  if (looksHtml(head)) return { kind: "html", kindSource: "content" };
  if (startsWith(head, OLE_SIGNATURE)) return { kind: "xls", kindSource: "content" };
  if (startsWith(head, ZIP_SIGNATURE)) return { kind: "other", kindSource: "content" };
  return { kind: "other", kindSource: "none" };
}

export async function fileFingerprint(absPath) {
  const handle = await open(absPath, "r");
  try {
    const st = await handle.stat();
    const headLength = Math.min(4096, st.size);
    const head = Buffer.alloc(headLength);
    let headBytes = 0;
    if (headLength > 0) {
      ({ bytesRead: headBytes } = await handle.read(head, 0, headLength, 0));
    }
    const hash = createHash("sha256");
    const chunk = Buffer.alloc(65536);
    let position = 0;
    for (;;) {
      const { bytesRead, buffer } = await handle.read(chunk, 0, chunk.length, position);
      if (bytesRead === 0) break;
      hash.update(buffer.subarray(0, bytesRead));
      position += bytesRead;
    }
    const classified = classifyKind(path.extname(absPath).toLowerCase(), head.subarray(0, headBytes));
    return { bytes: st.size, sha256: hash.digest("hex"), ...classified };
  } finally {
    await handle.close();
  }
}

function rowBase(meta) {
  return {
    source: meta.source,
    sourceUrl: meta.sourceUrl,
    query: { startDate: meta.startDate, endDate: meta.endDate, postingAxis: meta.postingAxis },
    summary: meta.summary,
    file: meta.file ?? null,
    verification: meta.verification,
    parserVerification: meta.parserVerification ?? null,
  };
}

export function buildNoDataRecord({ source, sourceUrl, startDate, endDate, postingAxis, pageTotalCount, summaryAvailable = false }) {
  const hasCount = Number.isInteger(pageTotalCount) && pageTotalCount >= 0;
  const summary = {
    available: hasCount || summaryAvailable === true,
    pageTotalCount: hasCount ? pageTotalCount : null,
  };
  if (!summary.available) {
    return rowBase({
      source, sourceUrl, startDate, endDate, postingAxis, summary,
      verification: {
        status: "no_data_unverified",
        note: "0건 주장이나 조회요약 근거가 확인되지 않음(조회요약 근거 필요)",
      },
    });
  }
  if (hasCount && pageTotalCount !== 0) {
    return rowBase({
      source, sourceUrl, startDate, endDate, postingAxis, summary,
      verification: {
        status: "no_data_unverified",
        note: "0건 주장이나 전달된 요약 건수가 0이 아님",
      },
    });
  }
  return rowBase({
    source, sourceUrl, startDate, endDate, postingAxis, summary,
    verification: {
      status: "no_data",
      basis: hasCount ? "조회요약 0건" : "조회요약 근거 있음(숫자 미표기)",
    },
  });
}

export async function validateDownloaded({
  savedPath,
  source,
  sourceUrl,
  startDate,
  endDate,
  postingAxis,
  pageTotalCount = null,
  summaryAvailable = false,
  suggestedFilename = null,
}) {
  let fingerprint;
  try {
    fingerprint = await fileFingerprint(savedPath);
  } catch (err) {
    return rowBase({
      source, sourceUrl, startDate, endDate, postingAxis,
      summary: {
        available: false,
        pageTotalCount: Number.isInteger(pageTotalCount) && pageTotalCount >= 0 ? pageTotalCount : null,
      },
      file: null,
      verification: {
        status: "failed",
        failure: "saved_file_unreadable",
        ...(err && err.code ? { code: String(err.code) } : {}),
      },
    });
  }
  const hasCount = Number.isInteger(pageTotalCount) && pageTotalCount >= 0;
  const summary = {
    available: hasCount || summaryAvailable === true,
    pageTotalCount: hasCount ? pageTotalCount : null,
  };
  if (fingerprint.bytes === 0) {
    return rowBase({
      source, sourceUrl, startDate, endDate, postingAxis, summary, file: { savedPath: savedPath, ...fingerprint },
      verification: { status: "failed", failure: "empty_file" },
    });
  }
  if (fingerprint.kind === "html") {
    return rowBase({
      source, sourceUrl, startDate, endDate, postingAxis, summary, file: { savedPath: savedPath, ...fingerprint },
      verification: { status: "failed", failure: "html_or_error_page" },
    });
  }
  if (fingerprint.kind !== "xls" && fingerprint.kind !== "xlsx" && fingerprint.kind !== "csv") {
    return rowBase({
      source, sourceUrl, startDate, endDate, postingAxis, summary, file: { savedPath: savedPath, ...fingerprint },
      verification: { status: "failed", failure: "unsupported_format" },
    });
  }
  return rowBase({
    source, sourceUrl, startDate, endDate, postingAxis, summary,
    file: { savedPath: savedPath, ...fingerprint, suggestedFilename: suggestedFilename || undefined },
    verification: {
      status: hasCount ? "ok" : "ok_count_unverified",
      ...(hasCount ? {} : { note: "바이트/형식만 확인; 화면 총건수 미확인" }),
      ...(fingerprint.kindSource === "content" ? { note: "확장자 불명확; 내용 시그니처로 분류" } : {}),
    },
  });
}

// 저장 경로는 미리 존재하지 않을 때만 그대로 쓴다. 충돌 시 덮어쓰지 않고 접미 번호를 붙인다.
export async function reserveAbsentPath(absPath) {
  const ext = path.extname(absPath);
  const base = absPath.slice(0, absPath.length - ext.length);
  for (let n = 1; n <= 999; n += 1) {
    const candidate = n === 1 ? absPath : `${base}-${n}${ext}`;
    let handle;
    try {
      handle = await open(candidate, "wx");
    } catch (err) {
      if (err && err.code === "EEXIST") continue;
      throw new AdapterError("save_failed");
    }
    await handle.close();
    await unlink(candidate).catch(() => {});
    return candidate;
  }
  throw new AdapterError("path_exhausted", `no free path for ${absPath}`);
}
