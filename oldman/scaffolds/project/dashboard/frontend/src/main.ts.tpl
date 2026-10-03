import "./app.css";
import { setupPage } from "oldman-web/core";
import { startDashboard } from "oldman-web/dashboard";
import { defaultLanguage, languageAliases, languageDefinitions, languagePreferencePath } from "./i18n/generated";
import { BasePage } from "./pages/base-page";

const pageEntries = import.meta.glob("./pages/*.ts");

// Pages that name no entry of their own (the framework's account pages among them) use the base page.
setupPage("backend", BasePage);

void startDashboard({
  i18n: {
    aliases: languageAliases,
    defaultLanguage,
    languagePreferencePath,
    languages: languageDefinitions
  },
  // A page entry nothing registered still gets the dashboard shell, with a console warning.
  fallbackPage: BasePage,
  pageLoader: async (pageName) => {
    const loader = pageEntries[`./pages/${pageName}.ts`];
    if (loader) await loader();
  }
}).catch((error: unknown) => {
  console.error("Dashboard startup failed", error);
});
