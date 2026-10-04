@import "@fontsource/dm-sans/latin-400.css";
@import "@fontsource/dm-sans/latin-500.css";
@import "@fontsource/dm-sans/latin-600.css";
@import "tailwindcss";
@import "oldman-web/styles/tailwind.css";
@import "oldman-web/styles/icons.css";
@import "./generated/icons.css";

@source "../../templates";
@source "../../apps/**/*.py";
@source "./**/*.ts";

/* Theme: override the shared --om-* variables (the framework's asset docs list them) inside @layer base, where the
   framework defines them, and give the dark theme its own value. A rule outside the layer wins over every layered
   one, the framework's dark values included, so dark pages would get the light value. Remove the comment to use it:

@layer base {
  :root {
    --om-color-primary: var(--color-indigo-600);
  }

  html[data-theme="dark"] {
    --om-color-primary: var(--color-indigo-400);
  }
}
*/
