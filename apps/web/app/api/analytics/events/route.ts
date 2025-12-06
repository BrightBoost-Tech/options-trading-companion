import { NextRequest, NextResponse } from "next/server";

const API_BASE_URL = process.env.API_URL || "http://127.0.0.1:8000";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    // Prepare headers for the backend request
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };

    // Forward Authorization header if present
    const authHeader = request.headers.get("authorization");
    if (authHeader) {
      headers["Authorization"] = authHeader;
    }

    // Forward cookies if present
    const cookieHeader = request.headers.get("cookie");
    if (cookieHeader) {
      headers["Cookie"] = cookieHeader;
    }

    // Forward "X-Test-Mode-User" header if present (for dev/test modes)
    const testUserHeader = request.headers.get("x-test-mode-user");
    if (testUserHeader) {
      headers["X-Test-Mode-User"] = testUserHeader;
    }

    const response = await fetch(`${API_BASE_URL}/analytics/events`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });

    if (response.status === 401) {
      // Log unauthorized access server-side but don't break the client UI
      console.error("Analytics backend unauthorized:", await response.text());
      return new NextResponse(null, { status: 200 });
    }

    if (!response.ok) {
        // Just log server side, don't fail the request to the client
        console.error(`Analytics backend failed: ${response.status} ${await response.text()}`);
        return NextResponse.json({ status: "logged_with_error" });
    }

    const data = await response.json();
    return NextResponse.json(data);

  } catch (error) {
    console.error("Error in analytics proxy:", error);
    // Return success to client so we don't break their flow
    return NextResponse.json({ status: "error_swallowed" });
  }
}
