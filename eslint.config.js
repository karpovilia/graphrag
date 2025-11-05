import plugins from "@krainovsd/presets/eslint";

export default [
  ...plugins.presets.vue,
  {
    ignores: ["tmp/", "node_modules/", ".turbo/", "dist/", "storybook-static/"],
  },
  {
    rules: {
      camelcase: "off",
      "max-params": ["error", 4],
      "vue/no-v-text-v-html-on-component": "off",
      "vue/no-v-html": "off",
    },
  },
];
