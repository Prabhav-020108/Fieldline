"use client";

import "@livekit/components-styles";
import { useParams, useRouter } from "next/navigation";
import { useState, useSyncExternalStore } from "react";
import { Track } from "livekit-client";
import {
  BarVisualizer,
  DisconnectButton,
  LiveKitRoom,
  RoomAudioRenderer,
  TrackToggle,
  useVoiceAssistant,
} from "@livekit/components-react";
import { Lock, PhoneOff, Radio } from "lucide-react";

import { getCallRoleToken, isLoggedIn } from "@/lib/api";
import { Badge, Button, Spinner } from "@/components/ui";

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
  const router = useRouter();
  const roomName = `fieldline-${companyId}`;
  const [details, setDetails] = useState<ConnectionDetails | null>(null);
  const [activeRole, setActiveRole] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const authChecked = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false
  );
  const loggedIn = authChecked && isLoggedIn();

  const startCall = async () => {
    if (!isLoggedIn()) {
      setError("Authentication required: Please sign in before connecting to the voice agent.");
      return;
    }
    setConnecting(true);
    setError(null);
    try {
      let roleToken: string | null = null;
      let role: string | null = null;

      try {
        const result = await getCallRoleToken(companyId);
        roleToken = result.token;
        role = result.role;
      } catch (err: unknown) {
        throw new Error(
          err instanceof Error
            ? err.message
            : "Could not obtain an authorized call role token for this company. Please ensure you are signed in with an authorized account."
        );
      }

      const identity = `${role}-${Math.random().toString(36).slice(2, 8)}`;
      const params = new URLSearchParams({ room: roomName, identity, roleToken });

      const res = await fetch(`/api/livekit-token?${params.toString()}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not get a call token.");
      setDetails(data as ConnectionDetails);
      setActiveRole(role);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the call.");
    } finally {
      setConnecting(false);
    }
  };

  const endCall = () => {
    setDetails(null);
    setActiveRole(null);
  };

  return (
    <div>
      <div className="mb-5">
        <h2 className="text-base font-semibold text-[var(--ink)]">Talk to the agent</h2>
        <p className="text-sm text-[var(--ink-muted)] mt-0.5">
          Connects to room <code className="font-mono text-xs">{roomName}</code> -- the agent
          answers using only this company&apos;s data.
        </p>
      </div>

      {!authChecked ? (
        <div className="flex items-center justify-center py-20">
          <Spinner size={20} />
        </div>
      ) : !loggedIn ? (
        <div className="flex flex-col items-center justify-center gap-4 py-16 px-6 bg-[var(--surface)] border border-[var(--line)] rounded-[var(--radius-lg)] text-center max-w-lg mx-auto">
          <div className="w-12 h-12 rounded-full bg-[var(--surface-sunken)] flex items-center justify-center text-[var(--ink-muted)]">
            <Lock size={22} />
          </div>
          <div>
            <h3 className="text-base font-semibold text-[var(--ink)]">Sign in required</h3>
            <p className="text-sm text-[var(--ink-muted)] mt-1.5">
              Only authenticated team members (dispatcher, supervisor, or technician) can connect to the voice agent. Please sign in to continue.
            </p>
          </div>
          <Button onClick={() => router.push("/login")}>
            Sign in
          </Button>
        </div>
      ) : !details ? (
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
          <CallPanel onEndCall={endCall} role={activeRole} />
          <RoomAudioRenderer />
        </LiveKitRoom>
      )}
    </div>
  );
}

function CallPanel({ onEndCall, role }: { onEndCall: () => void; role: string | null }) {
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
        {role ? (
          <Badge tone={role === "technician" ? "neutral" : "brand"}>Connected as {role}</Badge>
        ) : null}
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