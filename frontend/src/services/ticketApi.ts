import { apiFetch } from "../lib/apiClient";

const getHeaders = () => {
  const token = localStorage.getItem("bmtc-token");
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
};

export interface TicketPurchaseRequest {
  source_stop: string;
  destination_stop: string;
  fare_amount: number;
}

export interface TicketResponse {
  ticket_id: string;
  user_id: string;
  source_stop: string;
  destination_stop: string;
  fare_amount: number;
  issue_time: string;
  expiry_time: string;
  status: string;
  qr_token: string;
  short_code: string;
  /** What the journey would have cost. On a Shakti ticket this is the amount
   *  BMTC claims back from the State, which is why a free ticket still has a
   *  price on it. Absent on tickets issued before the scheme flow existed. */
  fare_value_inr?: number | null;
  fare_collected_inr?: number | null;
  is_zero_fare?: boolean;
  scheme?: string | null;
  scheme_note?: string | null;
}

export interface VerifyTicketRequest {
  qr_token: string;
}

export interface VerifyTicketResponse {
  success: boolean;
  message: string;
  ticket_id?: string;
  status?: string;
}

export const ticketApi = {
  getFare: async (source: string, destination: string): Promise<{fare: number}> => {
    const params = new URLSearchParams({ source, destination });
    const res = await apiFetch(`/api/tickets/fare?${params.toString()}`, {
      headers: getHeaders(),
    });
    if (!res.ok) throw new Error("Fare not found");
    return res.json();
  },
  
  purchaseTicket: async (data: TicketPurchaseRequest): Promise<TicketResponse> => {
    const res = await apiFetch(`/api/tickets/purchase`, {
      method: "POST",
      headers: getHeaders(),
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error("Failed to purchase ticket");
    return res.json();
  },
  
  getActiveTicket: async (): Promise<TicketResponse | null> => {
    const res = await apiFetch(`/api/tickets/active`, {
      headers: getHeaders(),
    });
    if (res.status === 404) return null;
    if (!res.ok) throw new Error("Failed to fetch active ticket");
    return res.json();
  },

  getHistory: async (): Promise<TicketResponse[]> => {
    const res = await apiFetch(`/api/tickets/history`, {
      headers: getHeaders(),
    });
    if (!res.ok) throw new Error("Failed to fetch ticket history");
    return res.json();
  },

  verifyTicket: async (data: VerifyTicketRequest): Promise<VerifyTicketResponse> => {
    const res = await apiFetch(`/api/tickets/verify`, {
      method: "POST",
      headers: getHeaders(),
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error("Failed to verify ticket");
    return res.json();
  }
};
