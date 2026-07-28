const DAY_MS = 24 * 60 * 60 * 1000;

export class SaturatedMailRangeError extends Error {
  constructor(start, end, limit) {
    super(
      `메일 검색 결과가 최소 구간에서도 ${limit}건에 도달했습니다: ` +
        `${formatDate(start)}..${formatDate(end)}`,
    );
    this.name = "SaturatedMailRangeError";
  }
}

export function formatDate(value) {
  const date = value instanceof Date ? value : new Date(value);
  return date.toISOString().slice(0, 10).replaceAll("-", "/");
}

export async function exhaustiveMailSearch({
  start,
  end,
  search,
  limit = 50,
}) {
  const rows = new Map();
  let queryCount = 0;

  async function visit(rangeStart, rangeEnd) {
    queryCount += 1;
    const result = await search({
      after: formatDate(rangeStart),
      before: formatDate(rangeEnd),
      limit,
    });
    if (result.length < limit) {
      for (const row of result) rows.set(row.messageId, row);
      return;
    }

    const span = rangeEnd.getTime() - rangeStart.getTime();
    if (span <= DAY_MS) {
      throw new SaturatedMailRangeError(rangeStart, rangeEnd, limit);
    }
    const days = Math.floor(span / DAY_MS);
    const midpoint = new Date(
      rangeStart.getTime() + Math.max(1, Math.floor(days / 2)) * DAY_MS,
    );
    await visit(rangeStart, midpoint);
    await visit(midpoint, rangeEnd);
  }

  await visit(new Date(start), new Date(end));
  return {
    records: [...rows.values()],
    queryCount,
    coverageComplete: true,
    saturatedRanges: 0,
  };
}
