/**
 * useHashRoute — minimal hash-based router (no react-router dep).
 *
 * The portal is a single-page app; we don't need a real router for
 * 4-6 view tabs. `window.location.hash` is the URL of record and
 * `hashchange` is the event we subscribe to. The initial hash on
 * first mount becomes the active route; missing/invalid hashes
 * fall back to ``defaultValue``.
 *
 * Why hash routes (not pushState):
 *   * No server-side config required (Traefik serves the SPA from
 *     /portal/app/ and doesn't need a SPA-fallback rewrite).
 *   * Back/forward buttons work for free.
 *   * Deep links survive a refresh.
 *   * No extra dependency.
 *
 * The trade-off: hashes are a bit ugly (`#/operate` vs `/operate`).
 * Acceptable for an internal LAN demo; we'd switch to a real router
 * before exposing this URL publicly.
 */

import { useEffect, useState, useCallback } from "react";

export function useHashRoute<T extends string>(
  validValues: readonly T[],
  defaultValue: T,
): [T, (next: T) => void] {
  const parseHash = useCallback((): T => {
    if (typeof window === "undefined") return defaultValue;
    const raw = window.location.hash.replace(/^#\/?/, "");
    const normalized = raw.split("?")[0] as T;
    if (validValues.includes(normalized)) return normalized;
    return defaultValue;
  }, [validValues, defaultValue]);

  const [route, setRoute] = useState<T>(parseHash);

  useEffect(() => {
    function onChange() {
      setRoute(parseHash());
    }
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, [parseHash]);

  const setRouteAndHash = useCallback(
    (next: T) => {
      if (!validValues.includes(next)) return;
      // Update state directly so the URL change doesn't fight us.
      setRoute(next);
      if (typeof window !== "undefined") {
        const newHash = `#/${next}`;
        if (window.location.hash !== newHash) {
          window.history.replaceState(null, "", newHash);
        }
      }
    },
    [validValues],
  );

  return [route, setRouteAndHash];
}
