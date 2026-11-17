type NavigableTrip = {
  id: string;
  starts_on?: string;
  display_key?: string;
  kind?: "trip" | "quarter";
  archived?: boolean;
};

/** Keep the supplied permission scope; show every unarchived trip, earliest first. */
export function listedTrips<T extends NavigableTrip>(trips: readonly T[], includeQuarters = false): T[] {
  return trips
    .filter((trip) => !trip.archived && (includeQuarters || (trip.kind !== "quarter" && !trip.id.startsWith("quarter:"))))
    .sort((a, b) => {
      const aDate = a.starts_on || "9999-99-99";
      const bDate = b.starts_on || "9999-99-99";
      if (aDate !== bDate) return aDate < bDate ? -1 : 1;
      const aKey = a.display_key || "";
      const bKey = b.display_key || "";
      return aKey < bKey ? -1 : aKey > bKey ? 1 : 0;
    });
}
