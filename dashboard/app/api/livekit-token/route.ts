import { NextRequest, NextResponse } from "next/server";
import { AccessToken } from "livekit-server-sdk";
import { RoomAgentDispatch, RoomConfiguration } from "@livekit/protocol";

// Never cache -- every call needs a fresh, single-use token.
export const dynamic = "force-dynamic";

// Must match agent.py's @server.rtc_session(agent_name="fieldline-agent")
// exactly.
const AGENT_NAME = "fieldline-agent";

export async function GET(req: NextRequest) {
  const room = req.nextUrl.searchParams.get("room");
  const identity =
    req.nextUrl.searchParams.get("identity") ??
    `dispatcher-${Math.random().toString(36).slice(2, 8)}`;
  // Phase 8c: an optional short-lived JWT minted by
  // POST /companies/{id}/call-role-token, carried as participant metadata
  // so agent/src/role_cache.py can verify it locally, offline-capable,
  // once the call has started.
  const roleToken = req.nextUrl.searchParams.get("roleToken") ?? undefined;

  if (!room) {
    return NextResponse.json({ error: "Missing 'room' query parameter" }, { status: 400 });
  }

  const apiKey = process.env.LIVEKIT_API_KEY;
  const apiSecret = process.env.LIVEKIT_API_SECRET;
  const wsUrl = process.env.NEXT_PUBLIC_LIVEKIT_URL;

  if (!apiKey || !apiSecret || !wsUrl) {
    return NextResponse.json(
      {
        error:
          "Missing LIVEKIT_API_KEY / LIVEKIT_API_SECRET / NEXT_PUBLIC_LIVEKIT_URL in dashboard/.env.local -- copy them from agent/.env.local.",
      },
      { status: 500 }
    );
  }

  const at = new AccessToken(apiKey, apiSecret, {
    identity,
    name: "Dispatch console",
    metadata: roleToken,
  });
  at.addGrant({ room, roomJoin: true, canPublish: true, canSubscribe: true });
  at.roomConfig = new RoomConfiguration({
    agents: [new RoomAgentDispatch({ agentName: AGENT_NAME })],
  });

  const token = await at.toJwt();

  return NextResponse.json({ token, url: wsUrl, room, identity });
}