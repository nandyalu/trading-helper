/** Chart colors taken from the CSS tokens, and a way to notice a theme change.
 *
 * lightweight-charts draws to a canvas, so it cannot inherit a CSS variable
 * the way the rest of the page does. Each chart reads the tokens once when it
 * is created and again whenever the theme attribute changes; without the
 * second part, switching to the dark theme leaves black axis labels on a dark
 * card until the page is reloaded.
 */

export interface ChartTheme {
  text: string;
  grid: string;
  crosshair: string;
  line: string;
}

export function readChartTheme(): ChartTheme {
  const styles = getComputedStyle(document.documentElement);
  const token = (name: string, fallback: string) =>
    styles.getPropertyValue(name).trim() || fallback;
  return {
    text: token('--text-muted', '#888888'),
    grid: token('--border', 'rgba(128,128,128,0.15)'),
    crosshair: token('--text-muted', '#334155'),
    line: token('--accent', '#2563eb'),
  };
}

/** Calls `listener` whenever the theme changes. Returns a function that stops
 * listening; callers pass it to DestroyRef.onDestroy. */
export function watchTheme(listener: () => void): () => void {
  const observer = new MutationObserver(listener);
  observer.observe(document.documentElement, { attributeFilter: ['data-theme'] });

  const media = matchMedia('(prefers-color-scheme: dark)');
  media.addEventListener('change', listener);

  return () => {
    observer.disconnect();
    media.removeEventListener('change', listener);
  };
}
