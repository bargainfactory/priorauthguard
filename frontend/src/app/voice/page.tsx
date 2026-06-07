"use client";

import { useEffect, useRef, useState } from "react";
import { Cpu, Mic, MicOff, ShieldCheck, Square } from "lucide-react";
import { toast } from "sonner";
import { Shell } from "@/components/layout/shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { transcribeDictation } from "@/lib/api";
import { startBrowserRecording, type RecordingHandle } from "@/lib/audio";
import { getPlatform, isNative } from "@/lib/platform";
import { transcribeOnDevice } from "@/lib/whisper";
import { formatMs } from "@/lib/utils";
import type { DictationResponse } from "@/types/api";

type RuntimePlatform = "web" | "tauri" | "capacitor";

export default function VoicePage() {
  const [platform, setPlatform] = useState<RuntimePlatform>("web");
  const [recordingHandle, setRecordingHandle] = useState<RecordingHandle | null>(null);
  const [recording, setRecording] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [whisperLatencyMs, setWhisperLatencyMs] = useState<number | null>(null);
  const [redacted, setRedacted] = useState<DictationResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const startedAtRef = useRef<number | null>(null);

  useEffect(() => {
    setPlatform(getPlatform());
  }, []);

  async function startRecording() {
    try {
      if (platform === "capacitor") {
        // Capacitor's native plugin handles capture entirely on-device; the
        // page just dispatches to it and surfaces the resulting text.
        const { OnDeviceWhisper } = await import(
          /* @vite-ignore */ "@pa-guard/on-device-whisper"
        );
        const perm = await OnDeviceWhisper.requestMicrophonePermission();
        if (!perm.granted) {
          toast.error("Microphone permission denied");
          return;
        }
        await OnDeviceWhisper.startRecording({ sampleRate: 16_000 });
        setRecording(true);
        startedAtRef.current = performance.now();
        return;
      }

      // Browser + Tauri share the same Web Audio capture path; the difference
      // is only where the transcript is computed (backend vs. native).
      const h = await startBrowserRecording();
      setRecordingHandle(h);
      setRecording(true);
      startedAtRef.current = performance.now();
    } catch (e) {
      toast.error("Failed to start recording", { description: String(e) });
    }
  }

  async function stopRecording() {
    if (!recording) return;
    setBusy(true);
    try {
      if (platform === "capacitor") {
        const { OnDeviceWhisper } = await import(
          /* @vite-ignore */ "@pa-guard/on-device-whisper"
        );
        const stop = await OnDeviceWhisper.stopRecording();
        const out = await OnDeviceWhisper.transcribe({
          wavPath: stop.wavPath,
          language: "en",
          deleteAudioAfter: true,
        });
        setRecording(false);
        setTranscript(out.text);
        setWhisperLatencyMs(out.durationMs);
        await deidentify(out.text);
        return;
      }

      const handle = recordingHandle;
      if (!handle) return;
      const wav = await handle.stop();
      setRecording(false);
      setRecordingHandle(null);

      if (platform === "tauri") {
        const out = await transcribeOnDevice(wav, "en");
        setTranscript(out.text);
        setWhisperLatencyMs(out.durationMs);
        await deidentify(out.text);
      } else {
        toast.message(
          "Web recording captured locally. Paste the dictation text into the input below — " +
            "raw audio is NOT uploaded.",
        );
      }
    } catch (e) {
      toast.error("Recording stop failed", { description: String(e) });
      setRecording(false);
    } finally {
      setBusy(false);
    }
  }

  async function deidentify(text: string) {
    setBusy(true);
    try {
      const r = await transcribeDictation({ text });
      setRedacted(r);
    } catch (e) {
      toast.error("De-identification failed", { description: String(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell
      title="Voice Dictation"
      subtitle="Native on-device Whisper on desktop / mobile, Safe Harbor de-identification on every transcript."
    >
      <Card className="surface-blur">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Cpu className="size-4" />
            Capture surface
          </CardTitle>
          <CardDescription>
            {platform === "tauri"
              ? "Tauri desktop — Rust + whisper.cpp running on this machine."
              : platform === "capacitor"
              ? "Capacitor mobile — native AVAudioEngine / AudioRecord + on-device Whisper."
              : "Web browser — audio stays in this tab; paste the transcript below for de-identification."}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          <Badge variant={isNative() ? "success" : "info"}>{platform}</Badge>
          {whisperLatencyMs !== null ? (
            <Badge variant="outline">whisper {formatMs(whisperLatencyMs)}</Badge>
          ) : null}
          <Button
            onClick={recording ? stopRecording : startRecording}
            disabled={busy && !recording}
            variant={recording ? "destructive" : "default"}
            size="lg"
          >
            {recording ? (
              <>
                <Square className="size-4" /> Stop
              </>
            ) : (
              <>
                <Mic className="size-4" /> Record
              </>
            )}
          </Button>
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <MicOff className="size-4" /> Native transcript
            </CardTitle>
            <CardDescription>
              {isNative()
                ? "On-device Whisper output. PHI gets stripped in the next step."
                : "Paste dictation here — raw audio never leaves this browser."}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Textarea
              rows={10}
              value={transcript}
              onChange={(e) => setTranscript(e.target.value)}
              placeholder={
                isNative()
                  ? "Press Record above to start dictation…"
                  : "Mr. John Smith MRN: AB12345678 follow-up visit…"
              }
            />
            <Button
              onClick={() => deidentify(transcript)}
              disabled={busy || !transcript.trim()}
            >
              {busy ? "De-identifying…" : "De-identify"}
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="size-4 text-trust-600 dark:text-trust-300" />
              De-identified transcript
            </CardTitle>
            <CardDescription>
              Safe for downstream agents and persistence.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {redacted ? (
              <>
                <div className="mb-3 flex items-center gap-2">
                  <Badge variant="success">
                    {redacted.identifiers_redacted} identifiers redacted
                  </Badge>
                </div>
                <Separator className="mb-3" />
                <p className="whitespace-pre-wrap text-sm leading-relaxed">
                  {redacted.cleaned_text}
                </p>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                Submit a transcript to see the redacted version here.
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </Shell>
  );
}
