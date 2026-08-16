// useApi — shared data hook for the dashboard (T4, F-DA-03, NF-DA-06, ADR-3).
//
// Centralizes loading / error / empty / not-found states for every island:
//   const { data, loading, error, retry } = useApi('/api/projects');
//
// - HTTP errors (including 404) become `error` with `error.status`.
// - Empty JSON (`null`, `[]`, `{}`) is returned as-is in `data`; views decide
//   how to render the empty state (NF-DA-06).
// - `retry` re-runs the fetch with the same URL.
// - Requests are abortable; a new fetch cancels the previous one.
// - A falsy `url` skips the fetch and yields `loading: false` (T10): lets views
//   keep a single data layer for optional/conditional fetches (e.g. the intento
//   gate-log dialog fetches only while a gate is selected).

import { useCallback, useEffect, useRef, useState } from 'react';

export function useApi(url) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const controllerRef = useRef(null);

  const retry = useCallback(() => {
    setError(null);
    setLoading(true);
    setAttempt((n) => n + 1);
  }, []);

  useEffect(() => {
    if (!url) {
      // Conditional/optional fetch not requested (T10): idle, not loading.
      setLoading(false);
      setError(null);
      return undefined;
    }

    const controller = new AbortController();
    controllerRef.current = controller;

    let cancelled = false;
    setLoading(true);
    setError(null);

    fetch(url, { signal: controller.signal })
      .then(async (res) => {
        const text = await res.text();
        if (!res.ok) {
          const err = new Error(`HTTP ${res.status} ${res.statusText}`.trim());
          err.status = res.status;
          err.body = text;
          throw err;
        }
        // Empty responses (204 or empty body) become null; S8/S9 views decide.
        return text ? JSON.parse(text) : null;
      })
      .then((value) => {
        if (cancelled) return;
        setData(value);
        setLoading(false);
        setError(null);
      })
      .catch((err) => {
        if (cancelled || err.name === 'AbortError') return;
        setData(null);
        setLoading(false);
        setError(err);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [url, attempt]);

  return { data, loading, error, retry };
}

export default useApi;
