import { setupPage } from "oldman-web/core";
import { BasePage } from "./base-page";

/** The {{ app_slug }} page: add its own component loaders or actions here. */
class {{ app_class }}Page extends BasePage {}

setupPage("{{ app_slug }}", {{ app_class }}Page);
