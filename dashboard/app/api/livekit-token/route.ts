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
  const roleToken = req.nextUrl.searchParams.get("roleToken");

  if (!room) {
    return NextResponse.json({ error: "Missing 'room' query parameter" }, { status: 400 });
  }

  if (!roleToken) {
    return NextResponse.json(
      { error: "Authentication required: A verified role token is required to connect to the voice dispatch agent." },
      { status: 401 }
    );
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