// API client tests need a same-origin browser location, while fetch, Response,
// Blob, File and FormData must all come from Node's matching implementation.
// Component suites can opt into jsdom with Vitest's environment directive.
if (typeof window === "undefined") {
  Object.assign(globalThis, { window: { location: new URL("http://localhost") } });
}
