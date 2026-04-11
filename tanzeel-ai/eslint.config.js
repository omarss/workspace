const { defineConfig } = require("eslint/config");

const expoConfig = (() => {
  try {
    return require("eslint-config-expo/flat");
  } catch {
    // eslint-config-expo not installed yet — provide empty config so lint doesn't crash
    return [];
  }
})();

module.exports = defineConfig([
  ...expoConfig,
  {
    ignores: ["server/**", "worker/**", "node_modules/**"],
  },
]);
