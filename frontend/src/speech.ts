import { API_BASE } from "./api";

let currentAudio: HTMLAudioElement | null = null;
let speakGeneration = 0;
let voicesReady: Promise<SpeechSynthesisVoice[]> | null = null;

const PREFERRED: Record<string, string[]> = {
  "vi-VN": ["hoaimy", "namminh", "hoai my", "an ", "google"],
  "en-US": ["jenny", "aria", "andrew", "emma", "natural", "google", "samantha", "siri"],
};

export function unlockSpeech() {
  if (!("speechSynthesis" in window)) return;
  window.speechSynthesis.getVoices();
  const silent = new Audio(
    "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQAAAAA=",
  );
  silent.play().catch(() => undefined);
}

function haltPlayback() {
  currentAudio?.pause();
  currentAudio = null;
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
}

export async function speak(text: string, lang = "en-US") {
  if (!text.trim()) return;
  const generation = ++speakGeneration;
  haltPlayback();
  const neural = await speakNeural(text, lang, generation);
  if (neural || generation !== speakGeneration) return;
  await speakBrowser(text, lang, generation);
}

export function stopSpeech() {
  speakGeneration += 1;
  haltPlayback();
}

async function speakNeural(text: string, lang: string, generation: number) {
  try {
    const response = await fetch(`${API_BASE}/tts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, language: lang }),
    });
    if (!response.ok || generation !== speakGeneration) return false;
    const blob = await response.blob();
    if (!blob.size || generation !== speakGeneration) return false;
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    currentAudio = audio;
    await audio.play();
    audio.addEventListener("ended", () => URL.revokeObjectURL(url), { once: true });
    return true;
  } catch {
    return false;
  }
}

async function speakBrowser(text: string, lang: string, generation: number) {
  if (!("speechSynthesis" in window)) return;
  const voices = await loadVoices();
  if (generation !== speakGeneration) return;
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = lang;
  utterance.rate = 0.88;
  utterance.pitch = 0.95;
  const voice = pickVoice(voices, lang);
  if (voice) utterance.voice = voice;
  await new Promise((resolve) => window.setTimeout(resolve, 40));
  if (generation !== speakGeneration) return;
  window.speechSynthesis.speak(utterance);
}

function loadVoices(): Promise<SpeechSynthesisVoice[]> {
  if (voicesReady) return voicesReady;
  voicesReady = new Promise((resolve) => {
    const existing = window.speechSynthesis.getVoices();
    if (existing.length) {
      resolve(existing);
      return;
    }
    const finish = () => resolve(window.speechSynthesis.getVoices());
    window.speechSynthesis.addEventListener("voiceschanged", finish, { once: true });
    window.setTimeout(finish, 400);
  });
  return voicesReady;
}

export function pickVoice(voices: SpeechSynthesisVoice[], lang: string) {
  const prefix = lang.slice(0, 2).toLowerCase();
  const preferred = PREFERRED[lang] ?? PREFERRED["en-US"];
  const scored = voices
    .filter((voice) => voice.lang.toLowerCase().startsWith(prefix))
    .map((voice) => {
      const name = voice.name.toLowerCase();
      let score = 0;
      if (voice.lang.toLowerCase() === lang.toLowerCase()) score += 4;
      if (/natural|neural|online|premium|enhanced/.test(name)) score += 12;
      if (!voice.localService) score += 6;
      if (preferred.some((token) => name.includes(token))) score += 8;
      if (/zira|david|mark|hazel|desktop|espeak|sapi/.test(name)) score -= 10;
      return { voice, score };
    })
    .sort((left, right) => right.score - left.score);
  return scored[0]?.voice ?? null;
}
