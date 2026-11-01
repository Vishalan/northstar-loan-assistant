import { test } from "node:test";
import assert from "node:assert/strict";
import {
  SentenceBuffer,
  echoRatio,
  fillerFromStatus,
  isAffirmative,
  isBackchannel,
  isClosing,
  isThanks,
  isEcho,
  novelWords,
  parseOtp,
  shouldBargeIn,
  stripEchoPrefix,
  splitSentences,
  stripMarkdown,
  toSpeakable,
  LONG_WAIT_FILLER,
} from "../lib/voice-utils.ts";
import { createSSEParser, type SSEFrame } from "../lib/sse-parser.ts";

test("splitSentences keeps the unfinished tail", () => {
  const r = splitSentences("Your EMI is ₹17,486. It changed because the rate went up");
  assert.deepEqual(r.sentences, ["Your EMI is ₹17,486."]);
  assert.equal(r.rest, "It changed because the rate went up");
});

test("splitSentences does not split decimals, abbreviations or end-of-buffer", () => {
  assert.deepEqual(splitSentences("Rate is 8.5% p.a. now").sentences, []);
  assert.deepEqual(splitSentences("Pay Rs. 500 today. Thanks").sentences, ["Pay Rs. 500 today."]);
  // period at end of buffer may be a decimal point still streaming in
  assert.deepEqual(splitSentences("The rate is 8.").sentences, []);
  assert.deepEqual(splitSentences("Done? Yes! Great.", true).sentences, ["Done?", "Yes!", "Great."]);
});

test("splitSentences splits list items on newlines", () => {
  const r = splitSentences("Two options:\n- Reduce tenure\n- Reduce EMI\n");
  assert.deepEqual(r.sentences, ["Two options:", "- Reduce tenure", "- Reduce EMI"]);
});

test("SentenceBuffer streams across deltas and flushes", () => {
  const b = new SentenceBuffer();
  assert.deepEqual(b.push("Hello the"), []);
  assert.deepEqual(b.push("re. How are"), ["Hello there."]);
  assert.deepEqual(b.push(" you? I'm"), ["How are you?"]);
  assert.deepEqual(b.flush(), ["I'm"]);
  assert.deepEqual(b.flush(), []);
});

test("stripMarkdown / toSpeakable", () => {
  assert.equal(stripMarkdown("**Bold** and *it*\n- item"), "Bold and it\nitem");
  assert.equal(toSpeakable("Your **EMI** is ₹17,486."), "Your E.M.I. is 17,486 rupees.");
});

test("backchannels", () => {
  assert.equal(isBackchannel("okay"), true);
  assert.equal(isBackchannel("mm-hmm yeah"), true);
  assert.equal(isBackchannel("Haan, right."), true);
  assert.equal(isBackchannel("okay but why"), false);
});

test("shouldBargeIn: needs ≥2 non-backchannel words that are not echo", () => {
  const speaking = "Your EMI went up by ₹291 because the repo rate changed.";
  assert.equal(shouldBargeIn("wait", [speaking]), false, "single word");
  assert.equal(shouldBargeIn("okay yeah", [speaking]), false, "backchannels");
  assert.equal(shouldBargeIn("the repo rate changed", [speaking]), false, "echo of speaker");
  assert.equal(shouldBargeIn("what about my card", [speaking]), true);
  assert.equal(shouldBargeIn("no stop that", [speaking]), true);
  assert.ok(echoRatio("rate changed because", speaking) > 0.6);
});

test("isAffirmative", () => {
  for (const t of ["Yes", "yeah go ahead", "Confirm it", "do it", "haan please", "okay, go ahead"])
    assert.equal(isAffirmative(t), true, t);
  for (const t of ["no", "don't do it", "wait", "what is the charge", "not yet"])
    assert.equal(isAffirmative(t), false, t);
});

test("parseOtp handles digits, words, mixtures and double/triple", () => {
  assert.equal(parseOtp("123456"), "123456");
  assert.equal(parseOtp("my code is 123 456"), "123456");
  assert.equal(parseOtp("one two three four five six"), "123456");
  assert.equal(parseOtp("One, two, 3, four. Five six"), "123456");
  assert.equal(parseOtp("four double five triple oh"), "455000");
  assert.equal(parseOtp("one two three"), null);
  assert.equal(parseOtp("yes go ahead"), null);
});

test("fillerFromStatus", () => {
  assert.equal(fillerFromStatus("Checking your recent payments…"), "One moment, checking your recent payments.");
  assert.equal(fillerFromStatus("Looking up EMI history..."), "One moment, looking up EMI history.");
  assert.equal(fillerFromStatus(""), "One moment.");
  assert.equal(fillerFromStatus(undefined), "One moment.");
  assert.match(LONG_WAIT_FILLER, /bear with me/);
});

test("SSE parser handles split chunks, CRLF, comments and multi-line data", () => {
  const frames: SSEFrame[] = [];
  const p = createSSEParser((f) => frames.push(f));
  p.feed("event: status\r");
  p.feed("\ndata: {\"text\":\"Hi\"}\r\n\r\n: ping\n\n");
  p.feed("event: answer.delta\ndata: {\"te");
  p.feed("xt\":\"a\"}\n\nevent: x\ndata: line1\ndata: line2\n");
  p.end();
  assert.deepEqual(frames, [
    { event: "status", data: '{"text":"Hi"}' },
    { event: "answer.delta", data: '{"text":"a"}' },
    { event: "x", data: "line1\nline2" },
  ]);
});

test("echo spanning a filler and the answer never interrupts the assistant (feedback loop bug)", () => {
  const said = [
    "One moment, looking into it.",
    "This is taking a little longer, bear with me.",
    "Got it, take your time.",
    "Your next EMI of ₹17,416 is due on 5 Nov 2026.",
  ];
  // transcripts Chrome produced from the speakers in the reported loop
  for (const heard of [
    "one moment looking into it got it take your time I",
    "one moment looking into it this is taking a little longer",
    "your next e m i of 17416 rupees is due on 5 nov",
  ]) {
    assert.equal(shouldBargeIn(heard, said), false, heard);
    assert.equal(isEcho(heard, said), true, heard);
  }
});

test("a real interruption still stops the assistant", () => {
  const said = ["One moment, looking into it.", "Your next EMI of ₹17,416 is due on 5 Nov 2026."];
  assert.equal(shouldBargeIn("actually check my last payment first", said), true);
  assert.equal(shouldBargeIn("wait stop", said), true);
  assert.equal(shouldBargeIn("okay right", said), false); // backchannel
  assert.ok(novelWords("actually check my last payment", said).includes("payment"));
  assert.equal(isEcho("actually check my last payment first", said), false);
});

test("a long echo result keeps only what the person said after it", () => {
  const said = ["One moment, looking into it.", "This is taking a little longer, bear with me.",
    "Your EMI increased by ₹221 a month, from ₹17,195 to ₹17,416, starting 1 October 2026."];
  // the transcript from the second report: 20 s of speaker audio glued into one result
  const echo = "moment looking into it this is taking a little longer bear with me your eyes by 200 and 21 rupees a month from 17195 to 17416";
  assert.equal(isEcho(echo, said), true);
  assert.equal(stripEchoPrefix("this is taking a little longer bear with me wait check my card instead", said), "wait check my card instead");
  assert.equal(stripEchoPrefix("one moment looking into it", said), "");
  assert.equal(stripEchoPrefix("what about my card", said), "what about my card");
});

test("closing phrases, thanks and lone acknowledgements", () => {
  for (const t of ["Okay, I'm done.", "That's all", "No thanks", "bye", "Nothing else, thank you", "end the call"])
    assert.equal(isClosing(t), true, t);
  for (const t of ["Okay.", "Can I foreclose my loan?", "What about my card", "Done with the payment?"])
    assert.equal(isClosing(t), false, t);
  assert.equal(isThanks("Thank you."), true);
  assert.equal(isThanks("Okay thanks"), true);
  assert.equal(isThanks("thanks, and what is my EMI"), false);
  assert.equal(isBackchannel("Okay."), true);
  assert.equal(isBackchannel("Mm-hmm."), true);
});
