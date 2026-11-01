// Pure helpers for the voice experience. No DOM / browser APIs in this file so it can be
// unit-tested with `node --test` (Node 22.6+ strips the TypeScript types natively).

/* ------------------------------------------------------------------ */
/* Text normalisation                                                  */
/* ------------------------------------------------------------------ */

/** Lower-case words with punctuation removed (keeps hyphens inside words, e.g. "mm-hmm"). */
export function words(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[’']/g, "")
    .replace(/[^\p{L}\p{N}\s-]/gu, " ")
    .split(/\s+/)
    .map((w) => w.replace(/^-+|-+$/g, ""))
    .filter(Boolean);
}

/** Remove the light markdown the assistant uses so it is not read aloud. */
export function stripMarkdown(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/(\*\*|__)(.+?)\1/g, "$2")
    .replace(/(^|[^\w*])\*(?!\s)([^*\n]+?)\*(?!\w)/g, "$1$2")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s*(?:[-*•]|\d+[.)])\s+/gm, "")
    .replace(/^\s*>\s?/gm, "")
    .replace(/\*\*|__/g, "");
}

/** Make text friendlier for speech synthesis: markdown removed, ₹ amounts read as rupees. */
export function toSpeakable(text: string): string {
  return stripMarkdown(text)
    .replace(/₹\s?([\d,]+(?:\.\d+)?)(\s?(?:lakh|crore|k)\b)?/gi, (_m, n: string, unit?: string) =>
      `${n}${unit ?? ""} rupees`,
    )
    .replace(/\bEMI\b/g, "E.M.I.")
    .replace(/[ \t]+/g, " ")
    .trim();
}

/* ------------------------------------------------------------------ */
/* Sentence splitting for incremental TTS                              */
/* ------------------------------------------------------------------ */

const ABBREVIATIONS = new Set([
  "rs", "no", "mr", "mrs", "ms", "dr", "st", "vs", "eg", "e.g", "ie", "i.e", "approx", "etc", "p.a", "pa", "a/c", "ac",
]);

/**
 * Split a streaming text buffer into complete sentences plus an unfinished remainder.
 * A boundary is `.`, `?`, `!` or `…` followed by whitespace, or a newline (list items).
 * Boundaries at the very end of the buffer are NOT taken (more text may follow, e.g. "8." → "8.5%"),
 * unless `final` is set. Abbreviations like "Rs." and decimals like "8.5" never split.
 */
export function splitSentences(buffer: string, final = false): { sentences: string[]; rest: string } {
  const sentences: string[] = [];
  let start = 0;
  const re = /([.?!…]+)(["')\]]*)(\s+)|\n+/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(buffer))) {
    const end = m.index + m[0].length;
    if (m[1] === ".") {
      const before = buffer.slice(start, m.index);
      const lastWord = before.split(/\s+/).pop()?.toLowerCase().replace(/^[(\["']+/, "") ?? "";
      if (ABBREVIATIONS.has(lastWord)) continue;
      // Single capital initial ("A. Kumar") — not a sentence end.
      if (/^[A-Z]$/.test(before.split(/\s+/).pop() ?? "")) continue;
    }
    const s = buffer.slice(start, m.index + (m[1]?.length ?? 0) + (m[2]?.length ?? 0)).trim();
    if (s) sentences.push(s);
    start = end;
  }
  let rest = buffer.slice(start);
  if (final) {
    const r = rest.trim();
    if (r) sentences.push(r);
    rest = "";
  }
  return { sentences, rest };
}

/** Streaming wrapper around splitSentences. */
export class SentenceBuffer {
  private buf = "";
  push(delta: string): string[] {
    this.buf += delta;
    const { sentences, rest } = splitSentences(this.buf);
    this.buf = rest;
    return sentences;
  }
  flush(): string[] {
    const { sentences } = splitSentences(this.buf, true);
    this.buf = "";
    return sentences;
  }
  reset() {
    this.buf = "";
  }
}

/* ------------------------------------------------------------------ */
/* Barge-in: backchannels and echo                                     */
/* ------------------------------------------------------------------ */

export const BACKCHANNELS = new Set([
  "okay", "ok", "mm-hmm", "mmhmm", "mhm", "mm", "hmm", "hm", "right", "yes", "yeah", "yep", "haan", "han",
  "uh-huh", "uhhuh", "uh", "huh", "ah", "oh", "achha", "acha", "accha", "sure", "alright", "fine", "ji",
]);

export function isBackchannel(text: string): boolean {
  const w = words(text);
  return w.length > 0 && w.every((x) => BACKCHANNELS.has(x));
}

/** Words that carry no intent on their own; they never count as evidence of a real interruption. */
export const FUNCTION_WORDS = new Set([
  "a", "an", "the", "is", "are", "was", "be", "it", "its", "i", "im", "me", "my", "you", "your", "we", "to", "of",
  "and", "or", "for", "on", "in", "at", "this", "that", "so", "just", "can", "do", "with", "from", "by", "as", "if",
  "what", "will", "would", "now", "then", "there", "here", "about", "up", "out", "all", "per",
]);

/** Comma-free digits so "17,416" (spoken text) and "17416" (recognised speech) compare equal. */
function speechWords(text: string): string[] {
  return words(text.replace(/(\d),(?=\d)/g, "$1"));
}

/** Every word the assistant has recently said, in both its written and its spoken form. */
function corpusWords(spoken: Array<string | null | undefined>): Set<string> {
  const all = new Set<string>();
  for (const s of spoken) {
    if (!s) continue;
    for (const w of speechWords(s)) all.add(w);
    for (const w of speechWords(toSpeakable(s))) all.add(w);
  }
  return all;
}

/** Fraction of `heard` words that also appear in `spoken` (0..1). */
export function echoRatio(heard: string, spoken: string | Array<string | null | undefined>): number {
  const h = speechWords(heard);
  if (h.length === 0) return 0;
  const s = corpusWords(Array.isArray(spoken) ? spoken : [spoken]);
  if (s.size === 0) return 0;
  return h.filter((x) => s.has(x)).length / h.length;
}

/** Content words in `heard` that the assistant did not just say: the evidence that a person is talking. */
export function novelWords(heard: string, spoken: Array<string | null | undefined>): string[] {
  const known = corpusWords(spoken);
  return speechWords(heard).filter((w) => !known.has(w) && !FUNCTION_WORDS.has(w) && !BACKCHANNELS.has(w));
}

/**
 * Drop leading words that the assistant just said, keeping what the person said after them. A recogniser result
 * that spans a barge-in starts with echo ("…bear with me your EMI is") and ends with the person ("wait, check my
 * card"); only the tail is theirs. Returns "" when nothing new remains.
 */
export function stripEchoPrefix(heard: string, spoken: Array<string | null | undefined>): string {
  const known = corpusWords(spoken);
  const raw = heard.trim().split(/\s+/);
  let i = 0;
  while (i < raw.length) {
    const w = speechWords(raw[i]);
    if (w.length && !w.every((x) => known.has(x))) break; // a word the assistant did not say: the person starts here
    i++;
  }
  return raw.slice(i).join(" ");
}

/**
 * Is `heard` the speakers' own output coming back through the mic? Compared against everything the assistant
 * said recently as one body of text: a recogniser transcript often spans two utterances (a filler and the
 * answer), so matching one sentence at a time misses it.
 */
export function isEcho(heard: string, spoken: Array<string | null | undefined>, threshold = 0.6): boolean {
  const w = speechWords(heard);
  if (w.length === 0 || !spoken.some(Boolean)) return false;
  if (echoRatio(heard, spoken) >= threshold) return true;
  return w.length >= 3 && novelWords(heard, spoken).length === 0;
}

/**
 * Should speech heard while the assistant is thinking/speaking stop it? Needs content words the assistant did
 * not just say, so its own voice leaking into the mic never interrupts it.
 */
export function shouldBargeIn(interim: string, spoken: Array<string | null | undefined>): boolean {
  const w = speechWords(interim);
  if (w.length < 2) return false;
  if (w.every((x) => BACKCHANNELS.has(x))) return false;
  if (isEcho(interim, spoken)) return false;
  const novel = novelWords(interim, spoken).length;
  // two new content words, or one in a mostly-new phrase ("what about my card")
  return novel >= 2 || (novel === 1 && w.length >= 3 && echoRatio(interim, spoken) < 0.5);
}

/* ------------------------------------------------------------------ */
/* Voice confirmations                                                 */
/* ------------------------------------------------------------------ */

const NEGATIVE = /\b(no|nope|nah|don'?t|do not|not|cancel|stop|wait|hold on|never ?mind|nahi|mat)\b/i;
const AFFIRMATIVE =
  /\b(yes|yeah|yep|yup|yess|sure|go ahead|confirm(ed)?|do it|please do|proceed|haan|ha|ji haan|absolutely|correct|that'?s right|ok(ay)?)\b/i;

export function isAffirmative(text: string): boolean {
  const t = text.toLowerCase().replace(/[’]/g, "'");
  if (NEGATIVE.test(t)) return false;
  return AFFIRMATIVE.test(t);
}

const DIGIT_WORDS: Record<string, string> = {
  zero: "0", oh: "0", o: "0", nil: "0",
  one: "1", won: "1",
  two: "2", too: "2",
  three: "3", tree: "3",
  four: "4",
  five: "5",
  six: "6", sex: "6",
  seven: "7",
  eight: "8", ate: "8",
  nine: "9", nein: "9",
};
const MULTIPLIERS: Record<string, number> = { double: 2, triple: 3 };

/**
 * Extract a 6-digit OTP from a spoken transcript.
 * Handles "123456", "123 456", "one two three four five six", mixtures, and
 * Indian-English "double five" / "triple one". Returns null unless exactly 6 digits are found.
 */
export function parseOtp(text: string, length = 6): string | null {
  const tokens = text
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .split(/\s+/)
    .filter(Boolean);
  let digits = "";
  let mult = 1;
  for (const tok of tokens) {
    if (tok in MULTIPLIERS) {
      mult = MULTIPLIERS[tok];
      continue;
    }
    let d = "";
    if (/^\d+$/.test(tok)) d = tok;
    else if (tok in DIGIT_WORDS) d = DIGIT_WORDS[tok];
    if (d) {
      // "double 5" → 55; "double 56" → 556 (only the first digit repeats)
      digits += d[0].repeat(mult) + d.slice(1);
    }
    mult = 1;
  }
  return digits.length === length ? digits : null;
}

/* ------------------------------------------------------------------ */
/* Fillers                                                             */
/* ------------------------------------------------------------------ */

export const LONG_WAIT_FILLER = "This is taking a little longer, bear with me.";

/** "Checking your recent payments…" → "One moment, checking your recent payments." */
export function fillerFromStatus(status?: string | null): string {
  const s = (status ?? "").replace(/(\.\.\.|…|\.)+\s*$/u, "").trim();
  if (!s) return "One moment.";
  const lowered = /^[A-Z][a-z]/.test(s) ? s[0].toLowerCase() + s.slice(1) : s;
  return `One moment, ${lowered}.`;
}

/* ------------------------------------------------------------------ */
/* Closing the conversation                                            */
/* ------------------------------------------------------------------ */

const CLOSING =
  /\b(that'?s (all|it|everything)|i'?m done|i am done|we'?re done|nothing else|no,? thanks?|no thank you|that will be all|bye|goodbye|good bye|end (the )?call|hang up)\b/i;
const THANKS = /^\s*(ok(ay)?,?\s*)?(thanks?|thank you|thank you so much|thanks a lot|great,? thanks?)[.!]?\s*$/i;

/** The customer is wrapping up: say goodbye and end the call. */
export function isClosing(text: string): boolean {
  return CLOSING.test(text);
}

/** Just a thank-you: acknowledge it without a round trip to the assistant. */
export function isThanks(text: string): boolean {
  return THANKS.test(text);
}

export const GOODBYE = "Thanks for calling Northstar. Have a good day.";
export const YOU_ARE_WELCOME = "You're welcome. Is there anything else I can help with?";
