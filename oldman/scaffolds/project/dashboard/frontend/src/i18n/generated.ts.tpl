export interface LanguageDefinition {
  readonly code: string;
  readonly locale: string;
  readonly aliases: readonly string[];
  readonly flag: string;
  readonly flagUrl?: string;
  readonly catalogPath: string;
  readonly name: string;
}

export const defaultLanguage = "en";

export const languageDefinitions = [
  {
    code: "en",
    locale: "en",
    aliases: ["en-US"],
    flag: "",
    flagUrl: "",
    catalogPath: "i18n/en.json",
    name: "English",
  },
] as const satisfies readonly LanguageDefinition[];

export const supportedLanguageCodes = languageDefinitions.map((language) => language.code);

export const languageAliases: Record<string, string> = {
  "en": "en",
  "en-US": "en",
  "en-us": "en",
};

export const localeToLanguageCode: Record<string, string> = {
  "en": "en",
};
