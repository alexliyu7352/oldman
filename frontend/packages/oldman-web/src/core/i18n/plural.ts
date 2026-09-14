type TokenType =
  | "number"
  | "identifier"
  | "operator"
  | "question"
  | "colon"
  | "leftParen"
  | "rightParen"
  | "eof";

type PluralValue = number | boolean;

interface Token {
  type: TokenType;
  value: string;
}

export function selectPluralIndex(pluralRule: string | undefined, count: number): number {
  if (!pluralRule) return count === 1 ? 0 : 1;

  try {
    const value = new PluralExpressionParser(tokenize(pluralRule), count).parse();
    return Math.max(0, Math.trunc(value));
  } catch {
    return count === 1 ? 0 : 1;
  }
}

function tokenize(input: string): Token[] {
  const tokens: Token[] = [];
  let index = 0;

  while (index < input.length) {
    const char = input[index]!;
    if (/\s/.test(char)) {
      index += 1;
      continue;
    }

    if (/\d/.test(char)) {
      const start = index;
      while (index < input.length && /\d/.test(input[index]!)) index += 1;
      tokens.push({ type: "number", value: input.slice(start, index) });
      continue;
    }

    if (/[a-zA-Z_]/.test(char)) {
      const start = index;
      while (index < input.length && /[a-zA-Z0-9_]/.test(input[index]!)) index += 1;
      tokens.push({ type: "identifier", value: input.slice(start, index) });
      continue;
    }

    const two = input.slice(index, index + 2);
    if (["&&", "||", "==", "!=", "<=", ">="].includes(two)) {
      tokens.push({ type: "operator", value: two });
      index += 2;
      continue;
    }

    if (["!", "%", "*", "/", "+", "-", "<", ">"].includes(char)) {
      tokens.push({ type: "operator", value: char });
      index += 1;
      continue;
    }

    if (char === "?") tokens.push({ type: "question", value: char });
    else if (char === ":") tokens.push({ type: "colon", value: char });
    else if (char === "(") tokens.push({ type: "leftParen", value: char });
    else if (char === ")") tokens.push({ type: "rightParen", value: char });
    else throw new Error(`Unsupported plural token: ${char}`);

    index += 1;
  }

  tokens.push({ type: "eof", value: "" });
  return tokens;
}

class PluralExpressionParser {
  private index = 0;

  constructor(
    private readonly tokens: Token[],
    private readonly count: number
  ) {}

  parse(): number {
    const value = this.parseConditional();
    this.expect("eof");
    return toNumber(value);
  }

  private parseConditional(): PluralValue {
    const condition = this.parseLogicalOr();
    if (!this.match("question")) return condition;

    const truthyValue = this.parseConditional();
    this.expect("colon");
    const falsyValue = this.parseConditional();
    return toBoolean(condition) ? truthyValue : falsyValue;
  }

  private parseLogicalOr(): PluralValue {
    let left = this.parseLogicalAnd();
    while (this.matchOperator("||")) {
      const right = this.parseLogicalAnd();
      left = toBoolean(left) || toBoolean(right);
    }
    return left;
  }

  private parseLogicalAnd(): PluralValue {
    let left = this.parseEquality();
    while (this.matchOperator("&&")) {
      const right = this.parseEquality();
      left = toBoolean(left) && toBoolean(right);
    }
    return left;
  }

  private parseEquality(): PluralValue {
    let left = this.parseComparison();
    while (true) {
      if (this.matchOperator("==")) {
        left = toNumber(left) === toNumber(this.parseComparison());
        continue;
      }
      if (this.matchOperator("!=")) {
        left = toNumber(left) !== toNumber(this.parseComparison());
        continue;
      }
      return left;
    }
  }

  private parseComparison(): PluralValue {
    let left: PluralValue = this.parseAdditive();
    while (true) {
      if (this.matchOperator("<")) {
        left = toNumber(left) < this.parseAdditive();
        continue;
      }
      if (this.matchOperator("<=")) {
        left = toNumber(left) <= this.parseAdditive();
        continue;
      }
      if (this.matchOperator(">")) {
        left = toNumber(left) > this.parseAdditive();
        continue;
      }
      if (this.matchOperator(">=")) {
        left = toNumber(left) >= this.parseAdditive();
        continue;
      }
      return left;
    }
  }

  private parseAdditive(): number {
    let left = this.parseMultiplicative();
    while (true) {
      if (this.matchOperator("+")) {
        left += this.parseMultiplicative();
        continue;
      }
      if (this.matchOperator("-")) {
        left -= this.parseMultiplicative();
        continue;
      }
      return left;
    }
  }

  private parseMultiplicative(): number {
    let left = this.parseUnary();
    while (true) {
      if (this.matchOperator("*")) {
        left *= this.parseUnary();
        continue;
      }
      if (this.matchOperator("/")) {
        left /= this.parseUnary();
        continue;
      }
      if (this.matchOperator("%")) {
        left %= this.parseUnary();
        continue;
      }
      return left;
    }
  }

  private parseUnary(): number {
    if (this.matchOperator("!")) return toBoolean(this.parseUnary()) ? 0 : 1;
    if (this.matchOperator("-")) return -this.parseUnary();
    return this.parsePrimary();
  }

  private parsePrimary(): number {
    const token = this.current();
    if (this.match("number")) return Number(token.value);
    if (this.match("identifier")) {
      if (token.value !== "n") throw new Error(`Unsupported plural identifier: ${token.value}`);
      return this.count;
    }
    if (this.match("leftParen")) {
      const value = this.parseConditional();
      this.expect("rightParen");
      return toNumber(value);
    }
    throw new Error(`Unexpected plural token: ${token.value}`);
  }

  private match(type: TokenType): boolean {
    if (this.current().type !== type) return false;
    this.index += 1;
    return true;
  }

  private matchOperator(operator: string): boolean {
    const token = this.current();
    if (token.type !== "operator" || token.value !== operator) return false;
    this.index += 1;
    return true;
  }

  private expect(type: TokenType): void {
    if (this.match(type)) return;
    throw new Error(`Expected ${type}, got ${this.current().type}`);
  }

  private current(): Token {
    return this.tokens[this.index] ?? { type: "eof", value: "" };
  }
}

function toBoolean(value: PluralValue): boolean {
  return typeof value === "boolean" ? value : value !== 0;
}

function toNumber(value: PluralValue): number {
  return typeof value === "boolean" ? (value ? 1 : 0) : value;
}
