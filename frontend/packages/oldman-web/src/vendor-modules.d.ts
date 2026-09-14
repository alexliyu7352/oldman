declare module "cleave.js" {
  export type CleaveDatePattern = "d" | "m" | "Y" | "y";
  export type CleaveTimePattern = "h" | "m" | "s";
  export type CleaveNumeralThousandsGroupStyle = "thousand" | "lakh" | "wan" | "none";

  export interface CleaveOptions {
    blocks?: number[];
    date?: boolean;
    datePattern?: CleaveDatePattern[];
    delimiter?: string;
    delimiters?: string[];
    numeral?: boolean;
    numeralThousandsGroupStyle?: CleaveNumeralThousandsGroupStyle;
    prefix?: string;
    time?: boolean;
    timePattern?: CleaveTimePattern[];
    uppercase?: boolean;
  }

  export default class Cleave {
    constructor(element: string | HTMLInputElement, options: CleaveOptions);
    destroy(): void;
    getRawValue(): string;
    setRawValue(value: string): void;
  }
}

declare module "wnumb" {
  export interface WNumbOptions {
    decimals?: number;
    mark?: string;
    negativeBefore?: string;
    negative?: string;
    thousand?: string;
    prefix?: string;
    suffix?: string;
    encoder?: (value: number) => number;
    decoder?: (value: number) => number;
    edit?: (value: string, original: number) => string;
    undo?: (value: string) => string;
  }

  export interface WNumbFormatter {
    to(value: number): string;
    from(value: string): number | false;
  }

  export default function wNumb(options?: WNumbOptions): WNumbFormatter;
}

declare module "node-waves" {
  const Waves: {
    init(): void;
  };

  export default Waves;
}

declare module "toastify-js" {
  export interface ToastifyOptions {
    callback?: () => void;
    className?: string;
    close?: boolean;
    duration?: number;
    gravity?: "bottom" | "top";
    node?: HTMLElement;
    onClick?: () => void;
    position?: "center" | "left" | "right";
    stopOnFocus?: boolean;
  }

  export interface ToastifyInstance {
    hideToast(): void;
    showToast(): void;
  }

  export default function Toastify(options: ToastifyOptions): ToastifyInstance;
}
