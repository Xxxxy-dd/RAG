import type { QARequest, QAResponse } from './types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';

export async function askQuestion(payload: QARequest): Promise<QAResponse> {
  const response = await fetch(`${API_BASE_URL}/qa`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    let message = `请求失败: ${response.status}`;
    try {
      const data = await response.json();
      message = data?.detail ? String(data.detail) : message;
    } catch {
      // ignore
    }
    throw new Error(message);
  }

  return response.json() as Promise<QAResponse>;
}

export async function clearSession(session_id: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/session/${encodeURIComponent(session_id)}`, {
    method: 'DELETE',
  });

  if (!response.ok) {
    let message = `请求失败: ${response.status}`;
    try {
      const data = await response.json();
      message = data?.detail ? String(data.detail) : message;
    } catch {
      // ignore
    }
    throw new Error(message);
  }
}

export interface SessionMessage {
  message_id: string;
  role: string;
  text: string;
  seq: number;
  metadata: string | null;
  created_at: string;
}

export interface SessionMessagesResponse {
  session_id: string;
  count: number;
  messages: SessionMessage[];
}

export async function getSessionMessages(session_id: string, limit = 20): Promise<SessionMessagesResponse> {
  const response = await fetch(`${API_BASE_URL}/session/${encodeURIComponent(session_id)}/messages?limit=${limit}`);

  if (!response.ok) {
    let message = `请求失败: ${response.status}`;
    try {
      const data = await response.json();
      message = data?.detail ? String(data.detail) : message;
    } catch {
      // ignore
    }
    throw new Error(message);
  }

  return response.json() as Promise<SessionMessagesResponse>;
}
