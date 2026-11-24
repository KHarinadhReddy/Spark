import { api } from "./api";

let activeSpeech = null;

export function browserSpeechSupported() {
  return Boolean(
    typeof window !== "undefined" &&
      (window.SpeechRecognition || window.webkitSpeechRecognition),
  );
}

export function stopSpeech() {
  const active = activeSpeech;
  activeSpeech = null;
  if (!active) return;
  try {
    if (active.type === "audio") {
      active.audio.pause();
      active.audio.removeAttribute("src");
    } else if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
  } catch {
    // nothing else to do — the promise is settled below
  }
  active.finish();
}

function playAudio(blob) {
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  return new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      if (activeSpeech && activeSpeech.audio === audio) activeSpeech = null;
      URL.revokeObjectURL(url);
      resolve();
    };
    audio.onended = finish;
    audio.onerror = finish;
    activeSpeech = { type: "audio", audio, finish };
    audio.play().catch(finish);
  });
}

function speakInBrowser(text, language) {
  if (!("speechSynthesis" in window)) {
    throw new Error("speech synthesis unavailable");
  }
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = language === "hi" ? "hi-IN" : "en-IN";
  utterance.rate = 1;
  utterance.pitch = 1;
  return new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      if (activeSpeech && activeSpeech.utterance === utterance) activeSpeech = null;
      resolve();
    };
    utterance.onend = finish;
    utterance.onerror = finish;
    activeSpeech = { type: "browser", utterance, finish };
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  });
}

export async function speakText({ text, language, useElevenLabs }) {
  stopSpeech();
  if (useElevenLabs) {
    try {
      const blob = await api.tts(text, language);
      await playAudio(blob);
      return;
    } catch {
      // fall through to the browser voice
    }
  }
  await speakInBrowser(text, language);
}

function transcribeWithElevenLabs({ language, onText, onState, onError }) {
  const chunks = [];
  let recorder = null;
  let stream = null;

  navigator.mediaDevices
    .getUserMedia({ audio: true })
    .then((mediaStream) => {
      stream = mediaStream;
      const preferred = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"];
      const mimeType = preferred.find((type) => MediaRecorder.isTypeSupported(type)) || "";
      recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size) chunks.push(event.data);
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        onState("transcribing");
        try {
          const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
          const result = await api.stt(blob);
          if (result.text) onText(result.text);
        } catch (error) {
          onError(error);
        } finally {
          onState("idle");
        }
      };
      recorder.start();
      onState("listening");
    })
    .catch(onError);

  return {
    stop() {
      if (recorder && recorder.state !== "inactive") {
        recorder.stop();
      } else {
        if (stream) stream.getTracks().forEach((track) => track.stop());
        onState("idle");
      }
    },
  };
}

function transcribeWithBrowser({ language, onText, onState, onError }) {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    onError(new Error("Speech recognition unavailable"));
    onState("idle");
    return { stop() {} };
  }
  const recognition = new Recognition();
  recognition.lang = language === "hi" ? "hi-IN" : "en-IN";
  recognition.interimResults = false;
  recognition.continuous = false;
  recognition.maxAlternatives = 1;
  recognition.onresult = (event) => {
    const transcript = event.results?.[0]?.[0]?.transcript;
    if (transcript) onText(transcript);
  };
  recognition.onerror = (event) => {
    if (event.error !== "no-speech" && event.error !== "aborted") {
      onError(new Error(event.error));
    }
  };
  recognition.onend = () => onState("idle");
  recognition.start();
  onState("listening");
  return {
    stop() {
      try {
        recognition.stop();
      } catch {
        onState("idle");
      }
    },
  };
}

export function startMic(options) {
  if (options.mode === "elevenlabs" && navigator.mediaDevices?.getUserMedia) {
    return transcribeWithElevenLabs(options);
  }
  return transcribeWithBrowser(options);
}
