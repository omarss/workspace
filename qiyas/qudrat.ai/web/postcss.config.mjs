// Tailwind v4 plugs into PostCSS via this single plugin. No content paths
// here — Tailwind v4 reads the `@source` directives in app/globals.css.
const config = {
  plugins: {
    '@tailwindcss/postcss': {},
  },
};

export default config;
