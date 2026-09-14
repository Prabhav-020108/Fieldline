"use client";

import "@livekit/components-styles";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Track } from "livekit-client";
import {
  BarVisualizer,
  DisconnectButton,
  LiveKitRoom,
  RoomAudioRenderer,
  TrackToggle,
  useVoiceAssistant,
} from "@livekit/components-react";
import { PhoneOff, Radio } from "lucide-react";

import { Button, Spinner } from "@/components/ui";

interface ConnectionDetails {
  token: string;
  url: string;
  room: string;
  identity: string;
}

export default function CallPage() {
  const params = useParams<{ companyId: string }>();
  return <CallPageInner key={params.companyId} companyId={params.companyId} />;
}

function CallPageInner({ companyId }: { companyId: string }) {
  const roomName = `fieldline-${companyId}`;
  const [details, setDetails] = useState<ConnectionDetails | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const startCall = async () => {
    setConnecting(true);
    setError(null);
    try {
      const identity = `dispatcher-${Math.random().toString(36).slice(2, 8)}`;
      const res = await fetch(
        `/api/livekit-token?room=${encodeURIComponent(roomName)}&identity=${identity}`
      );
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not get a call token.");
      setDetails(data as ConnectionDetails);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the call.");
    } finally {
      setConnecting(false);
    }
  };

  const endCall = () => setDetails(null);

  return (
    <div>
      <div className="mb-5">
        <h2 className="text-base font-semibold text-[var(--ink)]">Talk to the agent</h2>
        <p className="text-sm text-[var(--ink-muted)] mt-0.5">
          Connects to room <code className="font-mono text-xs">{roomName}</code> -- the agent
          answers using only this company&apos;s data.
        </p>
      </div>

      {!details ? (
        <div className="flex flex-col items-center justify-center gap-4 py-20 bg-[var(--surface)] border border-[var(--line)] rounded-[var(--radius-lg)]">
          <Button onClick={startCall} disabled={connecting}>
            {connecting ? <Spinner size={14} /> : <Radio size={16} />}
            {connecting ? "Connecting" : "Start voice call"}
          </Button>
          {error ? (
            <p className="text-sm text-[var(--danger)] max-w-sm text-center">{error}</p>
          ) : null}
          <p className="text-xs text-[var(--ink-faint)] max-w-sm text-center">
            Needs the agent running (<code className="font-mono">uv run python src/agent.py dev</code>)
            and LiveKit credentials in <code className="font-mono">dashboard/.env.local</code>.
          </p>
        </div>
      ) : (
        <LiveKitRoom
          token={details.token}
          serverUrl={details.url}
          connect
          audio
          onDisconnected={endCall}
          className="bg-[var(--surface)] border border-[var(--line)] rounded-[var(--radius-lg)] p-8"
        >
          <CallPanel onEndCall={endCall} />
          <RoomAudioRenderer />
        </LiveKitRoom>
      )}
    </div>
  );
}

function CallPanel({ onEndCall }: { onEndCall: () => void }) {
  const { state, audioTrack, agentTranscriptions } = useVoiceAssistant();

  const stateLabel: Record<string, string> = {
    connecting: "Connecting to agent...",
    initializing: "Connecting to agent...",
    listening: "Listening",
    thinking: "Thinking",
    speaking: "Speaking",
    disconnected: "Disconnected",
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] gap-8">
      <div className="flex flex-col items-center justify-center gap-5">
        <BarVisualizer state={state} trackRef={audioTrack} barCount={7} style={{ height: 64, width: 200 }} />
        <p className="text-sm font-medium text-[var(--ink-muted)]">
          {stateLabel[state ?? ""] ?? "Connecting to agent..."}
        </p>
        <div className="flex items-center gap-3">
          <TrackToggle
            source={Track.Source.Microphone}
            className="inline-flex items-center justify-center h-11 w-11 rounded-full border border-[var(--line-strong)] bg-white hover:bg-[var(--surface-sunken)] text-[var(--ink)] cursor-pointer"
          />
          <DisconnectButton
            onClick={onEndCall}
            className="inline-flex items-center justify-center h-11 w-11 rounded-full bg-[var(--danger)] text-white hover:opacity-90 cursor-pointer"
          >
            <PhoneOff size={17} />
          </DisconnectButton>
        </div>
      </div>

      <div className="border-l border-[var(--line)] pl-8 max-h-80 overflow-y-auto space-y-2.5">
        <p className="text-xs font-medium text-[var(--ink-faint)] mb-3">Agent transcript</p>
        {agentTranscriptions.length === 0 ? (
          <p className="text-sm text-[var(--ink-faint)]">
            What the agent says will appear here once the call connects.
          </p>
        ) : (
          agentTranscriptions.map((t) => (
            <div
              key={t.id}
              className="max-w-[90%] rounded-[var(--radius-md)] bg-[var(--brand-tint)] text-[var(--brand-strong)] px-3.5 py-2 text-sm leading-relaxed"
            >
              {t.text}
            </div>
          ))
        )}
      </div>
    </div>
  );
}