// eslint.config.mjs
import js from "@eslint/js";
import reactPlugin from "eslint-plugin-react";
import globals from "globals";

export default [
  js.configs.recommended,
  {
    files: ["**/*.{js,jsx}"],
    plugins: {
      react: reactPlugin,
    },
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: {
        ...globals.browser,
        ...globals.node,
      },
      parserOptions: {
        ecmaFeatures: {
          jsx: true,
        },
      },
    },
    rules: {
      // قواعد من Airbnb (معدلة)
      "react/jsx-uses-react": "error",
      "react/jsx-uses-vars": "error",
      "react/prop-types": "off", // إيقاف التحقق من الأنواع

      // قواعد مخصصة
      "no-console": "warn",
      quotes: ["error", "single"],
      semi: ["error", "always"],
    },
    settings: {
      react: {
        version: "detect", // الكشف التلقائي لإصدار React
      },
    },
  },
];
